#pragma once
#include "PhoneCameraPipe.h"
#include <wrl/client.h>
#include <atomic>
#include <cstdint>

namespace Magnolie::PhoneCamera
{
    struct OutputPublisherOwner
    {
        // ORIGINAL authenticated joined native session only, never renderer flags.
        HRESULT (*current)(void*) noexcept;
        HRESULT (*sending)(void*) noexcept;
        void (*retired)(void*, HRESULT) noexcept;
        void* context;
        IUnknown* lifetime = nullptr;
        ULONGLONG (*nowMs)(void*) noexcept = nullptr; // Native test dependency; default host tick clock.
    };
    class OutputPublisher final
    {
    public:
        // Launcher supplies its verified OWN suspended child. Create the pipes,
        // stop event and outer process guardian BEFORE resuming that child.
        // This class does not launch/elevate/terminate any process or install.
        static HRESULT Create(const GUID& originalScope, HANDLE originalOwnedChild,
            OutputPublisherOwner originalOwner, std::unique_ptr<OutputPublisher>& result) noexcept;
        static std::wstring StopName(const GUID& originalScope);
        ~OutputPublisher();
        HRESULT Accept() noexcept;
        HRESULT Publish() noexcept; // One actual original Current/SEND snapshot, no supplied phase flag.
        void Stop() noexcept; // Terminal event/cancellation signal only, no mutex wait.
        bool IsRetired() const noexcept { return retired_.load(); }
    private:
        explicit OutputPublisher(OutputPublisherOwner owner) noexcept : owner_(owner), lifetime_(owner.lifetime) {}
        HRESULT Check() noexcept;
        HRESULT Fail(HRESULT reason) noexcept;
        HRESULT Complete(OVERLAPPED& operation, DWORD limitMs, DWORD& bytes) noexcept;
        ULONGLONG Now() const noexcept;
        const OutputPublisherOwner owner_;
        Microsoft::WRL::ComPtr<IUnknown> lifetime_;
        HANDLE child_ = nullptr, pipe_ = INVALID_HANDLE_VALUE, stop_ = nullptr, completed_ = nullptr;
        std::mutex gate_;
        std::atomic_bool retired_{false}, pending_{false};
        bool connected_ = false;
        unsigned int phase_ = 0;
        std::uint64_t sequence_ = 0;
        ULONGLONG lastNow_ = 0;
#ifdef MAGNOLIE_NATIVE_OUTPUT_PUBLISHER_TESTS
        friend struct OutputPublisherTestAccess; // Observes own pending IO only; no productive test factory.
#endif
    };
}
