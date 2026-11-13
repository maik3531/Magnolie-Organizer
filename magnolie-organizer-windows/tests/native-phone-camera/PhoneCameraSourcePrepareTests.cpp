#include "../../native/phone-camera/PhoneCameraSource.h"
#include <mfapi.h>
#include <mferror.h>
#include <wrl.h>
#include <atomic>
#include <cstdio>
#include <stdexcept>

using namespace Magnolie::PhoneCamera;
namespace
{
    void Check(bool condition) { if (!condition) throw std::runtime_error("source preparation assertion"); }
    struct Owner final : Microsoft::WRL::RuntimeClass<Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, IUnknown>
    {
        std::atomic<HRESULT> current{S_OK}, sending{E_ACCESSDENIED}, reason{S_OK};
        HANDLE sent = CreateEventW(nullptr, TRUE, FALSE, nullptr), retired = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        ~Owner() { if (sent) CloseHandle(sent); if (retired) CloseHandle(retired); }
        static HRESULT Current(void* context) noexcept { return static_cast<Owner*>(context)->current.load(); }
        static HRESULT Sending(void* context) noexcept
        {
            auto& self = *static_cast<Owner*>(context); HRESULT hr = self.sending.load();
            if (hr == S_OK) SetEvent(self.sent);
            return hr;
        }
        static void Retired(void* context, HRESULT failure) noexcept
        { auto& self = *static_cast<Owner*>(context); self.reason.store(failure); SetEvent(self.retired); }
    };
    struct Fixture
    {
        Microsoft::WRL::ComPtr<Owner> owner = Microsoft::WRL::Make<Owner>();
        Microsoft::WRL::ComPtr<IMFMediaSourceEx> source;
        Microsoft::WRL::ComPtr<IFrameFeed> feed;
        Fixture()
        {
            Check(owner && owner->sent && owner->retired);
            Check(CreateSource({Owner::Current, Owner::Sending, Owner::Retired, owner.Get(), owner.Get()}, &source, &feed) == S_OK);
            Microsoft::WRL::ComPtr<IMFPresentationDescriptor> descriptor;
            Check(source->CreatePresentationDescriptor(&descriptor) == S_OK);
            PROPVARIANT start{}; start.vt = VT_EMPTY;
            Check(source->Start(descriptor.Get(), &GUID_NULL, &start) == S_OK);
        }
        ~Fixture() { if (source) source->Shutdown(); }
        HRESULT Current() { DWORD flags = 0; return source->GetCharacteristics(&flags); }
    };
    void PreparationOutlivesMediaGrace()
    {
        Fixture f;
        Sleep(5300); // Actual original MF timer; no registration/camera/audio/phone.
        Check(f.Current() == S_OK && WaitForSingleObject(f.owner->retired, 0) == WAIT_TIMEOUT);
    }
    void ActualSendStillTimesOutAtOriginalLimit()
    {
        Fixture f; f.owner->sending.store(S_OK);
        Check(WaitForSingleObject(f.owner->sent, 1000) == WAIT_OBJECT_0);
        Check(WaitForSingleObject(f.owner->retired, 5400) == WAIT_OBJECT_0);
        Check(f.owner->reason.load() == MF_E_NET_TIMEOUT && f.Current() == MF_E_SHUTDOWN);
    }
    void PositiveStatusIsNotPreparation()
    {
        Fixture f; f.owner->sending.store(S_FALSE);
        Check(WaitForSingleObject(f.owner->retired, 1000) == WAIT_OBJECT_0 && f.owner->reason.load() == E_ACCESSDENIED);
        f.owner->sending.store(S_OK); Check(f.Current() == MF_E_SHUTDOWN);
    }
    void OriginalPermissionStillRetiresDuringPreparation()
    {
        Fixture f; f.owner->current.store(E_ACCESSDENIED);
        Check(WaitForSingleObject(f.owner->retired, 1000) == WAIT_OBJECT_0 && f.owner->reason.load() == E_ACCESSDENIED);
        f.owner->current.store(S_OK); Check(f.Current() == MF_E_SHUTDOWN);
    }
}
int main()
{
    HRESULT com = CoInitializeEx(nullptr, COINIT_MULTITHREADED); if (FAILED(com)) return 1;
    HRESULT mf = MFStartup(MF_VERSION, MFSTARTUP_LITE); if (FAILED(mf)) { CoUninitialize(); return 1; }
    int result = 0;
    try
    {
        PreparationOutlivesMediaGrace(); std::puts("PASS source-prepare-before-send-no-media-timeout");
        ActualSendStillTimesOutAtOriginalLimit(); std::puts("PASS source-prepare-actual-send-original-five-second-limit");
        PositiveStatusIsNotPreparation(); std::puts("PASS source-prepare-positive-authority-status-denied");
        OriginalPermissionStillRetiresDuringPreparation(); std::puts("PASS source-prepare-original-revocation-terminal");
    }
    catch (const std::exception& error) { std::fprintf(stderr, "%s\n", error.what()); result = 1; }
    MFShutdown(); CoUninitialize(); return result;
}
