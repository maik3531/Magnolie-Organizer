#include "../../native/phone-camera/PhoneCameraDormantSource.h"
#include <mfapi.h>
#include <mferror.h>
#include <ks.h>
#include <ksproxy.h>
#include <wrl.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <future>
#include <string>
#include <stdexcept>
#include <vector>

using namespace Magnolie::PhoneCamera;
using Microsoft::WRL::ComPtr;

namespace Magnolie::PhoneCamera
{
    struct DormantSourceTestAccess
    {
        static std::unique_ptr<SourceBindingProof> Proof(const DormantSourceControl& target,
            SourceOwner owner, const GUID& scope, std::shared_ptr<PresentationClock> clock)
        { return std::unique_ptr<SourceBindingProof>(new SourceBindingProof(target, owner, scope, std::move(clock))); }
    };
}
namespace
{
    void CheckAt(bool value, int line) { if (!value) throw std::runtime_error("dormant source assertion line " + std::to_string(line)); }
#define Check(value) CheckAt(value, __LINE__)
    void Ok(HRESULT hr) { if (hr != S_OK) throw std::runtime_error("dormant source HRESULT " + std::to_string(static_cast<long>(hr))); }
    class Root final : public Microsoft::WRL::RuntimeClass<Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, IUnknown>
    {
    public:
        std::atomic<HRESULT> registration{S_OK}, capture{S_OK}, sending{S_OK}, reason{S_OK};
        std::atomic_int checks{0}, retired{0};
        std::atomic_int closed{0};
        std::atomic<DormantSourceControl*> stopOnCapture{nullptr};
        std::unique_ptr<DormantSourceControl> ownedControl;
        std::atomic_int* deaths = nullptr;
        ~Root() { if (deaths) ++*deaths; }
        static HRESULT Registration(void* context) noexcept { return static_cast<Root*>(context)->registration.load(); }
        static HRESULT Current(void* context) noexcept
        {
            auto& root = *static_cast<Root*>(context); ++root.checks;
            if (auto control = root.stopOnCapture.exchange(nullptr)) control->Stop();
            return root.capture.load();
        }
        static HRESULT Sending(void* context) noexcept { return static_cast<Root*>(context)->sending.load(); }
        static void Retired(void* context, HRESULT reason) noexcept
        {
            auto& root = *static_cast<Root*>(context);
            if (root.retired.fetch_add(1) == 0) root.reason = reason;
            root.capture = MF_E_SHUTDOWN;
        }
        static void Closed(void* context) noexcept
        { auto& root = *static_cast<Root*>(context); ++root.closed; root.ownedControl.reset(); }
        RegistrationLifetime RegistrationOwner() { return {Registration, this, this}; }
        SourceOwner CaptureOwner() { return {Current, Sending, Retired, this, this}; }
        ClockOwner ClockCallbacks() { return {Current, Sending, Retired, this, this}; }
    };
    struct Fixture
    {
        ComPtr<Root> root = Microsoft::WRL::Make<Root>();
        ComPtr<IMFMediaSourceEx> source;
        std::unique_ptr<DormantSourceControl> control;
        std::shared_ptr<PresentationClock> clock;
        GUID scope{};
        explicit Fixture(IMFAttributes* metadata = nullptr)
        { Check(root != nullptr); clock = std::make_shared<PresentationClock>(root->ClockCallbacks()); Ok(CoCreateGuid(&scope)); Ok(CreateDormantSource(root->RegistrationOwner(), &source, control, metadata)); }
        ~Fixture() { if (control) control->Stop(); }
        std::unique_ptr<SourceBindingProof> Proof()
        { return DormantSourceTestAccess::Proof(*control, root->CaptureOwner(), scope, clock); }
    };

