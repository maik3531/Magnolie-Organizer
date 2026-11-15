#include "../../native/phone-camera/PhoneCameraActivate.h"
#include "../../native/phone-camera/PhoneCameraAudioRender.h"
#include "../../native/phone-camera/PhoneCameraPipe.h"
#include <mfapi.h>
#include <mferror.h>
#include <wrl/client.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>

using namespace Magnolie::PhoneCamera;
using Microsoft::WRL::ComPtr;

namespace Magnolie::PhoneCamera
{
    struct AudioRenderTestAccess
    {
        static std::unique_ptr<AudioRender> Create(ClockOwner owner)
        { return std::unique_ptr<AudioRender>(new AudioRender(owner)); }
        static HRESULT CheckOwner(AudioRender& render, bool sending) noexcept { return render.Check(sending); }
    };
}

namespace
{
    void Check(bool value) { if (!value) throw std::runtime_error("unconfirmed authority accepted"); }
    struct Owner
    {
        std::atomic<HRESULT> current{S_OK}, sending{S_OK}, reason{S_OK};
        std::atomic_int retired{0}, constructed{0};
        static HRESULT Current(void* value) noexcept { return static_cast<Owner*>(value)->current.load(); }
        static HRESULT Sending(void* value) noexcept { return static_cast<Owner*>(value)->sending.load(); }
        static void Retired(void* value, HRESULT reason) noexcept
        { auto& owner = *static_cast<Owner*>(value); if (owner.retired.fetch_add(1) == 0) owner.reason = reason; }
        static HRESULT Construct(void* value, IMFAttributes*, IMFMediaSourceEx** result) noexcept
        {
            auto& owner = *static_cast<Owner*>(value); ++owner.constructed;
            ComPtr<IFrameFeed> feed;
            return CreateSource(owner.SourceCallbacks(), result, &feed);
        }
        ClockOwner ClockCallbacks() { return {Current, Sending, Retired, this}; }
        SourceOwner SourceCallbacks() { return {Current, Sending, Retired, this}; }
    };

