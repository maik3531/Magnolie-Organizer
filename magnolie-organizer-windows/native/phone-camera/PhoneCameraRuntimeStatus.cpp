#include "PhoneCameraRuntimeStatus.h"
#include <mferror.h>
#include <objbase.h>
#include <sddl.h>
#include <limits>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        HRESULT Error() noexcept { return HRESULT_FROM_WIN32(GetLastError()); }
        struct Local { void* value = nullptr; ~Local() { if (value) LocalFree(value); } };
        struct Handle { HANDLE value = nullptr; ~Handle() { if (value) CloseHandle(value); } };
        HRESULT Security(Local& descriptor)
        {
            Handle token; if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token.value)) return Error();
            DWORD bytes = 0; GetTokenInformation(token.value, TokenUser, nullptr, 0, &bytes);
            if (!bytes || bytes > 65536) return E_ACCESSDENIED;
            std::vector<BYTE> buffer(bytes);
            if (!GetTokenInformation(token.value, TokenUser, buffer.data(), bytes, &bytes)) return Error();
            Local sid;
            if (!ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(buffer.data())->User.Sid, reinterpret_cast<wchar_t**>(&sid.value))) return Error();
            const std::wstring sddl = std::wstring(L"D:P(A;;GA;;;SY)(A;;GA;;;") + static_cast<wchar_t*>(sid.value) + L")";
            if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1,
                reinterpret_cast<PSECURITY_DESCRIPTOR*>(&descriptor.value), nullptr)) return Error();
            return S_OK;
        }
    }
    std::wstring RuntimeStatus::Name(const GUID& scope)
    {
        wchar_t text[40]{};
        if (scope == GUID_NULL || !StringFromGUID2(scope, text, 40)) return {};
        return std::wstring(L"\\\\.\\pipe\\Magnolie.PhoneCamera.Status.") + text;
    }
    HRESULT RuntimeStatus::Create(const GUID& scope, RuntimeProcess* runtime, std::unique_ptr<RuntimeStatus>& result) noexcept
    {
        if (result || scope == GUID_NULL || !runtime) return E_INVALIDARG;
        try
        {
            HRESULT hr = runtime->Check(); if (FAILED(hr)) return hr;
            std::unique_ptr<RuntimeStatus> status(new RuntimeStatus(runtime));
            Local descriptor; hr = Security(descriptor); if (FAILED(hr)) return status->Fail(hr);
            SECURITY_ATTRIBUTES attributes{sizeof(attributes), descriptor.value, FALSE};
            status->pipe_ = CreateNamedPipeW(Name(scope).c_str(), PIPE_ACCESS_INBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE | FILE_FLAG_OVERLAPPED,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, 1, 1024, 1024, 0, &attributes);
            if (status->pipe_ == INVALID_HANDLE_VALUE) return status->Fail(Error());
            status->stop_ = CreateEventW(nullptr, TRUE, FALSE, nullptr); status->completed_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            if (!status->stop_ || !status->completed_) return status->Fail(Error());
            result = std::move(status); return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    void RuntimeStatus::Stop() noexcept
    {
        if (!stopped_.exchange(true))
        {
            if (stop_) SetEvent(stop_);
            if (pipe_ != INVALID_HANDLE_VALUE) CancelIoEx(pipe_, nullptr);
            runtime_->Stop();
        }
    }
    HRESULT RuntimeStatus::Fail(HRESULT reason) noexcept { Stop(); return reason; }
    HRESULT RuntimeStatus::Check() noexcept
    {
        if (stopped_.load()) return MF_E_SHUTDOWN;
        const HRESULT hr = runtime_->Check();
        if (FAILED(hr)) return Fail(hr);
        return stopped_.load() ? MF_E_SHUTDOWN : S_OK;
    }
    HRESULT RuntimeStatus::Complete(OVERLAPPED& operation, ULONGLONG deadline, DWORD& bytes) noexcept
    {
        pending_.store(true); HRESULT hr = S_OK;
        for (;;)
        {
            hr = Check(); if (FAILED(hr)) break;
            if (GetTickCount64() >= deadline) { hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT); break; }
            const HANDLE waits[] = {stop_, runtime_->Child(), completed_};
            const DWORD wait = WaitForMultipleObjects(3, waits, FALSE, 10);
            if (wait == WAIT_OBJECT_0 || wait == WAIT_OBJECT_0 + 1) { hr = MF_E_SHUTDOWN; break; }
            if (wait == WAIT_FAILED) { hr = Error(); break; }
            if (wait == WAIT_OBJECT_0 + 2)
            {
                if (!GetOverlappedResult(pipe_, &operation, &bytes, FALSE)) hr = Error();
                pending_.store(false); return hr;
            }
        }
        CancelIoEx(pipe_, &operation); DWORD ignored = 0; GetOverlappedResult(pipe_, &operation, &ignored, TRUE);
        pending_.store(false); return hr;
    }
    HRESULT RuntimeStatus::Accept() noexcept
    {
        HRESULT hr = Check(); if (FAILED(hr)) return hr;
        if (accepted_) return S_OK;
        ResetEvent(completed_); OVERLAPPED operation{}; operation.hEvent = completed_;
        if (!ConnectNamedPipe(pipe_, &operation))
        {
            const DWORD error = GetLastError();
            if (error == ERROR_IO_PENDING) { DWORD ignored = 0; hr = Complete(operation, GetTickCount64() + 2000, ignored); }
            else if (error != ERROR_PIPE_CONNECTED) hr = HRESULT_FROM_WIN32(error);
        }
        if (FAILED(hr)) return Fail(hr);
        ULONG actual = 0;
        if (!GetNamedPipeClientProcessId(pipe_, &actual)) return Fail(Error());
        if (!actual || actual != GetProcessId(runtime_->Child())) return Fail(E_ACCESSDENIED);
        hr = Check(); if (FAILED(hr)) return hr;
        accepted_ = true; return S_OK;
    }
    HRESULT RuntimeStatus::Record(BYTE phase, ULONGLONG token, DWORD limitMs) noexcept
    {
        HRESULT hr = Check(); if (FAILED(hr)) return hr;
        const ULONGLONG deadline = GetTickCount64() + limitMs;
        hr = Accept(); if (FAILED(hr)) return hr;
        std::array<BYTE, RecordBytes> record{};
        struct Clear { BYTE* data; std::size_t size; ~Clear() { SecureZeroMemory(data, size); } } clear{record.data(), record.size()};
        DWORD offset = 0;
        while (offset < record.size())
        {
            hr = Check(); if (FAILED(hr)) return hr;
            if (GetTickCount64() >= deadline) return Fail(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
            ResetEvent(completed_); OVERLAPPED operation{}; operation.hEvent = completed_; DWORD bytes = 0;
            if (!ReadFile(pipe_, record.data() + offset, static_cast<DWORD>(record.size()) - offset, &bytes, &operation))
            {
                const DWORD error = GetLastError();
                hr = error == ERROR_IO_PENDING ? Complete(operation, deadline, bytes) : HRESULT_FROM_WIN32(error);
            }
            if (FAILED(hr)) return Fail(hr);
            if (!bytes || bytes > record.size() - offset) return Fail(E_UNEXPECTED);
            offset += bytes;
        }
        ULONGLONG sequence = 0, actualToken = 0;
        for (unsigned int i = 0; i < 8; ++i) { sequence = (sequence << 8) | record[2 + i]; actualToken = (actualToken << 8) | record[10 + i]; }
        if (record[0] != 1 || record[1] != phase || sequence != sequence_ || actualToken != token ||
            sequence_ >= static_cast<ULONGLONG>((std::numeric_limits<LONGLONG>::max)())) return Fail(E_INVALIDARG);
        hr = Check(); if (FAILED(hr)) return hr;
        if (GetTickCount64() >= deadline) return Fail(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
        ++sequence_; return S_OK;
    }
    HRESULT RuntimeStatus::WaitPrepared() noexcept
    {
        std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
        if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
        if (prepared_) return Fail(E_INVALIDARG);
        HRESULT hr = Record(1, 0, 10000); if (FAILED(hr)) return hr;
        hr = runtime_->CompletePreparation(); if (FAILED(hr)) return Fail(hr);
        prepared_ = true; return S_OK;
    }
    HRESULT RuntimeStatus::WaitWritten(ULONGLONG token) noexcept
    {
        std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
        if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
        if (!prepared_ || !token) return Fail(E_INVALIDARG);
        HRESULT hr = Record(2, token, 250); if (FAILED(hr)) return hr;
        hr = runtime_->CompleteOperation(token); return FAILED(hr) ? Fail(hr) : S_OK;
    }
    RuntimeStatus::~RuntimeStatus()
    {
        Stop(); std::lock_guard<std::mutex> lock(gate_);
        if (pipe_ != INVALID_HANDLE_VALUE) CloseHandle(pipe_);
        if (stop_) CloseHandle(stop_);
        if (completed_) CloseHandle(completed_);
    }
}
