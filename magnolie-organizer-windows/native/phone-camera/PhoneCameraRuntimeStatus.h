#pragma once
#include "PhoneCameraRuntimeProcess.h"

namespace Magnolie::PhoneCamera
{
    // Parent-side independent inbound channel; control lease publication keeps
    // running while this waits. Only the held verified runtime child may report.
    // Status data is NOT permission or proof of endpoint IO by itself: the actual
    // packaged worker must emit Ready only after Open and Done only after Write.
    class RuntimeStatus final
    {
    public:
        static constexpr std::size_t RecordBytes = 18;
        static std::wstring Name(const GUID& originalControlScope);
        static HRESULT Create(const GUID& originalControlScope, RuntimeProcess* originalRuntime,
            std::unique_ptr<RuntimeStatus>& result) noexcept;
        ~RuntimeStatus();
        HRESULT WaitPrepared() noexcept;
        HRESULT WaitWritten(ULONGLONG originalOperationToken) noexcept;
        void Stop() noexcept;
    private:
        explicit RuntimeStatus(RuntimeProcess* runtime) noexcept : runtime_(runtime) {}
        HRESULT Check() noexcept;
        HRESULT Fail(HRESULT reason) noexcept;
        HRESULT Complete(OVERLAPPED& operation, ULONGLONG deadline, DWORD& bytes) noexcept;
        HRESULT Accept() noexcept;
        HRESULT Record(BYTE phase, ULONGLONG token, DWORD limitMs) noexcept;
        RuntimeProcess* const runtime_; // Original owner outlives this reader and joins its task first.
        HANDLE pipe_ = INVALID_HANDLE_VALUE, stop_ = nullptr, completed_ = nullptr;
        std::mutex gate_;
        std::atomic_bool stopped_{false}, pending_{false};
        bool accepted_ = false, prepared_ = false;
        ULONGLONG sequence_ = 0;
#ifdef MAGNOLIE_NATIVE_RUNTIME_STATUS_TESTS
        friend struct RuntimeStatusTestAccess;
#endif
    };
}
