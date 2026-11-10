#include "PhoneCameraFactoryProbe.h"
#include <mfapi.h>
#include <mfidl.h>
#include <mferror.h>
#include <wrl/client.h>
#include <cstdio>
#include <cstring>
#include <stdexcept>

using Microsoft::WRL::ComPtr;
namespace
{
    int cleanupFailures = 0;
    const wchar_t* libraryPath = nullptr;
    void Check(bool condition) { if (!condition) throw std::runtime_error("factory assertion"); }
    void Ok(HRESULT hr) { if (FAILED(hr)) { std::printf("HRESULT %08lx\n", static_cast<unsigned long>(hr)); Check(false); } }
    struct Module
    {
        HMODULE library = nullptr;
        using GetClass = HRESULT (WINAPI*)(REFCLSID, REFIID, void**);
        using CanUnload = HRESULT (WINAPI*)();
        GetClass getClass = nullptr;
        CanUnload canUnload = nullptr;
        Module()
        {
            Ok(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET));
            library = LoadLibraryExW(libraryPath, nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
            if (!library) { MFShutdown(); Check(false); }
            FARPROC get = GetProcAddress(library, "DllGetClassObject"), unload = GetProcAddress(library, "DllCanUnloadNow");
            static_assert(sizeof(get) == sizeof(getClass) && sizeof(unload) == sizeof(canUnload));
            std::memcpy(&getClass, &get, sizeof(getClass)); std::memcpy(&canUnload, &unload, sizeof(canUnload));
            Check(getClass && canUnload); Check(canUnload() == S_OK);
        }
        ~Module()
        {
            // All test-owned COM locals are released before this scope ends.
            // Drain native MF callbacks before actually unloading their DLL code.
            MFShutdown();
            if (library)
            {
                if (canUnload && canUnload() == S_OK) FreeLibrary(library);
                else { ++cleanupFailures; std::puts("FAIL module-still-owned"); }
            }
        }
        ComPtr<IClassFactory> Factory()
        { ComPtr<IClassFactory> result; Ok(getClass(FactoryProbeId, IID_PPV_ARGS(&result))); return result; }
    };

    void RolesAggregationAndArguments()
    {
        Module module; void* missing = reinterpret_cast<void*>(1);
        Check(module.getClass(GUID_NULL, IID_IClassFactory, &missing) == CLASS_E_CLASSNOTAVAILABLE && !missing);
        Check(module.getClass(FactoryProbeId, IID_IClassFactory, nullptr) == E_POINTER);
        auto factory = module.Factory(); Check(module.canUnload() == S_FALSE);
        Check(factory->CreateInstance(reinterpret_cast<IUnknown*>(1), __uuidof(IMFActivate), &missing) == CLASS_E_NOAGGREGATION && !missing);
        Check(factory->CreateInstance(nullptr, __uuidof(IMFMediaSource), &missing) == E_NOINTERFACE && !missing);
        Check(factory->CreateInstance(nullptr, __uuidof(IMFActivate), nullptr) == E_POINTER);
    }

    void FreshActivationsAndBaseInterfaces()
    {
        Module module; auto factory = module.Factory();
        ComPtr<IMFActivate> a, b; Ok(factory->CreateInstance(nullptr, IID_PPV_ARGS(&a))); Ok(factory->CreateInstance(nullptr, IID_PPV_ARGS(&b)));
        ComPtr<IUnknown> ia, ib; Ok(a.As(&ia)); Ok(b.As(&ib)); Check(ia.Get() != ib.Get());
        ComPtr<IMFAttributes> attributes; Ok(a.As(&attributes));
        ComPtr<IMFMediaSourceEx> source; Ok(a->ActivateObject(IID_PPV_ARGS(&source)));
        DWORD flags = 0; Ok(source->GetCharacteristics(&flags)); Check(flags == MFMEDIASOURCE_IS_LIVE);
        Ok(a->ShutdownObject()); Ok(b->ShutdownObject());
    }

    void SourceAndOldStreamKeepDllOwned()
    {
        Module module; auto factory = module.Factory(); ComPtr<IMFActivate> activate;
        Ok(factory->CreateInstance(nullptr, IID_PPV_ARGS(&activate)));
        ComPtr<IMFMediaSourceEx> source; Ok(activate->ActivateObject(IID_PPV_ARGS(&source)));
        ComPtr<IMFPresentationDescriptor> pd; Ok(source->CreatePresentationDescriptor(&pd));
        PROPVARIANT start{}; start.vt = VT_EMPTY; Ok(source->Start(pd.Get(), nullptr, &start));
        ComPtr<IMFMediaEvent> event; Ok(source->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event));
        PROPVARIANT streamValue{}; Ok(event->GetValue(&streamValue));
        Check(streamValue.vt == VT_UNKNOWN && streamValue.punkVal); ComPtr<IMFMediaStream> stream;
        Ok(streamValue.punkVal->QueryInterface(IID_PPV_ARGS(&stream))); PropVariantClear(&streamValue); event.Reset();
        Ok(activate->DetachObject()); factory.Reset(); activate.Reset();
        Check(module.canUnload() == S_FALSE); Ok(source->Shutdown()); source.Reset();
        Check(module.canUnload() == S_FALSE); stream.Reset();
        // Module's destructor drains callbacks, checks unloadability, then really
        // FreeLibrary's this otherwise entirely unregistered private probe DLL.
    }

    void ServerLockBalancesAcrossFactoryLifetimes()
    {
        Module module; auto factory = module.Factory(); Ok(factory->LockServer(TRUE)); factory.Reset();
        Check(module.canUnload() == S_FALSE);
        factory = module.Factory(); Ok(factory->LockServer(FALSE));
        Check(factory->LockServer(FALSE) == E_UNEXPECTED); factory.Reset(); Check(module.canUnload() == S_OK);
    }
}

int wmain(int argc, wchar_t** argv)
{
    if (argc != 2 || FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    libraryPath = argv[1]; int failed = 0;
    const struct { const char* name; void (*run)(); } cases[] = {
        {"factory-dll-roles-aggregation", RolesAggregationAndArguments}, {"factory-dll-fresh-activation-contexts", FreshActivationsAndBaseInterfaces},
        {"factory-dll-source-stream-lifetime", SourceAndOldStreamKeepDllOwned}, {"factory-dll-server-lock-lifetime", ServerLockBalancesAcrossFactoryLifetimes}
    };
    for (const auto& test : cases)
    {
        const int previous = cleanupFailures;
        try { test.run(); Check(cleanupFailures == previous); std::printf("PASS %s\n", test.name); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
        std::fflush(stdout);
    }
    CoUninitialize(); return failed ? 1 : 0;
}
