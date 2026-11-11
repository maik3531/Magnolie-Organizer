#pragma once
#include <windows.h>
#include <unknwn.h>
#include <wrl/client.h>
#include <array>
#include <atomic>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace Magnolie::PhoneCamera
{
    class RuntimeImage final
    {
    public:
        static constexpr wchar_t Filename[] = L"Magnolie.PhoneAudioWorker.x64.exe";
        // Digest MUST come from the immutable original application payload, not
        // an external manifest, user setting, command line or downloaded file.
        // Only this fixed sibling, protected ACLs and held non-reparse paths.
        static HRESULT VerifySibling(const std::array<BYTE, 32>& originalPayloadDigest,
            std::shared_ptr<RuntimeImage>& result) noexcept;
        ~RuntimeImage();
        RuntimeImage(const RuntimeImage&) = delete;
        RuntimeImage& operator=(const RuntimeImage&) = delete;
    private:
        RuntimeImage() = default;
        HRESULT Hold(const std::wstring& path, bool directory, bool acl);
        std::wstring path_, directory_;
        std::vector<HANDLE> files_;
        friend class RuntimeProcess;
#ifdef MAGNOLIE_NATIVE_RUNTIME_PROCESS_TESTS
        friend struct RuntimeProcessTestAccess; // Fixed own test executable only, absent in production.
#endif
    };
    struct RuntimeProcessOwner
    {
        // Original authenticated joined owner; callbacks never block or destroy
        // the process/context. Retirement may signal idempotent Stop.
        HRESULT (*current)(void*) noexcept;
        void (*retired)(void*, HRESULT) noexcept;
        void* context;
        IUnknown* lifetime = nullptr;
    };
    class RuntimeProcess final
    {
    public:
        // Creates only its verified image, SUSPENDED, with an independent guard
        // and own kill-on-close job BEFORE any guest/native worker instruction.
        static HRESULT Create(const std::shared_ptr<RuntimeImage>& originalImage,
            const GUID& control, const GUID& audio, const GUID& anchor,
            RuntimeProcessOwner originalOwner, std::unique_ptr<RuntimeProcess>& result) noexcept;
        ~RuntimeProcess();
        HANDLE Child() const noexcept { return process_; } // Borrow for exact-peer publisher only; never reopen by PID.
        HRESULT Resume() noexcept; // Caller has established pipes/stop channel; does not report device readiness.
        HRESULT CompletePreparation() noexcept; // Actual trusted readiness protocol must finish first; no authority grant.
        HRESULT BeginOperation(ULONGLONG* token) noexcept;
        HRESULT CompleteOperation(ULONGLONG originalToken) noexcept;
        void Stop() noexcept; // Signals only, does not wait for COM/process exit or take command mutex.
        bool IsRetired() const noexcept { return retired_.load(); }
        HRESULT WaitStopped(DWORD limitMs) noexcept;
    private:
        explicit RuntimeProcess(RuntimeProcessOwner owner) noexcept : owner_(owner), lifetime_(owner.lifetime) {}
        HRESULT Check() noexcept;
        HRESULT Fail(HRESULT reason) noexcept;
        void Guard() noexcept;
        const RuntimeProcessOwner owner_;
        Microsoft::WRL::ComPtr<IUnknown> lifetime_;
        std::shared_ptr<RuntimeImage> image_;
        HANDLE process_ = nullptr, thread_ = nullptr, job_ = nullptr, stop_ = nullptr, finished_ = nullptr;
        std::thread guard_;
        std::mutex gate_;
        std::atomic_bool retired_{false}, exitConfirmed_{false};
        std::atomic<ULONGLONG> deadline_{0};
        bool resumed_ = false, prepared_ = false;
        ULONGLONG nextToken_ = 1, operation_ = 0;
#ifdef MAGNOLIE_NATIVE_RUNTIME_PROCESS_TESTS
        friend struct RuntimeProcessTestAccess;
#endif
    };
}
