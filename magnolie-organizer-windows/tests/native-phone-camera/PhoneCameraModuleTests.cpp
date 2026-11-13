#include "../../native/phone-camera/PhoneCameraModule.h"
#include "../../native/phone-camera/PhoneCameraSource.h"
#include <mfapi.h>
#include <mferror.h>
#include <ks.h>
#include <ksproxy.h>
#include <wrl/client.h>
#include <cstdio>
#include <stdexcept>
#include <string>

using namespace Magnolie::PhoneCamera;
using Microsoft::WRL::ComPtr;
namespace
{
    using FactoryFunction = HRESULT (WINAPI*)(REFCLSID, REFIID, void**);
    using UnloadFunction = HRESULT (WINAPI*)();
    FactoryFunction factory = nullptr;
    UnloadFunction unload = nullptr;
    void Check(bool value) { if (!value) throw std::runtime_error("source module assertion"); }
    void Ok(HRESULT hr) { Check(hr == S_OK); }
    ComPtr<IClassFactory> Factory()
    { ComPtr<IClassFactory> result; Ok(factory(SourceClassId, IID_PPV_ARGS(&result))); return result; }
    ComPtr<IMFActivate> Activation(IClassFactory* from)
    { ComPtr<IMFActivate> result; Ok(from->CreateInstance(nullptr, IID_PPV_ARGS(&result))); return result; }
    ComPtr<IMFMediaSourceEx> Source(IMFActivate* from)
    { ComPtr<IMFMediaSourceEx> result; Ok(from->ActivateObject(IID_PPV_ARGS(&result))); return result; }
    void UnknownClassAndInterfaceDoNotRetainModule()
    {
        Ok(unload()); void* result = reinterpret_cast<void*>(1);
        Check(factory(GUID_NULL, IID_IUnknown, &result) == CLASS_E_CLASSNOTAVAILABLE && !result);
        Check(factory(SourceClassId, __uuidof(IFrameFeed), &result) == E_NOINTERFACE && !result);
        Check(factory(SourceClassId, IID_IUnknown, nullptr) == E_POINTER); Ok(unload());
    }
    void FactoryAndActivationHoldIndependentModuleLifetime()
    {
        Ok(unload()); auto owner = Factory(); Check(unload() == S_FALSE);
        auto activation = Activation(owner.Get()); owner.Reset(); Check(unload() == S_FALSE);
        activation.Reset(); Ok(unload());
    }
    void ActualModuleIsDormantAndIgnoresAuthorityMetadata()
    {
        auto owner = Factory(); auto activation = Activation(owner.Get()); owner.Reset();
        const GUID metadata = {0xc28e72db,0x5c42,0x4918,{0x84,0xdb,0xab,0xa0,0xd9,0xb3,0x48,0x45}};
        Ok(activation->SetUINT32(metadata, TRUE)); auto source = Source(activation.Get());
        ComPtr<IMFPresentationDescriptor> descriptor;
        Check(source->CreatePresentationDescriptor(&descriptor) == MF_E_NOT_INITIALIZED && !descriptor);
        PROPVARIANT position{}; Check(source->Start(nullptr, nullptr, &position) == MF_E_NOT_INITIALIZED);
        ComPtr<IFrameFeed> feed; Check(source.As(&feed) == E_NOINTERFACE && !feed);
        ComPtr<IKsControl> control; Ok(source.As(&control));
        KSPROPERTY property{}; property.Flags = KSPROPERTY_TYPE_SET;
        BYTE bytes[64]{}; ULONG used = 99;
        Check(control->KsProperty(&property, sizeof(property), bytes, sizeof(bytes), &used) == HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND) && used == 0);
        Ok(activation->ShutdownObject()); control.Reset(); source.Reset(); activation.Reset(); Ok(unload());
    }
    void ActivationReleaseDoesNotRevokeHeldSource()
    {
        auto owner = Factory(); auto activation = Activation(owner.Get()); auto source = Source(activation.Get());
        owner.Reset(); activation.Reset(); Check(unload() == S_FALSE);
        DWORD flags = 0; Ok(source->GetCharacteristics(&flags)); Check(flags == MFMEDIASOURCE_IS_LIVE);
        Ok(source->Shutdown()); Check(unload() == S_FALSE);
        source.Reset(); Ok(unload());
    }
    void DetachedOriginalSourceKeepsItsOwnLifetime()
    {
        auto owner = Factory(); auto activation = Activation(owner.Get()); auto source = Source(activation.Get());
        Ok(activation->DetachObject());
        ComPtr<IMFMediaSourceEx> replacement;
        Check(activation->ActivateObject(IID_PPV_ARGS(&replacement)) == MF_E_SHUTDOWN && !replacement);
        owner.Reset(); activation.Reset(); Check(unload() == S_FALSE);
        Ok(source->Shutdown()); source.Reset(); Ok(unload());
    }
    void SeparateActivationsDoNotRetireEachOther()
    {
        auto owner = Factory(); auto a = Activation(owner.Get()); auto b = Activation(owner.Get());
        auto first = Source(a.Get()); auto second = Source(b.Get());
        Ok(first->Shutdown()); DWORD flags = 0; Ok(second->GetCharacteristics(&flags));
        ComPtr<IMFMediaSourceEx> revived;
        Check(FAILED(a->ActivateObject(IID_PPV_ARGS(&revived))) && !revived);
        Check(unload() == S_FALSE); Ok(second->Shutdown());
        first.Reset(); second.Reset(); a.Reset(); b.Reset(); owner.Reset(); Ok(unload());
    }
    void ExplicitServerLockDoesNotUnderflowOrImpersonateCapture()
    {
        auto owner = Factory(); Check(owner->LockServer(FALSE) == E_UNEXPECTED);
        Ok(owner->LockServer(TRUE)); owner.Reset(); Check(unload() == S_FALSE);
        auto release = Factory(); Ok(release->LockServer(FALSE));
        Check(release->LockServer(FALSE) == E_UNEXPECTED); release.Reset(); Ok(unload());
    }
}
int wmain(int argc, wchar_t** argv)
{
    if (argc != 2 || FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET))) { CoUninitialize(); return 3; }
    HMODULE module = LoadLibraryExW(argv[1], nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!module) { MFShutdown(); CoUninitialize(); return 4; }
    factory = reinterpret_cast<FactoryFunction>(GetProcAddress(module, "DllGetClassObject"));
    unload = reinterpret_cast<UnloadFunction>(GetProcAddress(module, "DllCanUnloadNow"));
    int failed = 0;
    if (!factory || !unload || GetProcAddress(module, "DllRegisterServer") || GetProcAddress(module, "DllUnregisterServer")) failed = 1;
    const struct { const char* name; void (*run)(); } cases[] = {
        {"module-exact-class-interface", UnknownClassAndInterfaceDoNotRetainModule},
        {"module-factory-activation-lifetime", FactoryAndActivationHoldIndependentModuleLifetime},
        {"module-dormant-no-property-grant", ActualModuleIsDormantAndIgnoresAuthorityMetadata},
        {"module-activation-release-held-source", ActivationReleaseDoesNotRevokeHeldSource},
        {"module-detached-original-source", DetachedOriginalSourceKeepsItsOwnLifetime},
        {"module-separate-originals", SeparateActivationsDoNotRetireEachOther},
        {"module-explicit-server-lock", ExplicitServerLockDoesNotUnderflowOrImpersonateCapture}
    };
    if (!failed) for (const auto& test : cases)
    {
        try { test.run(); std::printf("PASS %s\n", test.name); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
        std::fflush(stdout);
    }
    // Do not unload a failed test's still-held native callbacks. Its bounded
    // test process exits; no unsafe FreeLibrary is used to force a passing result.
    if (unload && unload() == S_OK)
    {
        if (!FreeLibrary(module)) ++failed;
        if (GetModuleHandleW(argv[1])) ++failed;
    }
    else ++failed;
    MFShutdown(); CoUninitialize(); return failed ? 1 : 0;
}
