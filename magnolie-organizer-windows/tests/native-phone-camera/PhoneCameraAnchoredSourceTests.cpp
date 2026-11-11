// Reuse the existing actual MF event/sample fixture and ONE affected legacy
// sample regression. Its other test functions are not executed by this entry.
#define main ExistingUnregisteredSourceTestEntry
#include "PhoneCameraSourceTests.cpp"
#undef main
#include <array>
#include <string>

namespace
{
    std::array<BYTE, PresentationClock::AnchorBytes> ParentAnchor(const GUID& scope)
    {
        Owner parent; PresentationClock clock(parent.ClockCallbacks()); LONGLONG mapped = 0;
        Ok(clock.Map(1000, &mapped)); Check(mapped == 5000000);
        std::array<BYTE, PresentationClock::AnchorBytes> record{}; Ok(clock.ExportAnchor(scope, record.data(), record.size())); return record;
    }
    void ImportedParentEpochInActualSample()
    {
        Fixture f(nullptr, true); auto record = ParentAnchor(f.scope);
        f.owner.nativeNow = 5030000; Ok(f.clock->ImportAnchor(f.scope, record.data(), record.size()));
        f.Start(); ComPtr<IMFAttributes> token; Ok(MFCreateAttributes(&token, 1)); Ok(f.stream->RequestSample(token.Get()));
        f.Publish(0, 11000); auto sample = f.Sample(); LONGLONG time = 0; Ok(sample->GetSampleTime(&time)); Check(time == 50100000);
        ComPtr<IUnknown> actual, expected; Ok(sample->GetUnknown(MFSampleExtension_Token, IID_PPV_ARGS(&actual))); Ok(token.As(&expected)); Check(actual.Get() == expected.Get());
        ComPtr<IMFMediaBuffer> buffer; Ok(sample->GetBufferByIndex(0, &buffer)); BYTE* bytes = nullptr; DWORD size = 0;
        Ok(buffer->Lock(&bytes, nullptr, &size)); Check(size == Samples::VideoBytes && bytes[0] == 60 && bytes[640 * 480] == 128); Ok(buffer->Unlock());
        Ok(f.stream->RequestSample(nullptr)); f.Publish(1, 31000); sample = f.Sample(); Ok(sample->GetSampleTime(&time)); Check(time == 50300000);
    }
    void MissingOrTrackLocalAnchorRefused()
    {
        for (bool local : {false, true})
        {
            Fixture f(nullptr, true); f.Start(); Ok(f.stream->RequestSample(nullptr));
            if (local) { LONGLONG invented = 0; Ok(f.clock->Map(0, &invented)); }
            std::vector<BYTE> data(Samples::VideoBytes, 42);
            Check(FAILED(f.feed->PublishVideo(data.data(), static_cast<DWORD>(data.size()), 0, 0)));
            ComPtr<IMFMediaEvent> event; Check(f.stream->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event) == MF_E_SHUTDOWN && !event);
        }
    }
    void ForeignScopeAndOwnerRefused()
    {
        Fixture f(nullptr, true); GUID other{}; Ok(CoCreateGuid(&other)); auto record = ParentAnchor(other);
        Ok(f.clock->ImportAnchor(other, record.data(), record.size())); f.Start();
        std::vector<BYTE> data(Samples::VideoBytes, 42); Check(FAILED(f.feed->PublishVideo(data.data(), static_cast<DWORD>(data.size()), 0, 1000)));
        Owner original, foreign; auto clock = std::make_shared<PresentationClock>(foreign.ClockCallbacks());
        ComPtr<IMFMediaSourceEx> source; ComPtr<IFrameFeed> feed;
        Check(CreateAnchoredSource(original.Callbacks(), other, clock, &source, &feed) == E_ACCESSDENIED && !source && !feed);
        Check(CreateAnchoredSource(original.Callbacks(), GUID_NULL, clock, &source, &feed) == E_ACCESSDENIED && !source && !feed);
    }
    void PrepareBeforeSendAndActualWithdrawal()
    {
        Fixture f(nullptr, true); Check(f.owner.sendChecks == 0); f.owner.sending = false;
        ComPtr<IMFPresentationDescriptor> pd; Ok(f.source->CreatePresentationDescriptor(&pd)); Check(f.owner.sendChecks == 0);
        f.owner.sending = true; auto record = ParentAnchor(f.scope); Ok(f.clock->ImportAnchor(f.scope, record.data(), record.size()));
        f.Start(); Ok(f.stream->RequestSample(nullptr)); f.owner.sending = false;
        std::vector<BYTE> data(Samples::VideoBytes, 42); Check(FAILED(f.feed->PublishVideo(data.data(), static_cast<DWORD>(data.size()), 0, 1000)));
        f.owner.sending = true; Check(f.source->CreatePresentationDescriptor(&pd) == MF_E_SHUTDOWN);
    }
    void RetiredClockCannotReleaseQueuedSample()
    {
        Fixture f(nullptr, true); auto record = ParentAnchor(f.scope); Ok(f.clock->ImportAnchor(f.scope, record.data(), record.size()));
        f.Start(); Ok(f.stream->RequestSample(nullptr)); f.Publish(0, 1000); f.clock->Stop();
        ComPtr<IMFMediaEvent> event; Check(FAILED(f.stream->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event)) && !event);
    }
    void ShutdownRetiresClockBeforeContextRelease()
    {
        Fixture f(nullptr, true); auto record = ParentAnchor(f.scope); Ok(f.clock->ImportAnchor(f.scope, record.data(), record.size()));
        f.Start(); Ok(f.source->Shutdown()); const int retired = f.owner.retired;
        Check(retired > 0); f.source.Reset(); f.feed.Reset(); f.stream.Reset(); f.clock.reset(); Check(f.owner.retired == retired);
    }
    void SourceFailureRetiresOriginalExactlyOnce()
    {
        Fixture f(nullptr, true); auto record = ParentAnchor(f.scope); Ok(f.clock->ImportAnchor(f.scope, record.data(), record.size()));
        std::vector<BYTE> data(Samples::VideoBytes, 42);
        Check(f.feed->PublishVideo(data.data(), static_cast<DWORD>(data.size() - 1), 0, 1000) == E_INVALIDARG);
        if (f.owner.retired != 1 || f.owner.firstReason != E_INVALIDARG)
            std::printf("RETIRE count=%d first=%08lx expected=%08lx\n", f.owner.retired.load(), static_cast<unsigned long>(f.owner.firstReason.load()), static_cast<unsigned long>(E_INVALIDARG));
        Check(f.owner.retired == 1 && f.owner.firstReason == E_INVALIDARG);
    }
}
int main(int argc, char** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET))) { CoUninitialize(); return 3; }
    const struct { const char* name; void (*run)(); } tests[] = {
        {"anchored-source-parent-epoch-sample", ImportedParentEpochInActualSample},
        {"anchored-source-no-receipt-origin", MissingOrTrackLocalAnchorRefused},
        {"anchored-source-original-scope-owner", ForeignScopeAndOwnerRefused},
        {"anchored-source-prepare-send-withdrawal", PrepareBeforeSendAndActualWithdrawal},
        {"anchored-source-queued-clock-loss", RetiredClockCannotReleaseQueuedSample},
        {"anchored-source-shutdown-clock-lifetime", ShutdownRetiresClockBeforeContextRelease},
        {"anchored-source-original-failure-once", SourceFailureRetiresOriginalExactlyOnce},
        {"source-events-token-sample-regression", EventTokenAndExactSample}
    };
    int failed = 0;
    const auto selected = argc == 2 ? std::string(",") + argv[1] + "," : std::string();
    for (const auto& test : tests) { if (!selected.empty() && selected.find(std::string(",") + test.name + ",") == std::string::npos) continue; try { test.run(); std::printf("PASS %s\n", test.name); } catch (...) { ++failed; std::printf("FAIL %s\n", test.name); } std::fflush(stdout); }
    MFShutdown(); CoUninitialize(); return failed ? 1 : 0;
}
