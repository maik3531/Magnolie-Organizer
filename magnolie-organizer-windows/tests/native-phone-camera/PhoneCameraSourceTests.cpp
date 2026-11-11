#include "../../native/phone-camera/PhoneCameraSource.h"
#include <mfapi.h>
#include <mferror.h>
#include <mfreadwrite.h>
#include <wrl.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <thread>
#include <vector>

using namespace Magnolie::PhoneCamera;
using Microsoft::WRL::ComPtr;

namespace
{
    void Check(bool value) { if (!value) throw std::runtime_error("source assertion"); }
    void Ok(HRESULT hr) { if (FAILED(hr)) { std::printf("HRESULT %08lx\n", static_cast<unsigned long>(hr)); Check(false); } }
    struct Owner
    {
        std::atomic_bool current{true}, sending{true};
        std::atomic_int retired{0}, sendChecks{0};
        std::atomic<HRESULT> reason{S_OK};
        std::atomic<HRESULT> firstReason{S_OK};
        std::atomic<LONGLONG> nativeNow{5000000};
        HANDLE event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        ~Owner() { if (event) CloseHandle(event); }
        static HRESULT Current(void* value) noexcept { return static_cast<Owner*>(value)->current ? S_OK : E_ACCESSDENIED; }
        static HRESULT Sending(void* value) noexcept
        { auto& o = *static_cast<Owner*>(value); ++o.sendChecks; return o.current && o.sending ? S_OK : E_ACCESSDENIED; }
        static void Retired(void* value, HRESULT reason) noexcept
        { auto& o = *static_cast<Owner*>(value); o.reason = reason; if (o.retired.fetch_add(1) == 0) o.firstReason = reason; SetEvent(o.event); }
        SourceOwner Callbacks() { return {Current, Sending, Retired, this}; }
        static LONGLONG Now(void* value) noexcept { return static_cast<Owner*>(value)->nativeNow; }
        ClockOwner ClockCallbacks() { return {Current, Sending, Retired, this, nullptr, Now}; }
    };
    struct Fixture
    {
        Owner owner;
        ComPtr<IMFMediaSourceEx> source;
        ComPtr<IFrameFeed> feed;
        ComPtr<IMFMediaStream2> stream;
        std::shared_ptr<PresentationClock> clock;
        GUID scope{};
        explicit Fixture(IUnknown* lifetime = nullptr, bool anchored = false)
        {
            auto callbacks = owner.Callbacks(); callbacks.lifetime = lifetime;
            if (anchored)
            {
                Ok(CoCreateGuid(&scope)); auto original = owner.ClockCallbacks(); original.lifetime = lifetime;
                clock = std::make_shared<PresentationClock>(original);
                Ok(CreateAnchoredSource(callbacks, scope, clock, &source, &feed));
            }
            else Ok(CreateSource(callbacks, &source, &feed));
        }
        ~Fixture() { if (source) source->Shutdown(); }
        void Start()
        {
            ComPtr<IMFPresentationDescriptor> pd; Ok(source->CreatePresentationDescriptor(&pd));
            PROPVARIANT start{}; start.vt = VT_EMPTY; Ok(source->Start(pd.Get(), nullptr, &start));
            ComPtr<IMFMediaEvent> event; Ok(source->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event));
            MediaEventType type{}; Ok(event->GetType(&type)); Check(type == MENewStream || type == MEUpdatedStream);
            PROPVARIANT value{}; Ok(event->GetValue(&value));
            Check(value.vt == VT_UNKNOWN && value.punkVal); Ok(value.punkVal->QueryInterface(IID_PPV_ARGS(&stream)));
            PropVariantClear(&value); event.Reset();
            Ok(source->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event)); Ok(event->GetType(&type)); Check(type == MESourceStarted);
            event.Reset(); Ok(stream->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event)); Ok(event->GetType(&type)); Check(type == MEStreamStarted);
        }
        void Publish(LONGLONG sequence, LONGLONG pts = 0, BYTE luma = 60)
        {
            std::vector<BYTE> data(Samples::VideoBytes, 128);
            std::fill(data.begin(), data.begin() + 640 * 480, luma);
            Ok(feed->PublishVideo(data.data(), static_cast<DWORD>(data.size()), sequence, pts));
        }
        ComPtr<IMFSample> Sample()
        {
            ComPtr<IMFMediaEvent> event; Ok(stream->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event));
            MediaEventType type{}; Ok(event->GetType(&type)); Check(type == MEMediaSample);
            PROPVARIANT value{}; Ok(event->GetValue(&value)); ComPtr<IMFSample> sample;
            Check(value.vt == VT_UNKNOWN); Ok(value.punkVal->QueryInterface(IID_PPV_ARGS(&sample))); PropVariantClear(&value);
            return sample;
        }
    };

    void InterfacesAndMetadata()
    {
        Fixture f; DWORD flags = 0; Ok(f.source->GetCharacteristics(&flags)); Check(flags == MFMEDIASOURCE_IS_LIVE);
        ComPtr<IMFMediaSource> base; ComPtr<IMFMediaEventGenerator> events;
        Ok(f.source.As(&base)); Ok(f.source.As(&events));
        ComPtr<IMFSampleAllocatorControl> allocation; Ok(f.source.As(&allocation));
        DWORD input = 99; MFSampleAllocatorUsage usage{}; Ok(allocation->GetAllocatorUsage(0, &input, &usage));
        Check(input == 0 && usage == MFSampleAllocatorUsage_UsesCustomAllocator);
        Check(allocation->GetAllocatorUsage(1, &input, &usage) == MF_E_INVALIDSTREAMNUMBER);
        ComPtr<IMFAttributes> attributes; Ok(f.source->GetSourceAttributes(&attributes));
        UINT32 type = 0; Ok(attributes->GetUINT32(MF_DEVICESTREAM_ATTRIBUTE_FRAMESOURCE_TYPES, &type)); Check(type == MFFrameSourceTypes_Color);
        attributes.Reset(); Ok(f.source->GetStreamAttributes(0, &attributes));
        Ok(attributes->GetUINT32(MF_DEVICESTREAM_STREAM_ID, &type)); Check(type == 0);
        attributes.Reset(); Check(f.source->GetStreamAttributes(1, &attributes) == MF_E_INVALIDSTREAMNUMBER && !attributes);
        Check(f.owner.sendChecks == 0);
        ComPtr<IMFPresentationDescriptor> pd; Ok(f.source->CreatePresentationDescriptor(&pd));
        DWORD count = 0; Ok(pd->GetStreamDescriptorCount(&count)); Check(count == 1);
        Check(f.source->QueueEvent(MEMediaSample, GUID_NULL, S_OK, nullptr) == E_NOTIMPL);
    }

    void EventTokenAndExactSample()
    {
        Fixture f; f.Start(); ComPtr<IMFAttributes> token; Ok(MFCreateAttributes(&token, 1));
        Ok(f.stream->RequestSample(token.Get())); f.Publish(0, 1234567);
        auto sample = f.Sample(); LONGLONG pts = 0; Ok(sample->GetSampleTime(&pts)); Check(pts == 12345670);
        ComPtr<IUnknown> returned; Ok(sample->GetUnknown(MFSampleExtension_Token, IID_PPV_ARGS(&returned)));
        ComPtr<IUnknown> expected; Ok(token.As(&expected)); Check(returned.Get() == expected.Get());
        ComPtr<IMFMediaBuffer> buffer; Ok(sample->ConvertToContiguousBuffer(&buffer));
        BYTE* bytes = nullptr; DWORD length = 0; Ok(buffer->Lock(&bytes, nullptr, &length));
        Check(length == Samples::VideoBytes);
        for (DWORD i = 0; i < length; ++i) Check(bytes[i] == (i < 640 * 480 ? 60 : 128));
        Ok(buffer->Unlock()); Check(f.owner.retired == 0);
        ComPtr<IMFMediaSource> parent; Ok(f.stream->GetMediaSource(&parent));
        ComPtr<IUnknown> a, b; Ok(parent.As(&a)); Ok(f.source.As(&b)); Check(a.Get() == b.Get());
    }

    void LatestWholeFrameAndNoReuse()
    {
        Fixture f; f.Start(); f.Publish(0, 0, 60); f.Publish(1, 66667, 180);
        Ok(f.stream->RequestSample(nullptr)); auto sample = f.Sample();
        LONGLONG pts = 0; Ok(sample->GetSampleTime(&pts)); Check(pts == 666670);
        ComPtr<IMFMediaBuffer> buffer; Ok(sample->GetBufferByIndex(0, &buffer));
        BYTE* bytes = nullptr; Ok(buffer->Lock(&bytes, nullptr, nullptr)); Check(bytes[0] == 180); Ok(buffer->Unlock());
        Ok(f.stream->RequestSample(nullptr)); ComPtr<IMFMediaEvent> none;
        Check(f.stream->GetEvent(MF_EVENT_FLAG_NO_WAIT, &none) == MF_E_NO_EVENTS_AVAILABLE && !none);
    }

    void BoundedRequests()
    {
        Fixture f; f.Start();
        for (int i = 0; i < 16; ++i) Ok(f.stream->RequestSample(nullptr));
        Check(FAILED(f.stream->RequestSample(nullptr)));
        Check(f.owner.retired == 1 && f.owner.reason == MF_E_NOTACCEPTING);
        Check(f.stream->RequestSample(nullptr) == MF_E_SHUTDOWN);
    }

    void OriginalOwnerRevocation()
    {
        Fixture f; f.Start(); f.Publish(0);
        f.owner.current = false; Check(FAILED(f.stream->RequestSample(nullptr)));
        Check(f.owner.retired == 1); f.owner.current = true;
        ComPtr<IMFPresentationDescriptor> pd; Check(f.source->CreatePresentationDescriptor(&pd) == MF_E_SHUTDOWN && !pd);
        Check(f.stream->RequestSample(nullptr) == MF_E_SHUTDOWN);
        f.source->Shutdown(); Check(f.owner.retired == 1);
    }

    void UnreadSampleBacklogBound()
    {
        Fixture f; f.Start();
        for (int i = 0; i < 16; ++i) { Ok(f.stream->RequestSample(nullptr)); f.Publish(i, i * 1000LL); }
        Check(FAILED(f.stream->RequestSample(nullptr)) && f.owner.retired == 1 && f.owner.reason == MF_E_NOTACCEPTING);
    }

    void OldQueuedSampleIsNotFreshenedByNewFrames()
    {
        Fixture f; f.Start(); Ok(f.stream->RequestSample(nullptr)); f.Publish(0);
        for (int i = 1; i <= 6; ++i)
        { std::this_thread::sleep_for(std::chrono::milliseconds(60)); f.Publish(i, i * 66667LL); }
        ComPtr<IMFMediaEvent> event;
        Check(FAILED(f.stream->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event)) && !event);
        Check(f.owner.retired == 1 && f.owner.reason == MF_E_NET_TIMEOUT);
    }

    void ActualSendRequiredAtPublicationAndReadback()
    {
        {
            Fixture f; f.Start(); f.owner.sending = false;
            std::vector<BYTE> data(Samples::VideoBytes);
            Check(FAILED(f.feed->PublishVideo(data.data(), static_cast<DWORD>(data.size()), 0, 0)));
            Check(f.owner.retired == 1); f.owner.sending = true;
            Check(f.feed->PublishVideo(data.data(), static_cast<DWORD>(data.size()), 0, 0) == MF_E_SHUTDOWN);
        }
        {
            Fixture f; f.Start(); Ok(f.stream->RequestSample(nullptr)); f.Publish(0);
            f.owner.sending = false; ComPtr<IMFMediaEvent> event;
            Check(FAILED(f.stream->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event)) && !event && f.owner.retired == 1);
        }
    }

    void ForeignDescriptorsAndStartPositions()
    {
        Fixture a, b; ComPtr<IMFPresentationDescriptor> pd; Ok(b.source->CreatePresentationDescriptor(&pd));
        PROPVARIANT zero{}; zero.vt = VT_EMPTY;
        Check(a.source->Start(pd.Get(), nullptr, &zero) == E_INVALIDARG);
        pd.Reset(); Ok(a.source->CreatePresentationDescriptor(&pd)); Ok(pd->DeselectStream(0));
        Check(a.source->Start(pd.Get(), nullptr, &zero) == E_INVALIDARG); Ok(pd->SelectStream(0));
        zero.vt = VT_I8; zero.hVal.QuadPart = 1;
        Check(a.source->Start(pd.Get(), nullptr, &zero) == MF_E_INVALIDREQUEST);
        zero.hVal.QuadPart = 0; GUID foreign{}; Ok(CoCreateGuid(&foreign));
        Check(a.source->Start(pd.Get(), &foreign, &zero) == MF_E_UNSUPPORTED_TIME_FORMAT);
        Check(a.owner.retired == 0); a.Start();
    }

    void StopRestartAndStreamState()
    {
        Fixture f; f.Start(); Ok(f.stream->RequestSample(nullptr)); f.Publish(0);
        Ok(f.source->Stop()); MF_STREAM_STATE state{}; Ok(f.stream->GetStreamState(&state)); Check(state == MF_STREAM_STATE_STOPPED);
        Check(f.stream->RequestSample(nullptr) == MF_E_INVALIDREQUEST);
        Check(f.stream->SetStreamState(MF_STREAM_STATE_RUNNING) == MF_E_INVALID_STATE_TRANSITION);
        // Discarding Stop notifications is deliberate before the next Start.
        ComPtr<IMFMediaEvent> event;
        while (SUCCEEDED(f.stream->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event))) event.Reset();
        Ok(f.source->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event)); event.Reset();
        f.Start(); Ok(f.stream->SetStreamState(MF_STREAM_STATE_PAUSED));
        Check(f.stream->RequestSample(nullptr) == MF_E_INVALIDREQUEST);
        Ok(f.stream->SetStreamState(MF_STREAM_STATE_RUNNING));
        Ok(f.stream->RequestSample(nullptr)); f.Publish(1, 66667); auto sample = f.Sample();
        LONGLONG pts = 0; Ok(sample->GetSampleTime(&pts)); Check(pts == 666670);
        Check(f.owner.retired == 0);
    }

    void IdleRevocationAndStallWatchdog()
    {
        {
            Fixture f; f.owner.current = false;
            Check(WaitForSingleObject(f.owner.event, 1500) == WAIT_OBJECT_0 && f.owner.retired == 1);
        }
        {
            Fixture f; f.Start(); f.Publish(0);
            Check(WaitForSingleObject(f.owner.event, 1500) == WAIT_OBJECT_0);
            Check(f.owner.retired == 1 && f.owner.reason == MF_E_NET_TIMEOUT);
        }
    }

    void ShutdownAndNullContracts()
    {
        Owner owner; ComPtr<IMFMediaSourceEx> source; ComPtr<IFrameFeed> feed;
        auto invalid = owner.Callbacks(); invalid.sending = nullptr;
        Check(CreateSource(invalid, &source, &feed) == E_INVALIDARG && !source && !feed);
        Check(CreateSource(owner.Callbacks(), nullptr, &feed) == E_POINTER);
        Fixture f; f.Start(); Ok(f.source->Shutdown()); Check(f.owner.retired == 1);
        Check(f.source->Shutdown() == MF_E_SHUTDOWN && f.owner.retired == 1);
        ComPtr<IMFMediaSource> parent; Check(f.stream->GetMediaSource(&parent) == MF_E_SHUTDOWN && !parent);
        ComPtr<IMFMediaEvent> event; Check(f.stream->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event) == MF_E_SHUTDOWN);
        Check(f.source->GetCharacteristics(nullptr) == E_POINTER);
        Check(f.stream->GetStreamState(nullptr) == E_POINTER);
        Check(f.stream->EndGetEvent(nullptr, &event) == E_POINTER && !event);
    }

    void ShutdownUnblocksActualEventWait()
    {
        Fixture f; f.Start(); HANDLE entered = CreateEventW(nullptr, TRUE, FALSE, nullptr); Check(entered != nullptr);
        std::atomic<HRESULT> result{E_FAIL};
        std::thread waiting([&] {
            SetEvent(entered); ComPtr<IMFMediaEvent> event;
            result = f.stream->GetEvent(0, &event);
        });
        const DWORD started = WaitForSingleObject(entered, 1000);
        const HRESULT shutdown = f.source->Shutdown(); waiting.join(); CloseHandle(entered);
        Check(started == WAIT_OBJECT_0 && SUCCEEDED(shutdown) && result == MF_E_SHUTDOWN && f.owner.retired == 1);
    }

    void StartupWithoutFramesExpires()
    {
        Fixture f; f.Start(); Ok(f.stream->RequestSample(nullptr));
        Check(WaitForSingleObject(f.owner.event, 6500) == WAIT_OBJECT_0);
        Check(f.owner.retired == 1 && f.owner.reason == MF_E_NET_TIMEOUT);
    }

    class Lifetime final : public Microsoft::WRL::RuntimeClass<Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, IUnknown>
    {
    public:
        Lifetime(HANDLE ended, std::atomic_int* deaths) : ended_(ended), deaths_(deaths) {}
        ~Lifetime() { ++*deaths_; SetEvent(ended_); }
    private:
        HANDLE ended_;
        std::atomic_int* deaths_;
    };

    void NativeLifetimeOutlivesSourceAndShutdown()
    {
        struct Event { HANDLE value = CreateEventW(nullptr, TRUE, FALSE, nullptr); ~Event() { if (value) CloseHandle(value); } } ended;
        Check(ended.value != nullptr); std::atomic_int deaths{0};
        auto lifetime = Microsoft::WRL::Make<Lifetime>(ended.value, &deaths); Check(lifetime != nullptr);
        Fixture f(lifetime.Get()); lifetime.Reset(); f.Start(); Check(deaths == 0);
        Ok(f.source->Shutdown()); f.feed.Reset(); f.source.Reset();
        // The capture client's old stream still executes our native code, even
        // though its source was shut down and the controller dropped its refs.
        Check(deaths == 0);
        f.stream.Reset(); Check(WaitForSingleObject(ended.value, 1500) == WAIT_OBJECT_0 && deaths == 1);
    }

    void ActualSourceReaderClient()
    {
        Fixture f; ComPtr<IMFAttributes> attrs; Ok(MFCreateAttributes(&attrs, 2));
        Ok(attrs->SetUINT32(MF_READWRITE_DISABLE_CONVERTERS, TRUE));
        ComPtr<IMFSourceReader> reader;
        HRESULT created = MFCreateSourceReaderFromMediaSource(f.source.Get(), attrs.Get(), &reader);
        if (FAILED(created)) std::printf("STAGE source-reader-create\n");
        Ok(created);
        ComPtr<IMFMediaType> type; Ok(Samples::VideoType(&type));
        HRESULT selected = reader->SetCurrentMediaType(static_cast<DWORD>(MF_SOURCE_READER_FIRST_VIDEO_STREAM), nullptr, type.Get());
        if (FAILED(selected)) std::printf("STAGE source-reader-select-type\n");
        Ok(selected);
        std::atomic_bool finished{false}; std::atomic<HRESULT> producerResult{S_OK};
        std::thread producer([&] {
            std::vector<BYTE> data(Samples::VideoBytes, 128); std::fill(data.begin(), data.begin() + 640 * 480, static_cast<BYTE>(90));
            for (int i = 0; i < 30 && !finished; ++i)
            {
                HRESULT hr = f.feed->PublishVideo(data.data(), static_cast<DWORD>(data.size()), i, i * 66667LL);
                if (FAILED(hr)) { producerResult = hr; break; }
                std::this_thread::sleep_for(std::chrono::milliseconds(67));
            }
        });
        // ReadSample is bounded by the source's actual startup/stall watchdog.
        // Its Shutdown wakes a native reader even if the generated producer fails.
        bool valid = true;
        LONGLONG previous = -1;
        for (int i = 0; i < 3; ++i)
        {
            DWORD stream = 99, flags = 0; LONGLONG pts = -1; ComPtr<IMFSample> sample;
            HRESULT hr = reader->ReadSample(static_cast<DWORD>(MF_SOURCE_READER_FIRST_VIDEO_STREAM), 0, &stream, &flags, &pts, &sample);
            if (FAILED(hr) || !sample || stream != 0 || pts <= previous ||
                (flags & (MF_SOURCE_READERF_ERROR | MF_SOURCE_READERF_ENDOFSTREAM | MF_SOURCE_READERF_STREAMTICK)))
            { valid = false; break; }
            previous = pts;
            LONGLONG samplePts = -1; hr = sample->GetSampleTime(&samplePts);
            if (FAILED(hr) || samplePts != pts) { valid = false; break; }
            ComPtr<IMFMediaBuffer> buffer; hr = sample->ConvertToContiguousBuffer(&buffer);
            if (FAILED(hr)) { valid = false; break; }
            DWORD size = 0; hr = buffer->GetCurrentLength(&size);
            if (FAILED(hr) || size != Samples::VideoBytes) { valid = false; break; }
            BYTE* data = nullptr; hr = buffer->Lock(&data, nullptr, nullptr);
            if (FAILED(hr)) { valid = false; break; }
            for (DWORD at = 0; at < size; ++at)
                if (data[at] != (at < 640 * 480 ? 90 : 128)) { valid = false; break; }
            buffer->Unlock(); if (!valid) break;
        }
        finished = true; producer.join(); reader.Reset();
        Check(valid && SUCCEEDED(producerResult));
    }
}

