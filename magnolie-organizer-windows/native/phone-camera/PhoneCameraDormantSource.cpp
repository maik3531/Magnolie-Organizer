#include "PhoneCameraDormantSource.h"
#include <mfapi.h>
#include <mferror.h>
#include <ks.h>
#include <ksproxy.h>
#include <wrl.h>

namespace Magnolie::PhoneCamera
{
    using Microsoft::WRL::ComPtr;
    struct DormantSourceState
    {
        explicit DormantSourceState(RegistrationLifetime value)
            : registration(value), lifetime(value.lifetime), identity(std::make_shared<const BYTE>(BYTE{0})) {}
        const RegistrationLifetime registration;
        const ComPtr<IUnknown> lifetime;
        const std::shared_ptr<const BYTE> identity;
        std::mutex gate;
        bool spent = false, stopped = false;
        ComPtr<IMFMediaSourceEx> source;
        ComPtr<IFrameFeed> feed;
        ComPtr<IMFAttributes> metadata; // Owned snapshot; NEVER source/capture authority.

        HRESULT Stop() noexcept
        {
            ComPtr<IMFMediaSourceEx> original;
            ComPtr<IMFAttributes> originalMetadata;
            {
                std::lock_guard<std::mutex> lock(gate);
                if (stopped) return MF_E_SHUTDOWN;
                stopped = true; spent = true;
                original = std::move(source); feed.Reset();
                originalMetadata = std::move(metadata);
            }
            // Source callbacks/shutdown may signal this controller. Never hold
            // the shell lock across any source call or blocking MF event wait.
            if (original) original->Shutdown();
            // Metadata can contain arbitrary COM objects. Release outside the
            // shell lock, before registry cleanup, with stopped already sticky.
            originalMetadata.Reset();
            if (registration.closed) registration.closed(registration.context);
            return S_OK;
        }
        HRESULT Current() noexcept
        {
            {
                std::lock_guard<std::mutex> lock(gate);
                if (stopped) return MF_E_SHUTDOWN;
            }
            const HRESULT hr = registration.current(registration.context);
            if (hr != S_OK) { Stop(); return FAILED(hr) ? hr : E_ACCESSDENIED; }
            std::lock_guard<std::mutex> lock(gate);
            return stopped ? MF_E_SHUTDOWN : S_OK;
        }
        HRESULT Bound(ComPtr<IMFMediaSourceEx>& result) noexcept
        {
            result.Reset();
            HRESULT hr = Current(); if (FAILED(hr)) return hr;
            {
                std::lock_guard<std::mutex> lock(gate);
                if (stopped) return MF_E_SHUTDOWN;
                if (!source) return MF_E_NOT_INITIALIZED;
                result = source;
            }
            hr = Current();
            if (FAILED(hr)) result.Reset();
            return hr;
        }
    };

