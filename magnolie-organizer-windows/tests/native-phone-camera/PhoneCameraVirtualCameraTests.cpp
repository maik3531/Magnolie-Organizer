#include "../../native/phone-camera/PhoneCameraVirtualCamera.h"
#include <mferror.h>
#include <wrl.h>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <thread>

using namespace Magnolie::PhoneCamera;
namespace
{
    void Check(bool value) { if (!value) throw std::runtime_error("virtual camera lifecycle assertion"); }
    struct Calls
    {
        int starts = 0, shutdowns = 0, destroyed = 0;
        HRESULT startResult = S_OK, shutdownResult = S_OK;
        VirtualCamera* stopDuringStart = nullptr;
        HANDLE entered = nullptr, resume = nullptr;
    };
    struct Owner final : Microsoft::WRL::RuntimeClass<Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, IUnknown>
    {
        HRESULT status = S_OK;
        int* deaths = nullptr;
        ~Owner() { if (deaths) ++*deaths; }
        static HRESULT Current(void* context) noexcept { return static_cast<Owner*>(context)->status; }
        VirtualCameraOwner Callbacks() { return {Current, this, this}; }
    };
}
namespace Magnolie::PhoneCamera
{
    // Test-only private lifecycle seam. No native registration, source adoption,
    // SourceBindingProof, phone permission, audio or device API is exercised.
    struct VirtualCameraTestAccess
    {
        struct FakeSession final : VirtualCamera::Session
        {
            Calls& calls;
            explicit FakeSession(Calls& value) : calls(value) {}
            ~FakeSession() override { ++calls.destroyed; }
            HRESULT Start() noexcept override
            {
                ++calls.starts;
                if (calls.stopDuringStart) calls.stopDuringStart->RequestStop();
                if (calls.entered)
                {
                    SetEvent(calls.entered);
                    if (WaitForSingleObject(calls.resume, 5000) != WAIT_OBJECT_0) return E_ABORT;
                }
                return calls.startResult;
            }
            HRESULT Shutdown() noexcept override { ++calls.shutdowns; return calls.shutdownResult; }
        };
        static std::unique_ptr<VirtualCamera> Create(Owner& owner, Calls& calls)
        { return std::unique_ptr<VirtualCamera>(new VirtualCamera(owner.Callbacks(), std::make_unique<FakeSession>(calls))); }
        struct RetainedFake
        {
            VirtualCamera::Session* session;
            IUnknown* owner;
            // TEST ONLY: discard synthetic objects after verifying production
            // destructor retained them. Never calls Shutdown, never an OS session.
            void Discard() { delete session; owner->Release(); VirtualCamera::ResetFakeUncertainty(); }
        };
        static RetainedFake Observe(VirtualCamera& camera) { return {camera.session_.get(), camera.lifetime_.Get()}; }
    };
}
namespace
{
    void RegistrationNotReadiness()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); Calls calls;
        auto camera = VirtualCameraTestAccess::Create(*owner.Get(), calls);
        Check(camera->RequireCurrent() == MF_E_NOT_INITIALIZED && calls.starts == 0);
        Check(camera->Start() == S_OK && camera->RequireCurrent() == S_OK && calls.starts == 1);
        Check(camera->Start() == MF_E_SHUTDOWN && calls.starts == 1);
        Check(camera->Close() == S_OK && calls.shutdowns == 1 && calls.destroyed == 1);
        Check(camera->Close() == S_OK && calls.shutdowns == 1);
        Check(camera->RequireCurrent() == MF_E_SHUTDOWN);
        camera.reset(); Check(calls.shutdowns == 1);
    }
    void StopBeforeStart()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); Calls calls;
        auto camera = VirtualCameraTestAccess::Create(*owner.Get(), calls); camera->RequestStop();
        Check(camera->Start() == MF_E_SHUTDOWN && calls.starts == 0 && calls.shutdowns == 1);
    }
    void ExactOwnerStatus()
    {
        for (HRESULT status : {S_FALSE, static_cast<HRESULT>(2), E_ACCESSDENIED})
        {
            auto owner = Microsoft::WRL::Make<Owner>(); Calls calls; owner->status = status;
            auto camera = VirtualCameraTestAccess::Create(*owner.Get(), calls);
            Check(camera->Start() == E_ACCESSDENIED && calls.starts == 0 && calls.shutdowns == 1);
            owner->status = S_OK;
            Check(camera->Start() == MF_E_SHUTDOWN && calls.starts == 0);
        }
    }
    void AmbiguousStartNoRetry()
    {
        for (HRESULT status : {S_FALSE, E_FAIL})
        {
            auto owner = Microsoft::WRL::Make<Owner>(); Calls calls; calls.startResult = status;
            auto camera = VirtualCameraTestAccess::Create(*owner.Get(), calls);
            Check(FAILED(camera->Start()) && calls.starts == 1 && calls.shutdowns == 1);
            Check(camera->Start() == MF_E_SHUTDOWN && calls.starts == 1);
        }
    }
    void UnknownShutdownRetainsOriginal()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); Calls calls; calls.shutdownResult = E_FAIL;
        auto camera = VirtualCameraTestAccess::Create(*owner.Get(), calls);
        Check(camera->Start() == S_OK);
        Check(camera->Close() == E_FAIL && calls.shutdowns == 1 && calls.destroyed == 0);
        std::unique_ptr<VirtualCamera> replacement;
        Check(VirtualCamera::Create(owner->Callbacks(), replacement) == HRESULT_FROM_WIN32(ERROR_BUSY) && !replacement);
        Calls otherCalls; auto other = VirtualCameraTestAccess::Create(*owner.Get(), otherCalls);
        Check(other->Start() == HRESULT_FROM_WIN32(ERROR_BUSY) && otherCalls.starts == 0 && otherCalls.shutdowns == 1);
        calls.shutdownResult = S_OK;
        Check(camera->Close() == E_FAIL && calls.shutdowns == 1 && calls.destroyed == 0);
        Check(camera->Start() == MF_E_SHUTDOWN);
        auto retained = VirtualCameraTestAccess::Observe(*camera);
        camera.reset(); Check(calls.shutdowns == 1 && calls.destroyed == 0);
        retained.Discard(); Check(calls.destroyed == 1);
    }
    void StopDuringOriginalStart()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); Calls calls;
        auto camera = VirtualCameraTestAccess::Create(*owner.Get(), calls); calls.stopDuringStart = camera.get();
        Check(camera->Start() == MF_E_SHUTDOWN && calls.starts == 1 && calls.shutdowns == 1);
        Check(camera->RequireCurrent() == MF_E_SHUTDOWN);
    }
    void RevocationIsTerminal()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); Calls calls;
        auto camera = VirtualCameraTestAccess::Create(*owner.Get(), calls); Check(camera->Start() == S_OK);
        owner->status = E_ACCESSDENIED; Check(camera->RequireCurrent() == E_ACCESSDENIED);
        owner->status = S_OK; Check(camera->RequireCurrent() == MF_E_SHUTDOWN);
        Check(camera->Close() == S_OK && calls.shutdowns == 1);
    }
    void NoOwnerNoOsAction()
    {
        std::unique_ptr<VirtualCamera> camera;
        Check(VirtualCamera::Create({}, camera) == E_INVALIDARG && !camera);
        auto owner = Microsoft::WRL::Make<Owner>(); owner->status = S_FALSE;
        Check(VirtualCamera::Create(owner->Callbacks(), camera) == E_ACCESSDENIED && !camera);
        Calls calls; auto existing = VirtualCameraTestAccess::Create(*owner.Get(), calls);
        auto original = existing.get();
        Check(VirtualCamera::Create({}, existing) == E_INVALIDARG && existing.get() == original);
    }
    void OriginalOwnerLifetime()
    {
        int deaths = 0; Calls calls; calls.shutdownResult = E_FAIL;
        auto owner = Microsoft::WRL::Make<Owner>(); owner->deaths = &deaths;
        auto camera = VirtualCameraTestAccess::Create(*owner.Get(), calls);
        owner.Reset(); Check(deaths == 0 && camera->Start() == S_OK);
        Check(camera->Close() == E_FAIL && deaths == 0 && calls.destroyed == 0);
        auto retained = VirtualCameraTestAccess::Observe(*camera);
        camera.reset(); Check(deaths == 0 && calls.destroyed == 0 && calls.shutdowns == 1);
        retained.Discard(); Check(deaths == 1 && calls.destroyed == 1);
    }
    void ConcurrentStartClose()
    {
        Calls calls;
        struct Event { HANDLE handle = CreateEventW(nullptr, TRUE, FALSE, nullptr); ~Event() { if (handle) CloseHandle(handle); } } entered, resume;
        Check(entered.handle && resume.handle); calls.entered = entered.handle; calls.resume = resume.handle;
        auto owner = Microsoft::WRL::Make<Owner>(); auto camera = VirtualCameraTestAccess::Create(*owner.Get(), calls);
        HRESULT start = E_UNEXPECTED, close = E_UNEXPECTED;
        std::thread starter([&] { start = camera->Start(); });
        const bool waiting = WaitForSingleObject(entered.handle, 5000) == WAIT_OBJECT_0;
        camera->RequestStop();
        std::thread closer([&] { close = camera->Close(); });
        SetEvent(resume.handle); starter.join(); closer.join();
        Check(waiting && start == MF_E_SHUTDOWN && close == S_OK && calls.starts == 1 && calls.shutdowns == 1 && calls.destroyed == 1);
        Check(camera->RequireCurrent() == MF_E_SHUTDOWN);
    }
    void ActualApartmentDenialBeforeCameraApi()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); std::unique_ptr<VirtualCamera> camera;
        Check(VirtualCamera::Create(owner->Callbacks(), camera) == CO_E_NOTINITIALIZED && !camera);
        HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED); Check(hr == S_OK);
        hr = VirtualCamera::Create(owner->Callbacks(), camera);
        CoUninitialize();
        Check(hr == E_ACCESSDENIED && !camera); // No MFStartup, DLL load, camera configuration or registration.
    }
}
int main(int argc, char** argv)
{
    try
    {
        const std::string only = argc == 2 ? std::string(",") + argv[1] + "," : "";
        struct Case { const char* name; void (*run)(); };
        const Case cases[] = {{"virtual-registration-not-ready", RegistrationNotReadiness}, {"virtual-stop-before-start", StopBeforeStart},
            {"virtual-exact-owner", ExactOwnerStatus}, {"virtual-ambiguous-start", AmbiguousStartNoRetry},
            {"virtual-unknown-close", UnknownShutdownRetainsOriginal}, {"virtual-stop-during-start", StopDuringOriginalStart},
            {"virtual-revocation", RevocationIsTerminal}, {"virtual-no-owner", NoOwnerNoOsAction},
            {"virtual-owner-lifetime", OriginalOwnerLifetime}, {"virtual-start-close-race", ConcurrentStartClose},
            {"virtual-apartment-denial", ActualApartmentDenialBeforeCameraApi}};
        int ran = 0;
        for (const auto& test : cases)
            if (only.empty() || only.find(std::string(",") + test.name + ",") != std::string::npos)
            { test.run(); ++ran; std::printf("PASS %s\n", test.name); }
        return ran ? 0 : 87;
    }
    catch (const std::exception& error) { std::fprintf(stderr, "%s\n", error.what()); return 1; }
}
