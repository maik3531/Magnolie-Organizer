#pragma once
#include <windows.h>
#include <wrl/client.h>
#include <atomic>
#include <memory>
#include <cstddef>

namespace Magnolie::PhoneCamera
{
    struct FrameServerPeerOwner
    {
        HRESULT (*current)(void*) noexcept;
        void (*retired)(void*, HRESULT) noexcept;
        void* context;
        IUnknown* lifetime = nullptr;
    };

    // Peer admission ONLY. Never capture consent, actual SEND, a scope resolver
    // or endpoint readiness. No arbitrary PID/SID/path enters production Accept.
    class FrameServerPeer final
    {
    public:
        static HRESULT Accept(HANDLE originalConnectedServerPipe, const FrameServerPeerOwner& original,
            std::shared_ptr<FrameServerPeer>& result) noexcept;
        HRESULT RequireCurrent() noexcept;
        // Source-side property handler: actual primary process identity, not a
        // user-provided PID/SID or a successful property return. No SCM start.
        static HRESULT RequireCurrentHost() noexcept;
        void Stop() noexcept;
        ~FrameServerPeer();
        // Pure in-memory policy, not an IPC authority constructor. Actual Accept
        // reads every value from held OS handles; caller metadata cannot use it
        // to create an admitted peer. Groups must be a complete owned token blob.
        static bool AllowsIdentity(PSID user, DWORD session, const TOKEN_GROUPS* groups, std::size_t bytes) noexcept;
    private:
        explicit FrameServerPeer(FrameServerPeerOwner original) noexcept : owner_(original), lifetime_(original.lifetime) {}
        HRESULT Fail(HRESULT reason) noexcept;
        const FrameServerPeerOwner owner_;
        Microsoft::WRL::ComPtr<IUnknown> lifetime_;
        HANDLE pipe_ = INVALID_HANDLE_VALUE, process_ = nullptr;
        DWORD pid_ = 0;
        bool admitted_ = false;
        std::atomic_bool retired_{false};
    };
}