    void DormantMetadataNeverCreatesCaptureAuthority()
    {
        Fixture f; f.root->capture = E_ACCESSDENIED;
        DWORD flags = 0; Ok(f.source->GetCharacteristics(&flags)); Check(flags == MFMEDIASOURCE_IS_LIVE);
        ComPtr<IMFAttributes> attributes; Ok(f.source->GetSourceAttributes(&attributes));
        const GUID flag = {0x61266b14,0x4cec,0x4f94,{0xb4,0x3a,0xb3,0xc8,0x7c,0xe6,0x46,0x59}};
        Ok(attributes->SetUINT32(flag, TRUE));
        ComPtr<IMFPresentationDescriptor> descriptor;
        Check(f.source->CreatePresentationDescriptor(&descriptor) == MF_E_NOT_INITIALIZED && !descriptor);
        PROPVARIANT position{};
        Check(f.source->Start(nullptr, nullptr, &position) == MF_E_NOT_INITIALIZED);
        Check(f.source->Stop() == MF_E_NOT_INITIALIZED && f.source->Pause() == MF_E_NOT_INITIALIZED);
        ComPtr<IMFMediaEvent> event;
        Check(f.source->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event) == MF_E_NOT_INITIALIZED && !event);
        ComPtr<IFrameFeed> feed;
        Check(f.source.As(&feed) == E_NOINTERFACE && !feed);
        Check(f.control->GetBoundFeed(&feed) == MF_E_NOT_INITIALIZED && !feed);
        Check(f.root->checks == 0 && f.root->retired == 0);
    }
    void MetadataSurvivesBindingWithoutMaskingCaptureLoss()
    {
        ComPtr<IMFAttributes> activation; Ok(MFCreateAttributes(&activation, 4));
        Ok(activation->SetString(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK, L"original-metadata-only"));
        Ok(activation->SetUINT32(MF_DEVICESTREAM_ATTRIBUTE_FRAMESOURCE_TYPES, 0xffffffff));
        Fixture f(activation.Get());
        Ok(activation->SetString(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK, L"caller-replacement"));
        auto check = [&] {
            ComPtr<IMFAttributes> attributes; Ok(f.source->GetSourceAttributes(&attributes));
            wchar_t value[64]{}; UINT32 used = 0, type = 0;
            Ok(attributes->GetString(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK, value, 64, &used));
            Check(std::wstring(value) == L"original-metadata-only");
            Ok(attributes->GetUINT32(MF_DEVICESTREAM_ATTRIBUTE_FRAMESOURCE_TYPES, &type)); Check(type == MFFrameSourceTypes_Color);
        };
        check(); Check(f.root->checks == 0);
        f.root->sending = E_ACCESSDENIED; Ok(f.control->Adopt(f.Proof()));
        check(); Check(f.root->retired == 0); // Metadata never requires/grants SEND.
        f.root->capture = E_ACCESSDENIED;
        ComPtr<IMFAttributes> denied; Check(f.source->GetSourceAttributes(&denied) == E_ACCESSDENIED && !denied);
        Check(f.root->retired == 1 && f.root->registration == S_OK);
        f.root->capture = S_OK; Check(FAILED(f.source->GetSourceAttributes(&denied)) && !denied);
    }
    void ExternalPropertiesCannotConstructProof()
    {
        Fixture f; ComPtr<IKsControl> properties; Ok(f.source.As(&properties));
        KSPROPERTY property{}; property.Flags = KSPROPERTY_TYPE_SET;
        BYTE bytes[64]{}; ULONG used = 99;
        Check(properties->KsProperty(&property, sizeof(property), bytes, sizeof(bytes), &used) == HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND));
        Check(used == 0 && f.control->RequireBound() == MF_E_NOT_INITIALIZED && f.root->checks == 0);
        property.Flags = KSPROPERTY_TYPE_GET; used = 99;
        Check(properties->KsProperty(&property, sizeof(property), bytes, sizeof(bytes), &used) == HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND) && used == 0);
        Check(f.control->Adopt(nullptr) == E_ACCESSDENIED && f.root->retired == 0);
    }
    void WrongTargetDoesNotConsumeOriginalSlot()
    {
        Fixture first, second;
        auto proof = first.Proof();
        Check(second.control->Adopt(std::move(proof)) == E_ACCESSDENIED);
        Check(first.root->checks == 0 && second.root->checks == 0 && first.root->retired == 0 && second.root->retired == 0);
        Ok(second.control->Adopt(second.Proof())); Ok(second.control->RequireBound());
        Check(first.control->RequireBound() == MF_E_NOT_INITIALIZED);
    }
    void OneOriginalAdoptionAndNoReplacement()
    {
        Fixture f; f.root->sending = E_ACCESSDENIED;
        Ok(f.control->Adopt(f.Proof())); Ok(f.control->RequireBound());
        ComPtr<IMFPresentationDescriptor> descriptor; Ok(f.source->CreatePresentationDescriptor(&descriptor));
        auto later = f.Proof(); Check(f.control->Adopt(std::move(later)) == MF_E_SHUTDOWN);
        // Preparation does not publish SEND or manufacture a receipt-time anchor.
        ComPtr<IFrameFeed> feed; Ok(f.control->GetBoundFeed(&feed));
        std::vector<BYTE> picture(Samples::VideoBytes);
        Check(FAILED(feed->PublishVideo(picture.data(), static_cast<DWORD>(picture.size()), 0, 0)));
        Check(f.root->retired == 1);
        f.root->capture = S_OK; f.root->sending = S_OK;
        Check(f.control->RequireBound() == MF_E_SHUTDOWN);
    }
    void RegistrationRevocationIsNotCapturePermission()
    {
        Fixture f; f.root->registration = S_FALSE;
        DWORD flags = 99;
        Check(f.source->GetCharacteristics(&flags) == E_ACCESSDENIED && flags == 0);
        f.root->registration = S_OK;
        Check(f.control->Adopt(f.Proof()) == MF_E_SHUTDOWN);
        Check(f.root->checks == 0 && f.root->retired == 0);
    }
    void StopDuringAdoptionDoesNotPublishCandidate()
    {
        Fixture f; f.root->stopOnCapture = f.control.get();
        Check(f.control->Adopt(f.Proof()) == MF_E_SHUTDOWN);
        ComPtr<IFrameFeed> feed; Check(f.control->GetBoundFeed(&feed) == MF_E_SHUTDOWN && !feed);
        Check(f.root->retired == 1 && f.control->Stop() == MF_E_SHUTDOWN);
    }
    void ForeignClockDoesNotCreateCaptureSource()
    {
        Fixture f, foreign;
        auto wrong = DormantSourceTestAccess::Proof(*f.control, f.root->CaptureOwner(), f.scope,
            foreign.clock);
        Check(f.control->Adopt(std::move(wrong)) == E_ACCESSDENIED);
        Check(f.root->checks == 0 && f.root->retired == 0);
        Ok(f.control->Adopt(f.Proof()));
    }
    void RegistrationModuleLifetimeSurvivesControlRelease()
    {
        std::atomic_int deaths{0};
        auto root = Microsoft::WRL::Make<Root>(); root->deaths = &deaths;
        ComPtr<IMFMediaSourceEx> source; std::unique_ptr<DormantSourceControl> control;
        Ok(CreateDormantSource(root->RegistrationOwner(), &source, control));
        root.Reset(); Check(deaths == 0); control.reset(); Check(deaths == 0);
        DWORD flags = 99; Check(source->GetCharacteristics(&flags) == MF_E_SHUTDOWN && flags == 0);
        source.Reset(); Check(deaths == 1);
    }
    void StopUnblocksDelegatedEventWait()
    {
        Fixture f; Ok(f.control->Adopt(f.Proof()));
        auto waiting = std::async(std::launch::async, [&] {
            ComPtr<IMFMediaEvent> event; return f.source->GetEvent(0, &event);
        });
        const bool pending = waiting.wait_for(std::chrono::milliseconds(30)) == std::future_status::timeout;
        f.control->Stop();
        Check(waiting.wait_for(std::chrono::seconds(2)) == std::future_status::ready);
        Check(waiting.get() == MF_E_SHUTDOWN && pending && f.root->retired == 1);
    }
    void StaleTargetProofCannotAdoptNewShell()
    {
        Fixture old, replacement;
        auto proof = old.Proof(); Ok(old.control->Stop());
        Check(replacement.control->Adopt(std::move(proof)) == E_ACCESSDENIED);
        Check(replacement.root->checks == 0 && replacement.root->retired == 0);
        Ok(replacement.control->Adopt(replacement.Proof())); Ok(replacement.control->RequireBound());
    }
    void LivingRegistrationDoesNotMaskLostCaptureOwner()
    {
        Fixture f; Ok(f.control->Adopt(f.Proof()));
        f.root->capture = E_ACCESSDENIED;
        DWORD flags = 99; Check(FAILED(f.source->GetCharacteristics(&flags)) && flags == 0);
        ComPtr<IMFAttributes> attributes; Check(FAILED(f.source->GetSourceAttributes(&attributes)) && !attributes);
        Check(f.root->registration == S_OK && f.root->retired == 1);
        f.root->capture = S_OK;
        Check(f.control->RequireBound() == MF_E_SHUTDOWN);
    }
    void RegistryReleasesControllerOnSourceShutdown()
    {
        std::atomic_int deaths{0};
        auto root = Microsoft::WRL::Make<Root>(); root->deaths = &deaths;
        ComPtr<IMFMediaSourceEx> source;
        Ok(CreateDormantSource({Root::Registration, root.Get(), root.Get(), Root::Closed}, &source, root->ownedControl));
        Root* held = root.Get(); root.Reset();
        Ok(source->Shutdown()); Check(held->closed == 1 && !held->ownedControl && held->retired == 0);
        Check(source->Shutdown() == MF_E_SHUTDOWN && held->closed == 1 && deaths == 0);
        source.Reset(); Check(deaths == 1);
    }
    void RegistryCanReleaseCallingStopController()
    {
        std::atomic_int deaths{0};
        auto root = Microsoft::WRL::Make<Root>(); root->deaths = &deaths;
        ComPtr<IMFMediaSourceEx> source;
        Ok(CreateDormantSource({Root::Registration, root.Get(), root.Get(), Root::Closed}, &source, root->ownedControl));
        Root* held = root.Get(); auto calling = root->ownedControl.get(); root.Reset();
        Ok(calling->Stop()); // Callback intentionally destroys calling, not its held state.
        Check(held->closed == 1 && !held->ownedControl && held->retired == 0);
        DWORD flags = 99; Check(source->GetCharacteristics(&flags) == MF_E_SHUTDOWN && flags == 0);
        source.Reset(); Check(deaths == 1);
    }
    void RegistryCanReleaseControllerDuringAdoption()
    {
        Fixture f;
        // Recreate only the dormant shell, with the native registry notification.
        f.control.reset(); f.source.Reset();
        Ok(CreateDormantSource({Root::Registration, f.root.Get(), f.root.Get(), Root::Closed}, &f.source, f.control));
        auto proof = f.Proof();
        auto calling = f.control.get(); f.root->ownedControl = std::move(f.control);
        f.root->stopOnCapture = calling;
        Check(calling->Adopt(std::move(proof)) == MF_E_SHUTDOWN);
        Check(f.root->closed == 1 && !f.root->ownedControl && f.root->retired == 1);
        ComPtr<IMFPresentationDescriptor> descriptor;
        Check(f.source->CreatePresentationDescriptor(&descriptor) == MF_E_SHUTDOWN && !descriptor);
    }
}
int main(int argc, char** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET))) { CoUninitialize(); return 3; }
    const struct { const char* name; void (*run)(); } cases[] = {
        {"dormant-metadata-bound-owner-loss", MetadataSurvivesBindingWithoutMaskingCaptureLoss},
        {"dormant-no-capture-authority", DormantMetadataNeverCreatesCaptureAuthority},
        {"dormant-no-property-grant", ExternalPropertiesCannotConstructProof},
        {"dormant-exact-target", WrongTargetDoesNotConsumeOriginalSlot},
        {"dormant-one-original-no-send", OneOriginalAdoptionAndNoReplacement},
        {"dormant-registration-revoked", RegistrationRevocationIsNotCapturePermission},
        {"dormant-stop-during-adoption", StopDuringAdoptionDoesNotPublishCandidate},
        {"dormant-original-clock", ForeignClockDoesNotCreateCaptureSource},
        {"dormant-module-lifetime", RegistrationModuleLifetimeSurvivesControlRelease},
        {"dormant-stop-unblocks-event-wait", StopUnblocksDelegatedEventWait},
        {"dormant-stale-target", StaleTargetProofCannotAdoptNewShell},
        {"dormant-lost-capture-owner", LivingRegistrationDoesNotMaskLostCaptureOwner},
        {"dormant-registry-source-shutdown", RegistryReleasesControllerOnSourceShutdown},
        {"dormant-registry-release-in-stop", RegistryCanReleaseCallingStopController},
        {"dormant-registry-release-in-adoption", RegistryCanReleaseControllerDuringAdoption}
    };
    const std::string selection = argc == 2 ? "," + std::string(argv[1]) + "," : "";
    if (argc > 2) { MFShutdown(); CoUninitialize(); return 4; }
    int failed = 0, selected = 0;
    for (const auto& test : cases)
    {
        if (!selection.empty() && selection.find("," + std::string(test.name) + ",") == std::string::npos) continue;
        ++selected;
        try { test.run(); std::printf("PASS %s\n", test.name); }
        catch (const std::exception& error) { ++failed; std::printf("FAIL %s (%s)\n", test.name, error.what()); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
        std::fflush(stdout);
    }
    MFShutdown(); CoUninitialize(); return !selected ? 4 : failed ? 1 : 0;
}
