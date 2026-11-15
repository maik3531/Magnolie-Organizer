#pragma once
#include <windows.h>
#include <atomic>
#include <cstddef>
#include <memory>
#include <mutex>
#include <string>

namespace Magnolie::PhoneCamera
{
    // Local FrameServer transport primitive, not a phone/SEND authorization.
    // Both arguments come from the original native owner, never renderer input.
    class PipeReader final
    {
    public:
        using Current = HRESULT (*)(void*) noexcept;
        // current is nonblocking/nonreentrant; its context remains alive until
        // the owner has stopped, joined its read task and destroyed this reader.
        static constexpr std::size_t MaxRead = 640 * 480 * 3 / 2 + 4096;
        static std::wstring Name(const GUID& originalSession);
        static HRESULT Connect(const GUID& originalSession, HANDLE originalServerProcess,
            Current current, void* context, std::unique_ptr<PipeReader>& result) noexcept;
        ~PipeReader();
        HRESULT ReadExact(BYTE* target, std::size_t bytes) noexcept;
        void Stop() noexcept;
        bool IsRetired() const noexcept;
    private:
        friend class AudioRender; // Isolated renderer verifies the exact admitted OS parent, never a PID lookup replacement.
        friend class OutputLease; // Nonblocking recheck of the original held control process.
        friend class FrameServerSourceBroker;
        // Only the actual property/capability-authenticated source broker may
        // adopt its already connected overlapped channel; no public handle route.
        static HRESULT AdoptBroker(HANDLE originalPipe, HANDLE originalParent, HANDLE originalStop,
            Current current, void* context, std::unique_ptr<PipeReader>& result) noexcept;
        PipeReader(Current current, void* context) noexcept : current_(current), context_(context) {}
        HRESULT RequireCurrent() noexcept;
        const Current current_;
        void* const context_;
        HANDLE pipe_ = INVALID_HANDLE_VALUE, server_ = nullptr, stop_ = nullptr, completed_ = nullptr;
        std::atomic_bool retired_{false};
        std::mutex reader_;
    };
}
