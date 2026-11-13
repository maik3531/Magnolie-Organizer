#pragma once
#include <windows.h>
#include <wrl/client.h>
#include <atomic>
#include <memory>
#include <mutex>

namespace Magnolie::PhoneCamera
{
    struct VirtualCameraOwner
    {
        // Registration lifetime ONLY, not phone consent/SEND or media readiness.
        // Nonblocking/nonreentrant; may RequestStop, never call Start/Close.
        HRESULT (*current)(void*) noexcept;
        void* context;
        IUnknown* lifetime;
    };

    // Original ordinary-user CurrentUser/Session registration. Never a proof
    // producer, installer, audio-default selector or elevated fallback.
    // Create/Start/Close/destroy on original MTA workers; caller keeps MFStartup/COM alive until
    // this object has been destroyed. No thread impersonation is accepted.
    class VirtualCamera final
    {
    public:
        static HRESULT Create(VirtualCameraOwner original, std::unique_ptr<VirtualCamera>& result) noexcept;
        ~VirtualCamera();
        HRESULT Start() noexcept;
        HRESULT RequireCurrent() noexcept;
        void RequestStop() noexcept { stopped_.store(true); }
        // One original shutdown attempt; failed/unknown shutdown is never retried.
        // A failed Close retains the OS object/lifetime, even if the wrapper is
        // destroyed. The process refuses new registrations after uncertainty.
        HRESULT Close() noexcept;
        // Join all original callers before destruction, as for other native owners.
        VirtualCamera(const VirtualCamera&) = delete;
        VirtualCamera& operator=(const VirtualCamera&) = delete;
    private:
        struct Session
        {
            virtual ~Session() = default;
            virtual HRESULT Start() noexcept = 0;
            virtual HRESULT Shutdown() noexcept = 0;
        };
        struct OsSession;
#ifdef MAGNOLIE_NATIVE_VIRTUAL_CAMERA_TESTS
        friend struct VirtualCameraTestAccess;
        static void ResetFakeUncertainty() noexcept;
#endif
        VirtualCamera(VirtualCameraOwner original, std::unique_ptr<Session> session) noexcept;
        HRESULT CurrentOwner() noexcept;
        HRESULT CloseLocked() noexcept;
        const VirtualCameraOwner owner_;
        Microsoft::WRL::ComPtr<IUnknown> lifetime_;
        std::unique_ptr<Session> session_;
        std::mutex operation_;
        std::atomic_bool stopped_{false}, started_{false};
        bool startAttempted_ = false, closeAttempted_ = false;
        HRESULT closeResult_ = S_OK;
    };
}