int main(int argc, char** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET))) { CoUninitialize(); return 3; }
    int failed = 0;
    const struct { const char* name; void (*run)(); } cases[] = {
        {"source-interfaces-metadata", InterfacesAndMetadata}, {"source-events-token-sample", EventTokenAndExactSample},
        {"source-latest-whole-frame", LatestWholeFrameAndNoReuse}, {"source-bounded-requests", BoundedRequests},
        {"source-unread-sample-backlog", UnreadSampleBacklogBound}, {"source-old-queued-sample", OldQueuedSampleIsNotFreshenedByNewFrames},
        {"source-original-owner-revoked", OriginalOwnerRevocation}, {"source-actual-send-required", ActualSendRequiredAtPublicationAndReadback},
        {"source-original-descriptor", ForeignDescriptorsAndStartPositions}, {"source-stop-restart-state", StopRestartAndStreamState},
        {"source-idle-revocation-stall", IdleRevocationAndStallWatchdog}, {"source-shutdown-null-contract", ShutdownAndNullContracts},
        {"source-shutdown-unblocks-event-wait", ShutdownUnblocksActualEventWait}, {"source-no-frame-startup-timeout", StartupWithoutFramesExpires},
        {"source-native-context-lifetime", NativeLifetimeOutlivesSourceAndShutdown},
        {"source-real-mf-source-reader", ActualSourceReaderClient}
    };
    for (const auto& test : cases)
    {
        if (argc == 2 && std::strcmp(argv[1], test.name) != 0) continue;
        try { test.run(); std::printf("PASS %s\n", test.name); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
        std::fflush(stdout);
    }
    MFShutdown(); CoUninitialize(); return failed ? 1 : 0;
}
