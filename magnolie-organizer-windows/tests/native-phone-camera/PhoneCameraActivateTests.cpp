#include "../../native/phone-camera/PhoneCameraActivate.h"
#include <mfapi.h>
#include <mferror.h>
#include <wrl.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <stdexcept>

using namespace Magnolie::PhoneCamera;
using Microsoft::WRL::ComPtr;

namespace
{
    const GUID Config = {0xa2b59dfa, 0x90c0, 0x4880, {0x9a, 0x90, 0xe3, 0x26, 0xa0, 0x28, 0xe6, 0xba}};
    void Check(bool condition) { if (!condition) throw std::runtime_error("activate assertion"); }
    void Ok(HRESULT hr) { if (FAILED(hr)) { std::printf("HRESULT %08lx\n", static_cast<unsigned long>(hr)); Check(false); } }
    class Root final : public Microsoft::WRL::RuntimeClass<Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, IUnknown>
    {
    public:
        std::atomic_bool current{true}, stopped{false}, sending{true}, loseAfterConstruct{false};
        std::atomic_int constructed{0}, retired{0};
        std::atomic<UINT32> observed{0};
        HRESULT constructStatus = S_OK;
        HANDLE died = nullptr;
        std::atomic_int* deaths = nullptr;
        ~Root() { if (deaths) ++*deaths; if (died) SetEvent(died); }
        static HRESULT Current(void* context) noexcept
        { auto& root = *static_cast<Root*>(context); return root.current && !root.stopped ? S_OK : E_ACCESSDENIED; }
        static HRESULT Sending(void* context) noexcept
        { auto& root = *static_cast<Root*>(context); return root.sending ? Current(context) : E_ACCESSDENIED; }
        static void Retired(void* context, HRESULT) noexcept
        { auto& root = *static_cast<Root*>(context); ++root.retired; root.stopped = true; }
        static HRESULT Construct(void* context, IMFAttributes* snapshot, IMFMediaSourceEx** result) noexcept
        {
            auto& root = *static_cast<Root*>(context); ++root.constructed; *result = nullptr;
            if (FAILED(root.constructStatus)) return root.constructStatus;
            UINT32 config = 0; snapshot->GetUINT32(Config, &config); root.observed = config;
            ComPtr<IFrameFeed> feed;
            const HRESULT hr = CreateSource({Current, Sending, Retired, &root, &root}, result, &feed);
            if (root.loseAfterConstruct) root.current = false;
            return hr;
        }
        ActivateOwner Owner() { return {Current, Construct, this, this}; }
    };
    struct Fixture
    {
        ComPtr<Root> root = Microsoft::WRL::Make<Root>();
        ComPtr<IMFActivate> activate;
        Fixture() { Check(root != nullptr); Ok(CreateActivate(root->Owner(), &activate)); }
        ~Fixture() { if (activate) activate->ShutdownObject(); }
    };

    void MetadataSnapshotAndOriginalSource()
    {
        Fixture f; Ok(f.activate->SetUINT32(Config, 42));
        ComPtr<IMFAttributes> metadata; Ok(f.activate.As(&metadata)); UINT32 config = 0;
        Ok(metadata->GetUINT32(Config, &config)); Check(config == 42 && f.root->constructed == 0);
        ComPtr<IMFMediaSourceEx> first; Ok(f.activate->ActivateObject(IID_PPV_ARGS(&first)));
        Check(f.root->constructed == 1 && f.root->observed == 42);
        Ok(f.activate->SetUINT32(Config, 7));
        ComPtr<IMFMediaSource> second; Ok(f.activate->ActivateObject(IID_PPV_ARGS(&second)));
        ComPtr<IUnknown> a, b; Ok(first.As(&a)); Ok(second.As(&b));
        Check(a.Get() == b.Get() && f.root->constructed == 1 && f.root->observed == 42);
    }

    void MetadataCannotGrantAuthority()
    {
        Fixture f; f.root->current = false; Ok(f.activate->SetUINT32(Config, TRUE));
        ComPtr<IMFMediaSource> source; Check(FAILED(f.activate->ActivateObject(IID_PPV_ARGS(&source))) && !source);
        Check(f.root->constructed == 0); f.root->current = true;
        Check(f.activate->ActivateObject(IID_PPV_ARGS(&source)) == MF_E_SHUTDOWN && !source && f.root->constructed == 0);
    }

    void FailedConstructionDoesNotRetry()
    {
        Fixture f; f.root->constructStatus = E_ACCESSDENIED;
        ComPtr<IMFMediaSource> source; Check(FAILED(f.activate->ActivateObject(IID_PPV_ARGS(&source))) && !source);
        f.root->constructStatus = S_OK;
        Check(f.activate->ActivateObject(IID_PPV_ARGS(&source)) == MF_E_SHUTDOWN && !source && f.root->constructed == 1);
    }

    void LostOriginalContextDuringConstruction()
    {
        Fixture f; f.root->loseAfterConstruct = true;
        ComPtr<IMFMediaSource> source; Check(FAILED(f.activate->ActivateObject(IID_PPV_ARGS(&source))) && !source);
        Check(f.root->constructed == 1 && f.root->retired == 1);
        f.root->current = true; f.root->stopped = false; f.root->loseAfterConstruct = false;
        Check(f.activate->ActivateObject(IID_PPV_ARGS(&source)) == MF_E_SHUTDOWN && !source);
    }

