#include "PhoneCameraSource.h"
#include <mfapi.h>
#include <mferror.h>
#include <ks.h>
#include <ksmedia.h>
#include <ksproxy.h>
#include <wrl.h>
#include <chrono>
#include <deque>
#include <memory>

namespace Magnolie::PhoneCamera
{
    using Microsoft::WRL::ComPtr;
    using Microsoft::WRL::RuntimeClass;
    using Microsoft::WRL::RuntimeClassFlags;
    using Microsoft::WRL::ClassicCom;
    using Microsoft::WRL::ChainInterfaces;
    using Clock = std::chrono::steady_clock;
    class Source;

    struct State
    {
        explicit State(SourceOwner value) : owner(value), lifetime(value.lifetime), samples(SampleCurrent, this, true) {}
        static HRESULT SampleCurrent(void* value) noexcept
        {
            auto& state = *static_cast<State*>(value);
            if (state.shutdown) return MF_E_SHUTDOWN;
            HRESULT hr = state.owner.current(state.owner.context);
            return FAILED(hr) ? hr : state.owner.sending(state.owner.context);
        }
        std::recursive_mutex gate;
        SourceOwner owner;
        ComPtr<IUnknown> lifetime;
        Samples samples;
        std::shared_ptr<PresentationClock> clock;
        GUID clockScope = GUID_NULL;
        bool shutdown = false, started = false, announced = false, received = false;
        MF_STREAM_STATE streamState = MF_STREAM_STATE_STOPPED;
        Clock::time_point startedAt{}, receivedAt{};
        GUID descriptorId{};
        MFWORKITEM_KEY timer = 0;
        ComPtr<IMFMediaEventQueue> sourceEvents, streamEvents;
        ComPtr<IMFStreamDescriptor> descriptor;
        ComPtr<IMFPresentationDescriptor> presentation;
        ComPtr<IMFAttributes> sourceAttributes, streamAttributes;
        ComPtr<IMFSample> latest;
        std::deque<ComPtr<IUnknown>> requests;
        std::size_t outstanding = 0;
    };

    const GUID DescriptorOwner = {0xa45df0d1, 0xa193, 0x4fd2, {0x94, 0x6b, 0x30, 0x44, 0xa4, 0x2c, 0x6c, 0xe8}};
    const GUID SampleArrivedAt = {0xc89df77b, 0x45ae, 0x4185, {0xa9, 0x63, 0x54, 0xc8, 0x92, 0xc8, 0xa5, 0x11}};
    static UINT64 MonotonicUs() noexcept
    { return static_cast<UINT64>(std::chrono::duration_cast<std::chrono::microseconds>(Clock::now().time_since_epoch()).count()); }

    class Stream final : public RuntimeClass<RuntimeClassFlags<ClassicCom>, ChainInterfaces<IMFMediaStream2, IMFMediaStream, IMFMediaEventGenerator>>
    {
    public:
        Stream(std::shared_ptr<State> state, IMFMediaSource* parent) : state_(std::move(state)), parent_(parent) {}
        void Detach() noexcept { parent_.Reset(); }
        STDMETHODIMP GetEvent(DWORD flags, IMFMediaEvent** result) override
        { return Event(flags, nullptr, result); }
        STDMETHODIMP BeginGetEvent(IMFAsyncCallback* callback, IUnknown* context) override
        { return state_->streamEvents->BeginGetEvent(callback, context); }
        STDMETHODIMP EndGetEvent(IMFAsyncResult* result, IMFMediaEvent** event) override
        { if (!result) { if (event) *event = nullptr; return E_POINTER; } return Event(0, result, event); }
        STDMETHODIMP QueueEvent(MediaEventType, REFGUID, HRESULT, const PROPVARIANT*) override
        { return E_NOTIMPL; }
        STDMETHODIMP GetMediaSource(IMFMediaSource** result) override;
        STDMETHODIMP GetStreamDescriptor(IMFStreamDescriptor** result) override;
        STDMETHODIMP RequestSample(IUnknown* token) override;
        STDMETHODIMP SetStreamState(MF_STREAM_STATE state) override;
        STDMETHODIMP GetStreamState(MF_STREAM_STATE* state) override;
    private:
        HRESULT Event(DWORD flags, IMFAsyncResult* async, IMFMediaEvent** result) noexcept;
        std::shared_ptr<State> state_;
        ComPtr<IMFMediaSource> parent_;
    };

