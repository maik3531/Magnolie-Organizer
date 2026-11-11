#pragma once
#include "PhoneCameraPipe.h"
#include "PhoneCameraClock.h"
#include <cstdint>
#include <wrl/client.h>

namespace Magnolie::PhoneCamera
{
    struct OutputLeaseOwner
    {
        // Nonblocking original JOINED retirement, never a replacement session.
        void (*retired)(void*, HRESULT) noexcept;
        void* context;
        IUnknown* lifetime = nullptr;
        // Native test dependency only; nullptr uses host GetTickCount64.
        ULONGLONG (*nowMs)(void*) noexcept = nullptr;
    };

    // Original parent control channel only; not phone permission or a SEND owner.
    // Its PipeReader guard validates bootstrap/parent liveness and MUST NOT call
    // back into this lease. Parent may publish only from the original live joined
    // session, and must withdraw/kill its owned worker immediately on retirement.
    class OutputLease final
    {
    public:
        static constexpr std::size_t RecordBytes = 18;
        static HRESULT Create(std::unique_ptr<PipeReader>& originalControl,
            OutputLeaseOwner originalOwner, std::unique_ptr<OutputLease>& result) noexcept;
        ~OutputLease();
        HRESULT ReceiveOne() noexcept;
        HRESULT RequireCurrent() noexcept;
        HRESULT RequireSending() noexcept;
        void Stop() noexcept;
        bool IsRetired() const noexcept;
        // Actual control-backed callbacks, not a caller-supplied readiness grant.
        // This lease must outlive every clock/renderer using the borrowed context.
        ClockOwner Callbacks() noexcept;
        // Borrow only while this owner remains alive and all its workers joined.
        PipeReader* Control() const noexcept { return reader_.get(); }
    private:
        explicit OutputLease(OutputLeaseOwner owner) noexcept : owner_(owner), lifetime_(owner.lifetime) {}
        HRESULT Fail(HRESULT reason) noexcept;
        ULONGLONG Now() const noexcept;
        const OutputLeaseOwner owner_;
        Microsoft::WRL::ComPtr<IUnknown> lifetime_;
        std::unique_ptr<PipeReader> reader_;
        std::mutex receive_;
        std::uint64_t sequence_ = 0;
        std::atomic_bool retired_{false};
        std::atomic<unsigned int> phase_{0}; // 0 unprepared, 1 prepare, 2 SEND, 3 terminal.
        std::atomic<ULONGLONG> until_{0}, receivedAt_{0};
    };
}
