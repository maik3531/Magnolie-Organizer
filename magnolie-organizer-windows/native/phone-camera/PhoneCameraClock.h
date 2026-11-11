#pragma once
#include <windows.h>
#include <unknwn.h>
#include <wrl/client.h>
#include <atomic>
#include <cstddef>
#include <mutex>

namespace Magnolie::PhoneCamera
{
    struct ClockOwner
    {
        HRESULT (*current)(void*) noexcept;
        HRESULT (*sending)(void*) noexcept;
        void (*retired)(void*, HRESULT) noexcept;
        void* context;
        IUnknown* lifetime = nullptr;
        // Native dependency injection only; nullptr selects MFGetSystemTime.
        LONGLONG (*nowUs)(void*) noexcept = nullptr;
    };

    // One instance per ORIGINAL joined AV owner, shared by both tracks, never
    // per source/client/track. Not a consent grant, packet validator or scheduler.
    // Callbacks are nonblocking and valid through destruction; they may signal
    // idempotent Stop, but MUST NOT reenter Map or destroy this clock/context.
    // upstream retains authenticated sequence/PTS checks, downstream must wait
    // until presentation time and recheck original authority before native IO.
    class PresentationClock final
    {
    public:
        explicit PresentationClock(ClockOwner owner) noexcept;
        ~PresentationClock();
        HRESULT Map(LONGLONG originalPtsUs, LONGLONG* nativePtsUs) noexcept;
        static constexpr std::size_t AnchorBytes = 33;
        // Original mapper exports only AFTER its first admitted frame. Deliver
        // the SAME immutable record to both native tracks through the admitted
        // original process/broker boundary, never untrusted metadata/attributes.
        HRESULT ExportAnchor(const GUID& originalScope, BYTE* record, std::size_t size) noexcept;
        // One-time import BEFORE any local mapping. Receipt time is only a
        // rollback check; it NEVER replaces either original anchor coordinate.
        // This data is not Current/SEND authority or a scheduling/readiness grant.
        HRESULT ImportAnchor(const GUID& originalScope, const BYTE* record, std::size_t size) noexcept;
        void Stop() noexcept; // Nonblocking signal, including from an owner callback.
    private:
        HRESULT Check() noexcept;
        HRESULT Retire(HRESULT reason) noexcept;
        ClockOwner owner_;
        Microsoft::WRL::ComPtr<IUnknown> lifetime_;
        std::mutex gate_;
        std::atomic_bool retired_{false};
        bool anchored_ = false, imported_ = false;
        GUID anchorScope_ = GUID_NULL;
        LONGLONG remoteAnchor_ = 0, nativeAnchor_ = 0, lastNow_ = 0;
    };
}
