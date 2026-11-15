#pragma once
#include <windows.h>
#include <wrl/client.h>
#include <atomic>
#include <memory>
#include <mutex>
#include <string>

namespace Magnolie::PhoneCamera
{
    struct BrokerChannelOwner
    {
        HRESULT (*current)(void*) noexcept; // nonblocking/nonreentrant, exactly S_OK
        void* context;
        IUnknown* lifetime;
    };
    // Owned overlapped local transport, NOT FrameServer admission or consent.
    // The broker must additionally authenticate original processes/capability.
    class BrokerChannel final
    {
    public:
        static constexpr DWORD Maximum = 640 * 480 * 3 / 2 + 4096;
        // No GENERIC_WRITE/FILE_CREATE_PIPE_INSTANCE for the service client.
        static constexpr DWORD PipeRights = READ_CONTROL | SYNCHRONIZE | FILE_READ_DATA | FILE_WRITE_DATA | FILE_READ_ATTRIBUTES;
        static constexpr DWORD PipeOwnerRights = FILE_ALL_ACCESS;
        static constexpr DWORD StopReaderRights = READ_CONTROL | SYNCHRONIZE;
        static constexpr DWORD StopOwnerRights = EVENT_ALL_ACCESS;
        static std::wstring Name(const GUID& originalPipe);
        static std::wstring StopName(const GUID& originalPipe);
        static HRESULT CreateStopEvent(const GUID& originalPipe, HANDLE& ownedEvent) noexcept;
        static HRESULT CreateServer(const GUID& originalPipe, BrokerChannelOwner owner, std::unique_ptr<BrokerChannel>& result) noexcept;
        static HRESULT Connect(const GUID& originalPipe, HANDLE heldOriginalParent, BrokerChannelOwner owner,
            std::unique_ptr<BrokerChannel>& result) noexcept;
        HRESULT Accept() noexcept;
        HRESULT Read(BYTE* owned, DWORD size) noexcept;
        HRESULT Write(const BYTE* owned, DWORD size) noexcept;
        void Stop() noexcept;
        ~BrokerChannel(); // Original owner stops/joins all callers first.
        HANDLE Pipe() const noexcept { return pipe_; } // Borrowed, never peer authority by itself.
        HANDLE Peer() const noexcept { return peer_; }
    private:
        explicit BrokerChannel(BrokerChannelOwner owner) noexcept : owner_(owner), lifetime_(owner.lifetime) {}
        HRESULT Initialize() noexcept;
        HRESULT Current() noexcept;
        HRESULT Transfer(bool write, BYTE* bytes, DWORD size) noexcept;
        HRESULT Complete(OVERLAPPED& operation, ULONGLONG start, DWORD& count) noexcept;
        const BrokerChannelOwner owner_;
        Microsoft::WRL::ComPtr<IUnknown> lifetime_;
        HANDLE pipe_ = INVALID_HANDLE_VALUE, peer_ = nullptr, stop_ = nullptr, readDone_ = nullptr, writeDone_ = nullptr;
        std::mutex read_, write_;
        std::atomic_bool stopped_{false};
        bool server_ = false, acceptAttempted_ = false, connected_ = false;
    };
}
