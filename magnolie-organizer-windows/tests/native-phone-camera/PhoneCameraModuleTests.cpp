#include "../../native/phone-camera/PhoneCameraModule.h"
#include "../../native/phone-camera/PhoneCameraSource.h"
#include "../../native/phone-camera/PhoneCameraBrokerProtocol.h"
#include <mfapi.h>
#include <mferror.h>
#include <ks.h>
#include <ksproxy.h>
#include <wrl.h>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <algorithm>
#include <iterator>
#include <array>
#include <cstring>

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
    void ActivationMetadataRoundTripDoesNotAuthorizeCapture()
    {
        const GUID tag = {0x7b0022b1,0x3359,0x42a9,{0xa6,0xb7,0xe0,0x22,0x19,0xf5,0xa2,0x41}};
        const GUID blob = {0x7b0022b2,0x3359,0x42a9,{0xa6,0xb7,0xe0,0x22,0x19,0xf5,0xa2,0x41}};
        const BYTE data[] = {2, 4, 8, 16};
        auto owner = Factory(); auto activation = Activation(owner.Get());
        Ok(activation->SetString(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK, L"magnolie-metadata-original"));
        Ok(activation->SetGUID(tag, SourceClassId)); Ok(activation->SetBlob(blob, data, sizeof(data)));
        auto source = Source(activation.Get()); ComPtr<IMFAttributes> attributes;
        Ok(source->GetSourceAttributes(&attributes));
        wchar_t link[64]{}; GUID value{}; BYTE copied[4]{}; UINT32 used = 0;
        Ok(attributes->GetString(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK, link, 64, &used));
        Check(std::wstring(link) == L"magnolie-metadata-original");
        Ok(attributes->GetGUID(tag, &value)); Check(value == SourceClassId);
        Ok(attributes->GetBlob(blob, copied, sizeof(copied), &used));
        Check(used == sizeof(data) && std::equal(std::begin(data), std::end(data), std::begin(copied)));
        Ok(activation->SetString(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK, L"changed-activation"));
        Ok(attributes->SetString(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK, L"changed-returned-store"));
        attributes.Reset(); Ok(source->GetSourceAttributes(&attributes));
        Ok(attributes->GetString(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK, link, 64, &used));
        Check(std::wstring(link) == L"magnolie-metadata-original");
        PROPVARIANT position{}; Check(source->Start(nullptr, nullptr, &position) == MF_E_NOT_INITIALIZED);
        ComPtr<IFrameFeed> feed; Check(source.As(&feed) == E_NOINTERFACE && !feed);
        Ok(source->Shutdown()); attributes.Reset(); source.Reset(); activation.Reset(); owner.Reset(); Ok(unload());
    }
    class MetadataCookie final : public Microsoft::WRL::RuntimeClass<Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, IUnknown>
    {
    public:
        MetadataCookie(int* deaths, HRESULT* reentered) : deaths_(deaths), reentered_(reentered) {}
        ~MetadataCookie() { if (source) *reentered_ = source->Shutdown(); ++*deaths_; }
        IMFMediaSourceEx* source = nullptr; // Test holds it through this callback.
    private:
        int* deaths_; HRESULT* reentered_;
    };
    void MetadataLifetimeAndReentrantShutdown()
    {
        const GUID key = {0x7b0022b3,0x3359,0x42a9,{0xa6,0xb7,0xe0,0x22,0x19,0xf5,0xa2,0x41}};
        int deaths = 0; HRESULT reentered = E_UNEXPECTED;
        auto owner = Factory(); auto activation = Activation(owner.Get());
        auto cookie = Microsoft::WRL::Make<MetadataCookie>(&deaths, &reentered); Check(cookie != nullptr);
        Ok(activation->SetUnknown(key, cookie.Get())); auto source = Source(activation.Get()); cookie->source = source.Get();
        ComPtr<IMFAttributes> metadata; Ok(source->GetSourceAttributes(&metadata));
        ComPtr<IUnknown> held; Ok(metadata->GetUnknown(key, IID_PPV_ARGS(&held)));
        Ok(activation->DeleteAllItems()); cookie.Reset(); held.Reset(); metadata.Reset();
        Check(deaths == 0); // Only the source's snapshot still owns the cookie.
        Ok(source->Shutdown()); Check(deaths == 1 && reentered == MF_E_SHUTDOWN);
        Check(source->GetSourceAttributes(&metadata) == MF_E_SHUTDOWN && !metadata);
        source.Reset(); activation.Reset(); owner.Reset(); Ok(unload());
    }
    void SeparateMetadataAndIndependentSourceLifetime()
    {
        const GUID key = {0x7b0022b4,0x3359,0x42a9,{0xa6,0xb7,0xe0,0x22,0x19,0xf5,0xa2,0x41}};
        auto owner = Factory(); auto a = Activation(owner.Get()); auto b = Activation(owner.Get());
        Ok(a->SetString(key, L"source-a")); Ok(b->SetString(key, L"source-b"));
        auto first = Source(a.Get()); auto second = Source(b.Get());
        a.Reset(); owner.Reset();
        ComPtr<IMFAttributes> attributes; Ok(first->GetSourceAttributes(&attributes));
        wchar_t value[32]{}; UINT32 used = 0;
        Ok(attributes->GetString(key, value, 32, &used)); Check(std::wstring(value) == L"source-a");
        attributes.Reset(); Ok(first->Shutdown()); first.Reset();
        Ok(second->GetSourceAttributes(&attributes));
        Ok(attributes->GetString(key, value, 32, &used)); Check(std::wstring(value) == L"source-b");
        Ok(second->Shutdown()); attributes.Reset(); second.Reset(); b.Reset(); Ok(unload());
    }
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
    void ActualPropertyCannotForgeFrameServerHost()
    {
        auto owner = Factory(); auto activation = Activation(owner.Get()); auto source = Source(activation.Get());
        ComPtr<IKsControl> ks; Ok(source.As(&ks));
        std::array<BYTE, sizeof(KSPROPERTY) + BrokerProperty::Bytes> packet{};
        KSPROPERTY header{}; header.Set = BrokerProperty::PropertySet; header.Id = BrokerProperty::PropertyId;
        header.Flags = KSPROPERTY_TYPE_GET; std::memcpy(packet.data(), &header, sizeof(header));
        BYTE output[32]{}; std::fill(std::begin(output), std::end(output), BYTE{0xaa}); ULONG written = 123;
        Check(FAILED(ks->KsProperty(reinterpret_cast<PKSPROPERTY>(packet.data()), static_cast<ULONG>(packet.size()), output, sizeof(output), &written)) && !written);
        Check(std::all_of(std::begin(output), std::end(output), [](BYTE b) { return b == 0xaa; }));
        ComPtr<IMFAttributes> metadata; Ok(source->GetSourceAttributes(&metadata)); metadata.Reset();
        header.Flags = KSPROPERTY_TYPE_SET; std::memcpy(packet.data(), &header, sizeof(header));
        BYTE* body = packet.data() + sizeof(header); std::memcpy(body, "MGFSB001", 8);
        DWORD version = 1, size = BrokerProperty::Bytes, pid = GetCurrentProcessId(), session = 1; ULONGLONG birth = 1;
        std::memcpy(body + 8, &version, 4); std::memcpy(body + 12, &size, 4); std::memcpy(body + 16, &SourceClassId, 16);
        std::memcpy(body + 32, &SourceClassId, 16); std::memcpy(body + 48, &pid, 4); std::memcpy(body + 52, &session, 4);
        std::memcpy(body + 56, &birth, 8); std::fill(body + 64, body + 96, BYTE{1});
        Check(ks->KsProperty(reinterpret_cast<PKSPROPERTY>(packet.data()), static_cast<ULONG>(packet.size()), nullptr, 0, &written) == E_ACCESSDENIED && !written);
        DWORD flags = 0; Check(source->GetCharacteristics(&flags) == MF_E_SHUTDOWN);
        Check(FAILED(ks->KsProperty(reinterpret_cast<PKSPROPERTY>(packet.data()), static_cast<ULONG>(packet.size()), nullptr, 0, &written)));
        ks.Reset(); source.Reset(); activation.Reset(); owner.Reset(); Ok(unload());
    }
}
int wmain(int argc, wchar_t** argv)
{
    if ((argc != 2 && argc != 3) || FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET))) { CoUninitialize(); return 3; }
    HMODULE module = LoadLibraryExW(argv[1], nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!module) { MFShutdown(); CoUninitialize(); return 4; }
    factory = reinterpret_cast<FactoryFunction>(GetProcAddress(module, "DllGetClassObject"));
    unload = reinterpret_cast<UnloadFunction>(GetProcAddress(module, "DllCanUnloadNow"));
    int failed = 0;
    if (!factory || !unload || GetProcAddress(module, "DllRegisterServer") || GetProcAddress(module, "DllUnregisterServer")) failed = 1;
    const struct { const char* name; void (*run)(); } cases[] = {
        {"module-metadata-roundtrip-no-authority", ActivationMetadataRoundTripDoesNotAuthorizeCapture},
        {"module-metadata-release-reentrant-stop", MetadataLifetimeAndReentrantShutdown},
        {"module-metadata-separate-originals", SeparateMetadataAndIndependentSourceLifetime},
        {"module-exact-class-interface", UnknownClassAndInterfaceDoNotRetainModule},
        {"module-factory-activation-lifetime", FactoryAndActivationHoldIndependentModuleLifetime},
        {"module-dormant-no-property-grant", ActualModuleIsDormantAndIgnoresAuthorityMetadata},
        {"module-activation-release-held-source", ActivationReleaseDoesNotRevokeHeldSource},
        {"module-detached-original-source", DetachedOriginalSourceKeepsItsOwnLifetime},
        {"module-separate-originals", SeparateActivationsDoNotRetireEachOther},
        {"module-explicit-server-lock", ExplicitServerLockDoesNotUnderflowOrImpersonateCapture},
        {"module-original-property-host-denial", ActualPropertyCannotForgeFrameServerHost}
    };
    int executed = 0;
    if (!failed) for (const auto& test : cases)
    {
        std::wstring name; for (const char* at = test.name; *at; ++at) name.push_back(static_cast<wchar_t>(*at));
        if (argc == 3 && (L"," + std::wstring(argv[2]) + L",").find(L"," + name + L",") == std::wstring::npos) continue;
        ++executed;
        try { test.run(); std::printf("PASS %s\n", test.name); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
        std::fflush(stdout);
    }
    if (!executed) ++failed;
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