    class DormantSource final : public Microsoft::WRL::RuntimeClass<
        Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>,
        Microsoft::WRL::ChainInterfaces<IMFMediaSourceEx, IMFMediaSource, IMFMediaEventGenerator>,
        IMFGetService, IKsControl, IMFSampleAllocatorControl>
    {
    public:
        explicit DormantSource(std::shared_ptr<DormantSourceState> state) : state_(std::move(state)) {}
        ~DormantSource() { state_->Stop(); }
        STDMETHODIMP GetEvent(DWORD flags, IMFMediaEvent** result) override
        {
            if (!result) return E_POINTER; *result = nullptr;
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            return FAILED(hr) ? hr : source->GetEvent(flags, result);
        }
        STDMETHODIMP BeginGetEvent(IMFAsyncCallback* callback, IUnknown* context) override
        {
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            return FAILED(hr) ? hr : source->BeginGetEvent(callback, context);
        }
        STDMETHODIMP EndGetEvent(IMFAsyncResult* async, IMFMediaEvent** result) override
        {
            if (!result) return E_POINTER; *result = nullptr;
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            return FAILED(hr) ? hr : source->EndGetEvent(async, result);
        }
        STDMETHODIMP QueueEvent(MediaEventType, REFGUID, HRESULT, const PROPVARIANT*) override { return E_NOTIMPL; }
        STDMETHODIMP GetCharacteristics(DWORD* flags) override
        {
            if (!flags) return E_POINTER; *flags = 0;
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            if (hr == MF_E_NOT_INITIALIZED) { *flags = MFMEDIASOURCE_IS_LIVE; return S_OK; }
            return FAILED(hr) ? hr : source->GetCharacteristics(flags);
        }
        STDMETHODIMP CreatePresentationDescriptor(IMFPresentationDescriptor** result) override
        {
            if (!result) return E_POINTER; *result = nullptr;
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            return FAILED(hr) ? hr : source->CreatePresentationDescriptor(result);
        }
        STDMETHODIMP Start(IMFPresentationDescriptor* descriptor, const GUID* format, const PROPVARIANT* position) override
        {
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            return FAILED(hr) ? hr : source->Start(descriptor, format, position);
        }
        STDMETHODIMP Stop() override
        {
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            return FAILED(hr) ? hr : source->Stop();
        }
        STDMETHODIMP Pause() override
        {
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            return FAILED(hr) ? hr : source->Pause();
        }
        STDMETHODIMP Shutdown() override { return state_->Stop(); }
        STDMETHODIMP GetSourceAttributes(IMFAttributes** result) override
        {
            if (!result) return E_POINTER; *result = nullptr;
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            if (FAILED(hr) && hr != MF_E_NOT_INITIALIZED) return hr;
            ComPtr<IMFAttributes> metadata;
            {
                std::lock_guard<std::mutex> lock(state_->gate);
                if (state_->stopped) return MF_E_SHUTDOWN;
                metadata = state_->metadata;
            }
            // Return an independent store. Neither later activation changes nor
            // a caller modifying returned metadata may retarget this source.
            ComPtr<IMFAttributes> snapshot;
            hr = MFCreateAttributes(&snapshot, 8);
            if (SUCCEEDED(hr) && metadata) hr = metadata->CopyAllItems(snapshot.Get());
            if (SUCCEEDED(hr)) hr = snapshot->SetUINT32(MF_DEVICESTREAM_ATTRIBUTE_FRAMESOURCE_TYPES, MFFrameSourceTypes_Color);
            if (SUCCEEDED(hr) && source)
            {
                ComPtr<IMFAttributes> native;
                hr = source->GetSourceAttributes(&native);
                // Canonical source-owned media invariants override any caller
                // metadata collision. No attribute is ever read as authority.
                // CopyAllItems REPLACES the destination, it is not an overlay.
                UINT32 count = 0;
                if (SUCCEEDED(hr)) hr = native->GetCount(&count);
                for (UINT32 i = 0; SUCCEEDED(hr) && i < count; ++i)
                {
                    GUID key{}; PROPVARIANT item{};
                    hr = native->GetItemByIndex(i, &key, &item);
                    if (SUCCEEDED(hr)) hr = snapshot->SetItem(key, item);
                    PropVariantClear(&item);
                }
                DWORD flags = 0;
                if (SUCCEEDED(hr)) hr = source->GetCharacteristics(&flags);
            }
            if (SUCCEEDED(hr)) hr = state_->Current();
            return FAILED(hr) ? hr : snapshot.CopyTo(result);
        }
        STDMETHODIMP GetStreamAttributes(DWORD id, IMFAttributes** result) override
        {
            if (!result) return E_POINTER; *result = nullptr;
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            if (hr != MF_E_NOT_INITIALIZED) return FAILED(hr) ? hr : source->GetStreamAttributes(id, result);
            if (id) return MF_E_INVALIDSTREAMNUMBER;
            return MFCreateAttributes(result, 0);
        }
        STDMETHODIMP SetD3DManager(IUnknown* manager) override
        {
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            return FAILED(hr) ? hr : source->SetD3DManager(manager);
        }
        STDMETHODIMP GetService(REFGUID service, REFIID iid, LPVOID* result) override
        {
            if (!result) return E_POINTER; *result = nullptr;
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            ComPtr<IMFGetService> target;
            if (SUCCEEDED(hr)) hr = source.As(&target);
            return FAILED(hr) ? hr : target->GetService(service, iid, result);
        }
        STDMETHODIMP SetDefaultAllocator(DWORD id, IUnknown* allocator) override
        {
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            ComPtr<IMFSampleAllocatorControl> target;
            if (SUCCEEDED(hr)) hr = source.As(&target);
            return FAILED(hr) ? hr : target->SetDefaultAllocator(id, allocator);
        }
        STDMETHODIMP GetAllocatorUsage(DWORD id, DWORD* input, MFSampleAllocatorUsage* usage) override
        {
            if (!input || !usage) return E_POINTER;
            *input = 0; *usage = MFSampleAllocatorUsage_UsesCustomAllocator;
            ComPtr<IMFMediaSourceEx> source; HRESULT hr = state_->Bound(source);
            ComPtr<IMFSampleAllocatorControl> target;
            if (SUCCEEDED(hr)) hr = source.As(&target);
            return FAILED(hr) ? hr : target->GetAllocatorUsage(id, input, usage);
        }
        STDMETHODIMP KsProperty(PKSPROPERTY, ULONG, LPVOID, ULONG, ULONG* returned) override
        {
            if (!returned) return E_POINTER; *returned = 0;
            HRESULT hr = state_->Current();
            // The broker/property protocol is deliberately not implemented here.
            // In particular no external SET can manufacture SourceBindingProof.
            return FAILED(hr) ? hr : HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND);
        }
        STDMETHODIMP KsMethod(PKSMETHOD, ULONG, LPVOID, ULONG, ULONG* returned) override
        { if (!returned) return E_POINTER; *returned = 0; return HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND); }
        STDMETHODIMP KsEvent(PKSEVENT, ULONG, LPVOID, ULONG, ULONG* returned) override
        { if (returned) *returned = 0; return HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND); }
    private:
        const std::shared_ptr<DormantSourceState> state_;
    };

    SourceBindingProof::SourceBindingProof(const DormantSourceControl& target, SourceOwner owner,
        const GUID& scope, std::shared_ptr<PresentationClock> clock)
        : target_(target.state_->identity), owner_(owner), lifetime_(owner.lifetime), scope_(scope), clock_(std::move(clock)) {}

    HRESULT DormantSourceControl::Adopt(std::unique_ptr<SourceBindingProof> proof) noexcept
    {
        // A terminal callback can release this controller during the call.
        // Keep state locally and never dereference this again after callbacks.
        auto state = state_;
        if (!proof || proof->target_ != state->identity) return E_ACCESSDENIED;
        if (proof->scope_ == GUID_NULL || !proof->clock_ || !proof->owner_.current ||
            !proof->owner_.sending || !proof->owner_.retired || !proof->owner_.lifetime ||
            !proof->clock_->MatchesOwner({proof->owner_.current, proof->owner_.sending,
                proof->owner_.retired, proof->owner_.context, proof->owner_.lifetime})) return E_ACCESSDENIED;
        HRESULT hr = state->Current(); if (FAILED(hr)) return hr;
        {
            std::lock_guard<std::mutex> lock(state->gate);
            if (state->stopped || state->spent) return MF_E_SHUTDOWN;
            state->spent = true; // One authenticated adoption attempt, never rebind.
        }
        ComPtr<IMFMediaSourceEx> candidate; ComPtr<IFrameFeed> feed;
        hr = CreateAnchoredSource(proof->owner_, proof->scope_, proof->clock_, &candidate, &feed);
        if (SUCCEEDED(hr)) hr = state->Current();
        if (SUCCEEDED(hr))
        {
            std::lock_guard<std::mutex> lock(state->gate);
            if (state->stopped) hr = MF_E_SHUTDOWN;
            else { state->source = candidate; state->feed = feed; }
        }
        if (FAILED(hr)) { if (candidate) candidate->Shutdown(); state->Stop(); }
        return hr;
    }
    HRESULT DormantSourceControl::RequireBound() noexcept
    {
        auto state = state_;
        ComPtr<IMFMediaSourceEx> source;
        HRESULT hr = state->Bound(source); if (FAILED(hr)) return hr;
        DWORD flags = 0; return source->GetCharacteristics(&flags);
    }
    HRESULT DormantSourceControl::GetBoundFeed(IFrameFeed** result) noexcept
    {
        if (!result) return E_POINTER; *result = nullptr;
        auto state = state_;
        ComPtr<IMFMediaSourceEx> source;
        HRESULT hr = state->Bound(source); if (FAILED(hr)) return hr;
        DWORD flags = 0; hr = source->GetCharacteristics(&flags); if (FAILED(hr)) return hr;
        std::lock_guard<std::mutex> lock(state->gate);
        if (state->stopped || !state->feed) return MF_E_SHUTDOWN;
        return state->feed.CopyTo(result);
    }
    HRESULT DormantSourceControl::Stop() noexcept { auto state = state_; return state->Stop(); }
    DormantSourceControl::~DormantSourceControl() { state_->Stop(); }

    HRESULT CreateDormantSource(RegistrationLifetime registration, IMFMediaSourceEx** result,
        std::unique_ptr<DormantSourceControl>& control, IMFAttributes* activationMetadata) noexcept
    {
        if (!result) return E_POINTER; *result = nullptr;
        if (control || !registration.current || !registration.context || !registration.lifetime) return E_INVALIDARG;
        try
        {
            auto state = std::make_shared<DormantSourceState>(registration);
            HRESULT hr = state->Current(); if (FAILED(hr)) return hr;
            hr = MFCreateAttributes(&state->metadata, 8);
            if (SUCCEEDED(hr) && activationMetadata) hr = activationMetadata->CopyAllItems(state->metadata.Get());
            if (FAILED(hr)) return hr;
            auto shell = Microsoft::WRL::Make<DormantSource>(state);
            if (!shell) return E_OUTOFMEMORY;
            auto owner = std::unique_ptr<DormantSourceControl>(new DormantSourceControl(state));
            hr = state->Current(); if (FAILED(hr)) return hr;
            hr = shell.CopyTo(result); if (FAILED(hr)) return hr;
            control = std::move(owner); return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
}
