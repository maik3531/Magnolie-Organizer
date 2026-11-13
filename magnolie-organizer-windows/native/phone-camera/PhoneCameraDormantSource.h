#pragma once
#include "PhoneCameraSource.h"

namespace Magnolie::PhoneCamera
{
    class FrameServerSourceBroker;
    struct DormantSourceState;
    class DormantSourceControl;

    // Registration/module lifetime ONLY. Never Current/SEND capture authority.
    // Nonblocking, nonreentrant callback; lifetime must actually own context.
    struct RegistrationLifetime
    {
        HRESULT (*current)(void*) noexcept;
        void* context;
        IUnknown* lifetime;
        // Terminal registration cleanup, NOT capture retirement. Invoked once
        // outside shell locks; may release the owner's native controller.
        void (*closed)(void*) noexcept = nullptr;
    };

    // No productive caller can construct a proof from metadata or callbacks.
    // The future trusted broker must verify the actual original registration,
    // kernel peer, capability and lease BEFORE using this private constructor.
    class SourceBindingProof final
    {
    public:
        ~SourceBindingProof() = default;
        SourceBindingProof(const SourceBindingProof&) = delete;
        SourceBindingProof& operator=(const SourceBindingProof&) = delete;
    private:
        friend class FrameServerSourceBroker;
        friend class DormantSourceControl;
#ifdef MAGNOLIE_NATIVE_DORMANT_SOURCE_TESTS
        friend struct DormantSourceTestAccess;
#endif
        SourceBindingProof(const DormantSourceControl& exactTarget, SourceOwner owner,
            const GUID& originalScope, std::shared_ptr<PresentationClock> originalClock);
        const std::shared_ptr<const BYTE> target_;
        const SourceOwner owner_;
        const Microsoft::WRL::ComPtr<IUnknown> lifetime_;
        const GUID scope_;
        const std::shared_ptr<PresentationClock> clock_;
    };

    // Native in-process controller, not a marshalled COM/renderer interface.
    // Stop may race adoption. It never waits for a broker or starts device IO.
    // The owner must join its adoption/delegated calls before destroying control.
    class DormantSourceControl final
    {
    public:
        HRESULT Adopt(std::unique_ptr<SourceBindingProof> proof) noexcept;
        HRESULT RequireBound() noexcept;
        HRESULT GetBoundFeed(IFrameFeed** result) noexcept;
        HRESULT Stop() noexcept;
        ~DormantSourceControl();
        DormantSourceControl(const DormantSourceControl&) = delete;
        DormantSourceControl& operator=(const DormantSourceControl&) = delete;
    private:
        friend class SourceBindingProof;
        friend HRESULT CreateDormantSource(RegistrationLifetime, IMFMediaSourceEx**,
            std::unique_ptr<DormantSourceControl>&, IMFAttributes*) noexcept;
        explicit DormantSourceControl(std::shared_ptr<DormantSourceState> state) : state_(std::move(state)) {}
        const std::shared_ptr<DormantSourceState> state_;
    };

    // Returns an unregistered, dormant MF object and its own native controller.
    // Static metadata is available; presentation/events/Start/feed require the
    // genuine one-time binding. This function never grants capture or SEND.
    HRESULT CreateDormantSource(RegistrationLifetime registration, IMFMediaSourceEx** source,
        std::unique_ptr<DormantSourceControl>& control, IMFAttributes* activationMetadata = nullptr) noexcept;
}