    void OriginalContextRevokedAfterActivation()
    {
        Fixture f; ComPtr<IMFMediaSourceEx> source; Ok(f.activate->ActivateObject(IID_PPV_ARGS(&source)));
        f.root->current = false; ComPtr<IMFMediaSource> old;
        Check(FAILED(f.activate->ActivateObject(IID_PPV_ARGS(&old))) && !old && f.root->retired == 1);
        DWORD flags = 0; Check(source->GetCharacteristics(&flags) == MF_E_SHUTDOWN);
        f.root->current = true; Check(f.activate->ActivateObject(IID_PPV_ARGS(&old)) == MF_E_SHUTDOWN);
    }

    void ShutdownRetiresOnlyOriginalSource()
    {
        Fixture f; ComPtr<IMFMediaSourceEx> source; Ok(f.activate->ActivateObject(IID_PPV_ARGS(&source)));
        Ok(f.activate->ShutdownObject()); Check(f.root->retired == 1);
        Check(f.activate->ShutdownObject() == MF_E_SHUTDOWN && f.root->retired == 1);
        DWORD flags = 0; Check(source->GetCharacteristics(&flags) == MF_E_SHUTDOWN);
    }

    void ReleasedActivationDoesNotShutdownHeldSource()
    {
        Fixture f; ComPtr<IMFMediaSourceEx> source;
        Ok(f.activate->ActivateObject(IID_PPV_ARGS(&source)));
        f.activate.Reset();
        DWORD flags = 0;
        const HRESULT live = source->GetCharacteristics(&flags);
        const bool stillLive = SUCCEEDED(live) && flags == MFMEDIASOURCE_IS_LIVE && f.root->retired == 0;
        source->Shutdown();
        if (!stillLive) std::printf("REPRO released-activation-held-source HRESULT=%08lx\n", static_cast<unsigned long>(live));
        Check(stillLive);
    }

    void DetachedSourceKeepsNativeContext()
    {
        struct Event { HANDLE handle = CreateEventW(nullptr, TRUE, FALSE, nullptr); ~Event() { if (handle) CloseHandle(handle); } } ended;
        Check(ended.handle != nullptr); std::atomic_int deaths{0};
        auto root = Microsoft::WRL::Make<Root>(); root->died = ended.handle; root->deaths = &deaths;
        ComPtr<IMFActivate> activate; Ok(CreateActivate(root->Owner(), &activate)); root.Reset();
        ComPtr<IMFMediaSourceEx> source; Ok(activate->ActivateObject(IID_PPV_ARGS(&source)));
        Ok(activate->DetachObject());
        ComPtr<IMFMediaSource> replacement; Check(activate->ActivateObject(IID_PPV_ARGS(&replacement)) == MF_E_SHUTDOWN && !replacement);
        activate.Reset(); Check(deaths == 0);
        DWORD flags = 0; Ok(source->GetCharacteristics(&flags)); Check(flags == MFMEDIASOURCE_IS_LIVE);
        Ok(source->Shutdown()); source.Reset();
        Check(WaitForSingleObject(ended.handle, 1500) == WAIT_OBJECT_0 && deaths == 1);
    }

    void UnsupportedInterfaceAndInvalidArguments()
    {
        Fixture f; void* unknown = reinterpret_cast<void*>(1);
        const GUID notAnInterface = {0x9f018a2f, 0x145b, 0x4bd3, {0xb2, 0xdd, 0xc9, 0xe4, 0xd7, 0x5f, 0x87, 0x26}};
        Check(f.activate->ActivateObject(notAnInterface, &unknown) == E_NOINTERFACE && !unknown && f.root->constructed == 1);
        ComPtr<IMFMediaSource> source; Ok(f.activate->ActivateObject(IID_PPV_ARGS(&source))); Check(f.root->constructed == 1);
        Check(f.activate->ActivateObject(IID_IMFMediaSource, nullptr) == E_POINTER);
        ComPtr<IMFActivate> bad; auto owner = f.root->Owner(); owner.current = nullptr;
        Check(CreateActivate(owner, &bad) == E_INVALIDARG && !bad);
        owner = f.root->Owner(); owner.construct = nullptr; Check(CreateActivate(owner, &bad) == E_INVALIDARG && !bad);
        Check(CreateActivate(f.root->Owner(), nullptr) == E_POINTER);
    }
}

int main(int argc, char** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET))) { CoUninitialize(); return 3; }
    int failed = 0;
    const struct { const char* name; void (*run)(); } cases[] = {
        {"activate-metadata-snapshot-original-source", MetadataSnapshotAndOriginalSource}, {"activate-metadata-not-authority", MetadataCannotGrantAuthority},
        {"activate-construction-failure-no-retry", FailedConstructionDoesNotRetry}, {"activate-context-lost-during-construct", LostOriginalContextDuringConstruction},
        {"activate-original-context-revoked", OriginalContextRevokedAfterActivation}, {"activate-shutdown-original-source", ShutdownRetiresOnlyOriginalSource},
        {"activate-detached-source-context-lifetime", DetachedSourceKeepsNativeContext}, {"activate-unsupported-interface-arguments", UnsupportedInterfaceAndInvalidArguments},
        {"activate-release-preserves-held-source", ReleasedActivationDoesNotShutdownHeldSource}
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