    class Source final : public RuntimeClass<RuntimeClassFlags<ClassicCom>,
        ChainInterfaces<IMFMediaSourceEx, IMFMediaSource, IMFMediaEventGenerator>, IMFGetService, IKsControl, IMFSampleAllocatorControl, IFrameFeed, IMFAsyncCallback>
    {
    public:
        explicit Source(std::shared_ptr<State> state) : state_(std::move(state)) {}
        ~Source() { Shutdown(); }
        HRESULT Initialize() noexcept;
        HRESULT CurrentLocked() noexcept;
        HRESULT DeliverLocked() noexcept;
        HRESULT RetireLocked(HRESULT reason) noexcept;
        STDMETHODIMP GetEvent(DWORD flags, IMFMediaEvent** result) override
        { return state_->sourceEvents->GetEvent(flags, result); }
        STDMETHODIMP BeginGetEvent(IMFAsyncCallback* callback, IUnknown* context) override
        { return state_->sourceEvents->BeginGetEvent(callback, context); }
        STDMETHODIMP EndGetEvent(IMFAsyncResult* result, IMFMediaEvent** event) override
        { return state_->sourceEvents->EndGetEvent(result, event); }
        STDMETHODIMP QueueEvent(MediaEventType, REFGUID, HRESULT, const PROPVARIANT*) override
        { return E_NOTIMPL; }
        STDMETHODIMP GetCharacteristics(DWORD* flags) override;
        STDMETHODIMP CreatePresentationDescriptor(IMFPresentationDescriptor** result) override;
        STDMETHODIMP Start(IMFPresentationDescriptor* presentation, const GUID* format, const PROPVARIANT* start) override;
        STDMETHODIMP Stop() override;
        STDMETHODIMP Pause() override { return MF_E_INVALID_STATE_TRANSITION; }
        STDMETHODIMP Shutdown() override
        { std::lock_guard<std::recursive_mutex> lock(state_->gate); return RetireLocked(S_OK); }
        STDMETHODIMP GetSourceAttributes(IMFAttributes** result) override;
        STDMETHODIMP GetStreamAttributes(DWORD id, IMFAttributes** result) override;
        STDMETHODIMP SetD3DManager(IUnknown* manager) override
        { std::lock_guard<std::recursive_mutex> lock(state_->gate); HRESULT hr = CurrentLocked(); return FAILED(hr) ? hr : manager ? E_NOTIMPL : S_OK; }
        STDMETHODIMP GetService(REFGUID, REFIID, LPVOID* result) override
        { if (!result) return E_POINTER; *result = nullptr; return MF_E_UNSUPPORTED_SERVICE; }
        STDMETHODIMP SetDefaultAllocator(DWORD id, IUnknown*) override
        { std::lock_guard<std::recursive_mutex> lock(state_->gate); HRESULT hr = CurrentLocked(); return FAILED(hr) ? hr : id ? MF_E_INVALIDSTREAMNUMBER : E_NOTIMPL; }
        STDMETHODIMP GetAllocatorUsage(DWORD id, DWORD* input, MFSampleAllocatorUsage* usage) override;
        STDMETHODIMP KsProperty(PKSPROPERTY, ULONG, LPVOID, ULONG, ULONG* returned) override
        { if (!returned) return E_POINTER; *returned = 0; return HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND); }
        STDMETHODIMP KsMethod(PKSMETHOD, ULONG, LPVOID, ULONG, ULONG* returned) override
        { if (!returned) return E_POINTER; *returned = 0; return HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND); }
        STDMETHODIMP KsEvent(PKSEVENT, ULONG, LPVOID, ULONG, ULONG* returned) override
        { if (returned) *returned = 0; return HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND); }
        STDMETHODIMP PublishVideo(const BYTE* data, DWORD size, LONGLONG sequence, LONGLONG ptsUs) override;
        STDMETHODIMP GetParameters(DWORD*, DWORD*) override { return E_NOTIMPL; }
        STDMETHODIMP Invoke(IMFAsyncResult*) override;
    private:
        HRESULT ScheduleLocked() noexcept
        { return MFScheduleWorkItem(this, nullptr, -50, &state_->timer); }
        std::shared_ptr<State> state_;
        ComPtr<Stream> stream_;
    };

    HRESULT Source::Initialize() noexcept
    {
        std::lock_guard<std::recursive_mutex> lock(state_->gate);
        auto& s = *state_;
        HRESULT hr = MFCreateEventQueue(&s.sourceEvents);
        if (SUCCEEDED(hr)) hr = MFCreateEventQueue(&s.streamEvents);
        ComPtr<IMFMediaType> type;
        if (SUCCEEDED(hr)) hr = Samples::VideoType(&type);
        IMFMediaType* types[] = {type.Get()};
        if (SUCCEEDED(hr)) hr = MFCreateStreamDescriptor(0, 1, types, &s.descriptor);
        ComPtr<IMFMediaTypeHandler> handler;
        if (SUCCEEDED(hr)) hr = s.descriptor->GetMediaTypeHandler(&handler);
        if (SUCCEEDED(hr)) hr = handler->SetCurrentMediaType(type.Get());
        IMFStreamDescriptor* streams[] = {s.descriptor.Get()};
        if (SUCCEEDED(hr)) hr = MFCreatePresentationDescriptor(1, streams, &s.presentation);
        if (SUCCEEDED(hr)) hr = s.presentation->SelectStream(0);
        if (SUCCEEDED(hr)) hr = CoCreateGuid(&s.descriptorId);
        if (SUCCEEDED(hr)) hr = s.presentation->SetGUID(DescriptorOwner, s.descriptorId);
        if (SUCCEEDED(hr)) hr = MFCreateAttributes(&s.sourceAttributes, 2);
        if (SUCCEEDED(hr)) hr = MFCreateAttributes(&s.streamAttributes, 4);
        if (SUCCEEDED(hr)) hr = s.sourceAttributes->SetUINT32(MF_DEVICESTREAM_ATTRIBUTE_FRAMESOURCE_TYPES, MFFrameSourceTypes_Color);
        if (SUCCEEDED(hr)) hr = s.streamAttributes->SetUINT32(MF_DEVICESTREAM_ATTRIBUTE_FRAMESOURCE_TYPES, MFFrameSourceTypes_Color);
        if (SUCCEEDED(hr)) hr = s.streamAttributes->SetUINT32(MF_DEVICESTREAM_STREAM_ID, 0);
        const GUID capture = {STATIC_PINNAME_VIDEO_CAPTURE};
        if (SUCCEEDED(hr)) hr = s.streamAttributes->SetGUID(MF_DEVICESTREAM_STREAM_CATEGORY, capture);
        if (SUCCEEDED(hr))
        {
            stream_ = Microsoft::WRL::Make<Stream>(state_, static_cast<IMFMediaSourceEx*>(this));
            if (!stream_) hr = E_OUTOFMEMORY;
        }
        if (SUCCEEDED(hr)) hr = CurrentLocked();
        if (SUCCEEDED(hr)) hr = ScheduleLocked();
        if (FAILED(hr)) RetireLocked(hr);
        return hr;
    }

    HRESULT Source::CurrentLocked() noexcept
    {
        if (state_->shutdown) return MF_E_SHUTDOWN;
        const HRESULT hr = state_->owner.current(state_->owner.context);
        return FAILED(hr) ? RetireLocked(hr) : state_->shutdown ? MF_E_SHUTDOWN : S_OK;
    }

    HRESULT Source::RetireLocked(HRESULT reason) noexcept
    {
        auto& s = *state_;
        if (s.shutdown) return MF_E_SHUTDOWN;
        s.shutdown = true; s.started = false; s.samples.Retire();
        s.latest.Reset(); s.requests.clear(); s.outstanding = 0;
        if (s.timer) { MFCancelWorkItem(s.timer); s.timer = 0; }
        if (s.sourceEvents) s.sourceEvents->Shutdown();
        if (s.streamEvents) s.streamEvents->Shutdown();
        if (stream_) stream_->Detach();
        // An anchored source has the exact SAME retirement callback/context as
        // its clock. Notify through that clock once with the genuine reason,
        // while the callback context is still valid through Shutdown.
        if (s.clock) s.clock->Stop(reason);
        else s.owner.retired(s.owner.context, reason);
        return FAILED(reason) ? reason : S_OK;
    }

    HRESULT Source::GetCharacteristics(DWORD* flags)
    {
        if (!flags) return E_POINTER;
        *flags = 0; std::lock_guard<std::recursive_mutex> lock(state_->gate);
        HRESULT hr = CurrentLocked(); if (SUCCEEDED(hr)) *flags = MFMEDIASOURCE_IS_LIVE;
        return hr;
    }

    HRESULT Source::CreatePresentationDescriptor(IMFPresentationDescriptor** result)
    {
        if (!result) return E_POINTER;
        *result = nullptr; std::lock_guard<std::recursive_mutex> lock(state_->gate);
        HRESULT hr = CurrentLocked(); return FAILED(hr) ? hr : state_->presentation->Clone(result);
    }

    HRESULT Source::Start(IMFPresentationDescriptor* presentation, const GUID* format, const PROPVARIANT* start)
    {
        if (!presentation || !start) return E_POINTER;
        std::lock_guard<std::recursive_mutex> lock(state_->gate);
        HRESULT hr = CurrentLocked(); if (FAILED(hr)) return hr;
        if (format && *format != GUID_NULL) return MF_E_UNSUPPORTED_TIME_FORMAT;
        if (start->vt != VT_EMPTY && !(start->vt == VT_I8 && start->hVal.QuadPart == 0)) return MF_E_INVALIDREQUEST;
        auto& s = *state_;
        if (s.started) return MF_E_INVALID_STATE_TRANSITION;
        GUID id{}; DWORD count = 0; BOOL selected = FALSE;
        ComPtr<IMFStreamDescriptor> descriptor;
        if (FAILED(presentation->GetGUID(DescriptorOwner, &id)) || id != s.descriptorId ||
            FAILED(presentation->GetStreamDescriptorCount(&count)) || count != 1 ||
            FAILED(presentation->GetStreamDescriptorByIndex(0, &selected, &descriptor)) || !selected)
            return E_INVALIDARG;
        DWORD streamId = 1; ComPtr<IMFMediaTypeHandler> handler; ComPtr<IMFMediaType> type, expected;
        hr = descriptor->GetStreamIdentifier(&streamId);
        if (SUCCEEDED(hr) && streamId != 0) hr = E_INVALIDARG;
        if (SUCCEEDED(hr)) hr = descriptor->GetMediaTypeHandler(&handler);
        if (SUCCEEDED(hr)) hr = handler->GetCurrentMediaType(&type);
        if (SUCCEEDED(hr)) hr = Samples::VideoType(&expected);
        DWORD equal = 0;
        if (SUCCEEDED(hr)) hr = expected->IsEqual(type.Get(), &equal);
        if (hr != S_OK) return FAILED(hr) ? hr : MF_E_INVALIDMEDIATYPE;
        hr = CurrentLocked(); if (FAILED(hr)) return hr;
        s.started = true; s.streamState = MF_STREAM_STATE_RUNNING;
        s.startedAt = Clock::now(); s.received = false; s.latest.Reset();
        s.outstanding -= s.requests.size(); s.requests.clear();
        hr = s.sourceEvents->QueueEventParamUnk(s.announced ? MEUpdatedStream : MENewStream, GUID_NULL, S_OK, stream_.Get());
        PROPVARIANT zero{}; zero.vt = VT_I8; zero.hVal.QuadPart = 0;
        if (SUCCEEDED(hr)) hr = s.streamEvents->QueueEventParamVar(MEStreamStarted, GUID_NULL, S_OK, &zero);
        if (SUCCEEDED(hr)) hr = s.sourceEvents->QueueEventParamVar(MESourceStarted, GUID_NULL, S_OK, &zero);
        if (FAILED(hr)) return RetireLocked(hr);
        s.announced = true; return S_OK;
    }

    HRESULT Source::Stop()
    {
        std::lock_guard<std::recursive_mutex> lock(state_->gate);
        HRESULT hr = CurrentLocked(); if (FAILED(hr)) return hr;
        auto& s = *state_;
        if (!s.started) return MF_E_INVALID_STATE_TRANSITION;
        s.started = false; s.streamState = MF_STREAM_STATE_STOPPED;
        s.latest.Reset(); s.outstanding -= s.requests.size(); s.requests.clear();
        hr = s.streamEvents->QueueEventParamVar(MEStreamStopped, GUID_NULL, S_OK, nullptr);
        if (SUCCEEDED(hr)) hr = s.sourceEvents->QueueEventParamVar(MESourceStopped, GUID_NULL, S_OK, nullptr);
        return FAILED(hr) ? RetireLocked(hr) : S_OK;
    }

    HRESULT Source::GetSourceAttributes(IMFAttributes** result)
    {
        if (!result) return E_POINTER;
        *result = nullptr; std::lock_guard<std::recursive_mutex> lock(state_->gate);
        HRESULT hr = CurrentLocked();
        if (SUCCEEDED(hr)) hr = MFCreateAttributes(result, 2);
        if (SUCCEEDED(hr)) hr = state_->sourceAttributes->CopyAllItems(*result);
        if (FAILED(hr) && *result) { (*result)->Release(); *result = nullptr; }
        return hr;
    }

    HRESULT Source::GetStreamAttributes(DWORD id, IMFAttributes** result)
    {
        if (!result) return E_POINTER;
        *result = nullptr; std::lock_guard<std::recursive_mutex> lock(state_->gate);
        HRESULT hr = CurrentLocked();
        if (SUCCEEDED(hr) && id) hr = MF_E_INVALIDSTREAMNUMBER;
        if (SUCCEEDED(hr)) hr = MFCreateAttributes(result, 4);
        if (SUCCEEDED(hr)) hr = state_->streamAttributes->CopyAllItems(*result);
        if (FAILED(hr) && *result) { (*result)->Release(); *result = nullptr; }
        return hr;
    }

    HRESULT Source::GetAllocatorUsage(DWORD id, DWORD* input, MFSampleAllocatorUsage* usage)
    {
        if (!input || !usage) return E_POINTER;
        *input = 0; *usage = MFSampleAllocatorUsage_UsesCustomAllocator;
        std::lock_guard<std::recursive_mutex> lock(state_->gate);
        HRESULT hr = CurrentLocked(); return FAILED(hr) ? hr : id ? MF_E_INVALIDSTREAMNUMBER : S_OK;
    }

    HRESULT Source::DeliverLocked() noexcept
    {
        auto& s = *state_;
        if (!s.started || s.streamState != MF_STREAM_STATE_RUNNING || !s.latest || s.requests.empty()) return S_OK;
        HRESULT hr = CurrentLocked();
        if (SUCCEEDED(hr)) hr = s.owner.sending(s.owner.context);
        if (SUCCEEDED(hr) && s.clock) hr = s.clock->RequireImportedAnchor(s.clockScope);
        if (SUCCEEDED(hr) && Clock::now() - s.receivedAt > std::chrono::milliseconds(250)) hr = MF_E_NET_TIMEOUT;
        if (FAILED(hr)) return s.shutdown ? hr : RetireLocked(hr);
        auto sample = std::move(s.latest); auto token = std::move(s.requests.front()); s.requests.pop_front();
        if (token) hr = sample->SetUnknown(MFSampleExtension_Token, token.Get());
        if (SUCCEEDED(hr)) hr = s.owner.sending(s.owner.context);
        if (SUCCEEDED(hr)) hr = CurrentLocked();
        if (SUCCEEDED(hr)) hr = s.streamEvents->QueueEventParamUnk(MEMediaSample, GUID_NULL, S_OK, sample.Get());
        return FAILED(hr) ? (s.shutdown ? hr : RetireLocked(hr)) : S_OK;
    }

    HRESULT Source::PublishVideo(const BYTE* data, DWORD size, LONGLONG sequence, LONGLONG ptsUs)
    {
        std::lock_guard<std::recursive_mutex> lock(state_->gate);
        HRESULT hr = CurrentLocked(); if (FAILED(hr)) return hr;
        auto& s = *state_; ComPtr<IMFSample> sample;
        if (s.clock)
        {
            hr = s.clock->RequireImportedAnchor(s.clockScope);
            if (FAILED(hr)) return RetireLocked(hr);
        }
        hr = s.samples.Video(data, size, sequence, ptsUs, &sample);
        if (FAILED(hr)) return RetireLocked(hr);
        if (s.clock)
        {
            LONGLONG mapped = 0; hr = s.clock->Map(ptsUs, &mapped);
            if (SUCCEEDED(hr)) hr = sample->SetSampleTime(mapped * 10);
            if (FAILED(hr))
            {
                // This private sample has not entered a client event queue.
                ComPtr<IMFMediaBuffer> buffer; BYTE* bytes = nullptr; DWORD length = 0;
                if (SUCCEEDED(sample->GetBufferByIndex(0, &buffer)) && SUCCEEDED(buffer->Lock(&bytes, nullptr, &length)))
                { SecureZeroMemory(bytes, length); buffer->Unlock(); }
                return RetireLocked(hr);
            }
        }
        hr = sample->SetUINT64(SampleArrivedAt, MonotonicUs());
        if (FAILED(hr)) return RetireLocked(hr);
        s.received = true; s.receivedAt = Clock::now();
        // Whole unsent video frames may replace one another; pending native
        // requests are bounded separately. No audio path or silence is invented.
        s.latest = std::move(sample);
        return DeliverLocked();
    }

    HRESULT Source::Invoke(IMFAsyncResult*)
    {
        std::lock_guard<std::recursive_mutex> lock(state_->gate);
        auto& s = *state_; s.timer = 0;
        HRESULT hr = CurrentLocked(); if (FAILED(hr)) return S_OK;
        const auto now = Clock::now();
        if (s.started && ((s.received && now - s.receivedAt > std::chrono::milliseconds(250)) ||
            (!s.received && now - s.startedAt > std::chrono::seconds(5))))
        { RetireLocked(MF_E_NET_TIMEOUT); return S_OK; }
        hr = ScheduleLocked(); if (FAILED(hr)) RetireLocked(hr);
        return S_OK;
    }

    STDMETHODIMP Stream::GetMediaSource(IMFMediaSource** result)
    {
        if (!result) return E_POINTER;
        *result = nullptr; std::lock_guard<std::recursive_mutex> lock(state_->gate);
        if (state_->shutdown) return MF_E_SHUTDOWN;
        auto parent = parent_;
        HRESULT hr = static_cast<Source*>(parent.Get())->CurrentLocked(); if (FAILED(hr)) return hr;
        return parent_.CopyTo(result);
    }
    STDMETHODIMP Stream::GetStreamDescriptor(IMFStreamDescriptor** result)
    {
        if (!result) return E_POINTER;
        *result = nullptr; std::lock_guard<std::recursive_mutex> lock(state_->gate);
        if (state_->shutdown) return MF_E_SHUTDOWN;
        auto parent = parent_;
        HRESULT hr = static_cast<Source*>(parent.Get())->CurrentLocked(); if (FAILED(hr)) return hr;
        return state_->descriptor.CopyTo(result);
    }
    HRESULT Stream::Event(DWORD flags, IMFAsyncResult* async, IMFMediaEvent** result) noexcept
    {
        if (!result) return E_POINTER;
        *result = nullptr;
        {
            std::lock_guard<std::recursive_mutex> lock(state_->gate);
            if (state_->shutdown) return MF_E_SHUTDOWN;
            auto parent = parent_;
            HRESULT hr = static_cast<Source*>(parent.Get())->CurrentLocked(); if (FAILED(hr)) return hr;
        }
        // Never hold the state lock across a blocking event wait.
        HRESULT hr = async ? state_->streamEvents->EndGetEvent(async, result) : state_->streamEvents->GetEvent(flags, result);
        if (FAILED(hr)) return hr;
        std::lock_guard<std::recursive_mutex> lock(state_->gate);
        auto parent = parent_;
        hr = state_->shutdown ? MF_E_SHUTDOWN : static_cast<Source*>(parent.Get())->CurrentLocked();
        if (SUCCEEDED(hr))
        {
            MediaEventType type = MEUnknown; hr = (*result)->GetType(&type);
            if (SUCCEEDED(hr) && type == MEMediaSample)
            {
                hr = state_->owner.sending(state_->owner.context);
                if (SUCCEEDED(hr) && state_->clock) hr = state_->clock->RequireImportedAnchor(state_->clockScope);
                PROPVARIANT payload{};
                ComPtr<IMFSample> sample;
                UINT64 arrived = 0;
                if (SUCCEEDED(hr)) hr = (*result)->GetValue(&payload);
                if (SUCCEEDED(hr)) hr = payload.vt == VT_UNKNOWN && payload.punkVal ? payload.punkVal->QueryInterface(IID_PPV_ARGS(&sample)) : E_UNEXPECTED;
                PropVariantClear(&payload);
                if (SUCCEEDED(hr)) hr = sample->GetUINT64(SampleArrivedAt, &arrived);
                const UINT64 now = MonotonicUs();
                if (SUCCEEDED(hr) && (arrived > now || now - arrived > 250000)) hr = MF_E_NET_TIMEOUT;
                if (SUCCEEDED(hr) && !state_->outstanding) hr = E_UNEXPECTED;
                if (SUCCEEDED(hr)) --state_->outstanding;
                if (FAILED(hr)) static_cast<Source*>(parent.Get())->RetireLocked(hr);
            }
        }
        if (FAILED(hr) && *result) { (*result)->Release(); *result = nullptr; }
        return hr;
    }
    STDMETHODIMP Stream::RequestSample(IUnknown* token)
    {
        std::lock_guard<std::recursive_mutex> lock(state_->gate);
        if (state_->shutdown) return MF_E_SHUTDOWN;
        auto parent = parent_;
        auto* source = static_cast<Source*>(parent.Get());
        HRESULT hr = source->CurrentLocked(); if (FAILED(hr)) return hr;
        auto& s = *state_;
        if (!s.started || s.streamState != MF_STREAM_STATE_RUNNING) return MF_E_INVALIDREQUEST;
        // Include queued-but-unread sample events, not just unfilled requests.
        if (s.outstanding >= 16) return source->RetireLocked(MF_E_NOTACCEPTING);
        try { s.requests.emplace_back(token); } catch (...) { return source->RetireLocked(E_OUTOFMEMORY); }
        ++s.outstanding;
        return source->DeliverLocked();
    }
    STDMETHODIMP Stream::SetStreamState(MF_STREAM_STATE stateValue)
    {
        std::lock_guard<std::recursive_mutex> lock(state_->gate);
        if (state_->shutdown) return MF_E_SHUTDOWN;
        auto parent = parent_;
        HRESULT hr = static_cast<Source*>(parent.Get())->CurrentLocked(); if (FAILED(hr)) return hr;
        if (stateValue != MF_STREAM_STATE_RUNNING && stateValue != MF_STREAM_STATE_STOPPED && stateValue != MF_STREAM_STATE_PAUSED)
            return E_INVALIDARG;
        if (stateValue == MF_STREAM_STATE_RUNNING && !state_->started) return MF_E_INVALID_STATE_TRANSITION;
        state_->streamState = stateValue;
        if (stateValue != MF_STREAM_STATE_RUNNING)
        { state_->latest.Reset(); state_->outstanding -= state_->requests.size(); state_->requests.clear(); }
        return S_OK;
    }
    STDMETHODIMP Stream::GetStreamState(MF_STREAM_STATE* stateValue)
    {
        if (!stateValue) return E_POINTER;
        *stateValue = MF_STREAM_STATE_STOPPED; std::lock_guard<std::recursive_mutex> lock(state_->gate);
        if (state_->shutdown) return MF_E_SHUTDOWN;
        auto parent = parent_;
        HRESULT hr = static_cast<Source*>(parent.Get())->CurrentLocked(); if (FAILED(hr)) return hr;
        *stateValue = state_->streamState; return S_OK;
    }

    static HRESULT CreateBoundSource(const SourceOwner& owner, const GUID& scope,
        const std::shared_ptr<PresentationClock>& clock, IMFMediaSourceEx** result, IFrameFeed** feed) noexcept
    {
        if (result) *result = nullptr;
        if (feed) *feed = nullptr;
        if (!result || !feed) return E_POINTER;
        if (!owner.current || !owner.sending || !owner.retired) return E_INVALIDARG;
        try
        {
            auto state = std::make_shared<State>(owner);
            state->clock = clock; state->clockScope = scope;
            auto source = Microsoft::WRL::Make<Source>(state);
            if (!source) return E_OUTOFMEMORY;
            HRESULT hr = source->Initialize();
            if (SUCCEEDED(hr)) hr = source.CopyTo(result);
            if (SUCCEEDED(hr)) hr = source.CopyTo(feed);
            if (FAILED(hr)) { source->Shutdown(); if (*result) { (*result)->Release(); *result = nullptr; } }
            return hr;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    HRESULT CreateSource(const SourceOwner& owner, IMFMediaSourceEx** result, IFrameFeed** feed) noexcept
    { return CreateBoundSource(owner, GUID_NULL, {}, result, feed); }
    HRESULT CreateAnchoredSource(const SourceOwner& owner, const GUID& scope,
        const std::shared_ptr<PresentationClock>& clock, IMFMediaSourceEx** result, IFrameFeed** feed) noexcept
    {
        if (result) *result = nullptr;
        if (feed) *feed = nullptr;
        if (!result || !feed) return E_POINTER;
        if (!clock || scope == GUID_NULL || !clock->MatchesOwner({owner.current, owner.sending, owner.retired, owner.context})) return E_ACCESSDENIED;
        return CreateBoundSource(owner, scope, clock, result, feed);
    }
}