    void SamplesRequireConfirmedCurrent()
    {
        for (HRESULT status : {S_FALSE, HRESULT(2), E_ABORT})
        {
            Owner owner; owner.current = status;
            Samples samples(Owner::Current, &owner, false);
            std::vector<BYTE> bytes(Samples::VideoBytes);
            ComPtr<IMFSample> sample;
            Check(samples.Video(bytes.data(), bytes.size(), 0, 0, &sample) == (FAILED(status) ? status : E_ACCESSDENIED));
            Check(!sample && samples.IsRetired()); owner.current = S_OK;
            Check(samples.Video(bytes.data(), bytes.size(), 0, 0, &sample) == MF_E_SHUTDOWN && !sample);
        }
    }
    void ClockRequiresConfirmedCurrentAndSend()
    {
        for (bool sending : {false, true}) for (HRESULT status : {S_FALSE, HRESULT(2), E_ABORT})
        {
            Owner owner; (sending ? owner.sending : owner.current) = status;
            PresentationClock clock(owner.ClockCallbacks()); LONGLONG mapped = 99;
            Check(clock.Map(0, &mapped) == (FAILED(status) ? status : E_ACCESSDENIED));
            Check(mapped == 0 && owner.retired == 1 && owner.reason == (FAILED(status) ? status : E_ACCESSDENIED));
            owner.current = S_OK; owner.sending = S_OK;
            Check(clock.Map(0, &mapped) == MF_E_SHUTDOWN && mapped == 0 && owner.retired == 1);
        }
    }
    void SourceCreationNeedsConfirmedCurrent()
    {
        Owner owner; owner.current = S_FALSE;
        ComPtr<IMFMediaSourceEx> source; ComPtr<IFrameFeed> feed;
        HRESULT hr = CreateSource(owner.SourceCallbacks(), &source, &feed);
        if (source) source->Shutdown();
        Check(hr == E_ACCESSDENIED && !source && !feed && owner.retired == 1);
    }
    void PreparedSourceDoesNotGrantSend()
    {
        Owner owner; owner.sending = S_FALSE;
        ComPtr<IMFMediaSourceEx> source; ComPtr<IFrameFeed> feed;
        Check(CreateSource(owner.SourceCallbacks(), &source, &feed) == S_OK);
        std::vector<BYTE> bytes(Samples::VideoBytes);
        HRESULT hr = feed->PublishVideo(bytes.data(), static_cast<DWORD>(bytes.size()), 0, 0);
        source->Shutdown();
        Check(FAILED(hr) && owner.retired == 1 && owner.reason == E_ACCESSDENIED);
        owner.sending = S_OK;
        Check(feed->PublishVideo(bytes.data(), static_cast<DWORD>(bytes.size()), 0, 0) == MF_E_SHUTDOWN);
    }
    void SourceRechecksCurrentWithoutRevival()
    {
        Owner owner; ComPtr<IMFMediaSourceEx> source; ComPtr<IFrameFeed> feed;
        Check(CreateSource(owner.SourceCallbacks(), &source, &feed) == S_OK);
        owner.current = S_FALSE; DWORD flags = 99;
        HRESULT hr = source->GetCharacteristics(&flags); source->Shutdown();
        Check(FAILED(hr) && flags == 0 && owner.retired == 1 && owner.reason == E_ACCESSDENIED);
        owner.current = S_OK; Check(source->GetCharacteristics(&flags) == MF_E_SHUTDOWN && flags == 0);
    }
    void ActivationDoesNotConstructOnUnconfirmedCurrent()
    {
        Owner owner; owner.current = S_FALSE;
        ComPtr<IMFActivate> activation;
        Check(CreateActivate({Owner::Current, Owner::Construct, &owner}, &activation) == S_OK);
        ComPtr<IMFMediaSourceEx> source;
        HRESULT hr = activation->ActivateObject(IID_PPV_ARGS(&source));
        if (source) source->Shutdown();
        Check(hr == E_ACCESSDENIED && !source && owner.constructed == 0);
        owner.current = S_OK;
        Check(activation->ActivateObject(IID_PPV_ARGS(&source)) == MF_E_SHUTDOWN && !source);
    }
    void PipeRefusesBeforeOpeningAnyEndpoint()
    {
        Owner owner; owner.current = S_FALSE;
        GUID scope{}; Check(CoCreateGuid(&scope) == S_OK);
        std::unique_ptr<PipeReader> reader;
        HANDLE original = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, GetCurrentProcessId());
        Check(original != nullptr);
        const HRESULT hr = PipeReader::Connect(scope, original, Owner::Current, &owner, reader);
        CloseHandle(original);
        Check(hr == E_ACCESSDENIED && !reader);
    }
    void RenderChecksWithoutAnyAudioClient()
    {
        for (bool sending : {false, true})
        {
            Owner owner; (sending ? owner.sending : owner.current) = S_FALSE;
            auto render = AudioRenderTestAccess::Create(owner.ClockCallbacks());
            Check(AudioRenderTestAccess::CheckOwner(*render, sending) == E_ACCESSDENIED);
            Check(render->IsRetired() && owner.retired == 1 && owner.reason == E_ACCESSDENIED);
            owner.current = S_OK; owner.sending = S_OK;
            Check(AudioRenderTestAccess::CheckOwner(*render, true) == MF_E_SHUTDOWN && owner.retired == 1);
        }
    }
}

int main(int argc, char** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET))) { CoUninitialize(); return 3; }
    const struct { const char* name; void (*run)(); } cases[] = {
        {"authority-samples-exact-current", SamplesRequireConfirmedCurrent},
        {"authority-clock-exact-current-send", ClockRequiresConfirmedCurrentAndSend},
        {"authority-source-create", SourceCreationNeedsConfirmedCurrent},
        {"authority-source-prepare-not-send", PreparedSourceDoesNotGrantSend},
        {"authority-source-recheck", SourceRechecksCurrentWithoutRevival},
        {"authority-activation-no-construction", ActivationDoesNotConstructOnUnconfirmedCurrent},
        {"authority-pipe-before-open", PipeRefusesBeforeOpeningAnyEndpoint},
        {"authority-render-no-device", RenderChecksWithoutAnyAudioClient}
    };
    int failed = 0, selected = 0;
    for (const auto& test : cases)
    {
        if (argc > 1 && std::strcmp(argv[1], test.name)) continue;
        ++selected;
        try { test.run(); std::printf("PASS %s\n", test.name); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
        std::fflush(stdout);
    }
    MFShutdown(); CoUninitialize(); return !selected ? 4 : failed ? 1 : 0;
}
