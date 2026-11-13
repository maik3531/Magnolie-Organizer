#pragma once
#include "PhoneCameraVirtualCamera.h"
#include "PhoneCameraOutputPublisher.h"
#include <thread>

namespace Magnolie::PhoneCamera
{
    struct SourceBrokerOwner
    {
        OutputPublisherOwner output; // Exact original joined OutputAuthority.
        HRESULT (*exportAnchor)(void*, BYTE*, DWORD) noexcept;
    };
    // Actual original manager -> OS property -> kernel FrameServer peer ->
    // private capability -> source control lease. Binding is NOT video Ready.
    class SourceBrokerParent final
    {
    public:
        static HRESULT Prepare(const GUID& originalScope, std::shared_ptr<VirtualCamera> originalCamera,
            SourceBrokerOwner originalOwner, std::unique_ptr<SourceBrokerParent>& result) noexcept;
        HRESULT RequireBound() noexcept; // Native binding accounting only.
        HRESULT WriteVideo(const BYTE* actuallyAdmittedRecord, DWORD bytes) noexcept;
        void Stop() noexcept;
        HRESULT Close() noexcept; // Stop + join + original Source cleanup ACK.
        // Original owner joins callers before destruction; callbacks may Stop,
        // never Close/destroy/reenter this object or block waiting for the worker.
        ~SourceBrokerParent();
        SourceBrokerParent(const SourceBrokerParent&) = delete;
        SourceBrokerParent& operator=(const SourceBrokerParent&) = delete;
    private:
        struct Hold;
        explicit SourceBrokerParent(std::unique_ptr<Hold> hold) noexcept;
        static HRESULT TransportCurrent(void*) noexcept;
        static void PeerRetired(void*, HRESULT) noexcept;
        HRESULT CaptureCurrent() noexcept;
        HRESULT Fail(HRESULT reason) noexcept;
        HRESULT PublishLease() noexcept; // Caller holds transmit_.
        HRESULT PollReceipt() noexcept;
        void Run() noexcept;
        std::unique_ptr<Hold> hold_;
        std::thread worker_;
        std::mutex transmit_, close_;
        std::atomic_bool stopped_{false}, bound_{false}, sourceClosed_{false}, leaseAttempted_{false};
        bool closeAttempted_ = false, anchorSent_ = false;
        HRESULT closeResult_ = S_OK;
        unsigned int phase_ = 0;
        std::uint64_t sequence_ = 0;
        ULONGLONG lastTick_ = 0;
    };
}
