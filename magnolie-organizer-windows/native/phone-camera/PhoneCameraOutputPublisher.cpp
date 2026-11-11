#include "PhoneCameraOutputPublisher.h"
#include <mferror.h>
#include <objbase.h>
#include <sddl.h>
#include <tlhelp32.h>
#include <array>
#include <limits>
#include <vector>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        struct Handle { HANDLE value = nullptr; ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); } };
        struct Local { void* value = nullptr; ~Local() { if (value) LocalFree(value); } };
        bool OwnLiveChild(HANDLE child) noexcept
        {
            if (!child || child == INVALID_HANDLE_VALUE || WaitForSingleObject(child, 0) != WAIT_TIMEOUT) return false;
            const DWORD pid = GetProcessId(child), self = GetCurrentProcessId();
            if (!pid || pid == self) return false;
            Handle snapshot; snapshot.value = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if (snapshot.value == INVALID_HANDLE_VALUE) return false;
            PROCESSENTRY32W entry{}; entry.dwSize = sizeof(entry);
            if (Process32FirstW(snapshot.value, &entry)) do
            {
                if (entry.th32ProcessID == pid) return entry.th32ParentProcessID == self;
            } while (Process32NextW(snapshot.value, &entry));
            return false;
        }
        HRESULT OwnSecurity(Local& security)
        {
            Handle token;
            if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token.value)) return HRESULT_FROM_WIN32(GetLastError());
            DWORD size = 0; GetTokenInformation(token.value, TokenUser, nullptr, 0, &size);
            if (!size || size > 65536) return E_ACCESSDENIED;
            std::vector<BYTE> data(size);
            if (!GetTokenInformation(token.value, TokenUser, data.data(), size, &size)) return HRESULT_FROM_WIN32(GetLastError());
            Local text;
            if (!ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(data.data())->User.Sid, reinterpret_cast<wchar_t**>(&text.value)))
                return HRESULT_FROM_WIN32(GetLastError());
            const std::wstring descriptor = std::wstring(L"D:P(A;;GA;;;SY)(A;;GA;;;") + static_cast<wchar_t*>(text.value) + L")";
            if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(descriptor.c_str(), SDDL_REVISION_1,
                reinterpret_cast<PSECURITY_DESCRIPTOR*>(&security.value), nullptr)) return HRESULT_FROM_WIN32(GetLastError());
            return S_OK;
        }
    }

    std::wstring OutputPublisher::StopName(const GUID& scope)
    {
        wchar_t text[40]{};
        if (scope == GUID_NULL || !StringFromGUID2(scope, text, 40)) return {};
        return std::wstring(L"Local\\Magnolie.PhoneCamera.Stop.") + text;
    }
    HRESULT OutputPublisher::Fail(HRESULT reason) noexcept
    {
        if (!retired_.exchange(true))
        {
            if (stop_) SetEvent(stop_);
            if (pipe_ != INVALID_HANDLE_VALUE) CancelIoEx(pipe_, nullptr); // ONLY this owned outbound pipe.
            owner_.retired(owner_.context, reason);
        }
        return reason;
    }
    void OutputPublisher::Stop() noexcept { Fail(MF_E_SHUTDOWN); }
    ULONGLONG OutputPublisher::Now() const noexcept
    { return owner_.nowMs ? owner_.nowMs(owner_.context) : GetTickCount64(); }
    HRESULT OutputPublisher::Check() noexcept
    {
        if (IsRetired()) return MF_E_SHUTDOWN;
        const HRESULT hr = owner_.current(owner_.context);
        if (hr != S_OK) return Fail(FAILED(hr) ? hr : E_ACCESSDENIED);
        if (child_ && WaitForSingleObject(child_, 0) != WAIT_TIMEOUT) return Fail(HRESULT_FROM_WIN32(ERROR_BROKEN_PIPE));
        return IsRetired() ? MF_E_SHUTDOWN : S_OK;
    }

    HRESULT OutputPublisher::Create(const GUID& scope, HANDLE child, OutputPublisherOwner owner,
        std::unique_ptr<OutputPublisher>& result) noexcept
    {
        if (result || scope == GUID_NULL || !owner.current || !owner.sending || !owner.retired) return E_INVALIDARG;
        if (!OwnLiveChild(child)) return E_ACCESSDENIED;
        try
        {
            std::unique_ptr<OutputPublisher> publisher(new OutputPublisher(owner));
            HRESULT hr = publisher->Check(); if (FAILED(hr)) return hr;
            if (!DuplicateHandle(GetCurrentProcess(), child, GetCurrentProcess(), &publisher->child_,
                SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, 0)) return publisher->Fail(HRESULT_FROM_WIN32(GetLastError()));
            Local security; hr = OwnSecurity(security); if (FAILED(hr)) return publisher->Fail(hr);
            SECURITY_ATTRIBUTES attributes{sizeof(attributes), security.value, FALSE};
            publisher->pipe_ = CreateNamedPipeW(PipeReader::Name(scope).c_str(),
                PIPE_ACCESS_OUTBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE | FILE_FLAG_OVERLAPPED,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, 1, 1024, 1024, 0, &attributes);
            if (publisher->pipe_ == INVALID_HANDLE_VALUE) return publisher->Fail(HRESULT_FROM_WIN32(GetLastError()));
            // A collision is NEVER reset/signaled, not even during failure cleanup.
            SetLastError(ERROR_SUCCESS);
            const HANDLE candidate = CreateEventW(&attributes, TRUE, FALSE, StopName(scope).c_str());
            const DWORD eventError = GetLastError();
            if (!candidate) return publisher->Fail(HRESULT_FROM_WIN32(eventError));
            if (eventError == ERROR_ALREADY_EXISTS) { CloseHandle(candidate); return publisher->Fail(HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)); }
            publisher->stop_ = candidate;
            publisher->completed_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            if (!publisher->completed_) return publisher->Fail(HRESULT_FROM_WIN32(GetLastError()));
            hr = publisher->Check(); if (FAILED(hr)) return hr;
            result = std::move(publisher); return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }

    HRESULT OutputPublisher::Complete(OVERLAPPED& operation, DWORD limitMs, DWORD& bytes) noexcept
    {
        const ULONGLONG deadline = GetTickCount64() + limitMs;
        pending_.store(true);
        HRESULT hr = S_OK;
        for (;;)
        {
            hr = Check(); if (FAILED(hr)) break;
            if (GetTickCount64() >= deadline) { hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT); break; }
            const HANDLE waits[] = {stop_, child_, completed_};
            const DWORD wait = WaitForMultipleObjects(3, waits, FALSE, 10);
            if (wait == WAIT_OBJECT_0 || wait == WAIT_OBJECT_0 + 1) { hr = MF_E_SHUTDOWN; break; }
            if (wait == WAIT_FAILED) { hr = HRESULT_FROM_WIN32(GetLastError()); break; }
            if (wait == WAIT_OBJECT_0 + 2)
            {
                if (!GetOverlappedResult(pipe_, &operation, &bytes, FALSE)) hr = HRESULT_FROM_WIN32(GetLastError());
                pending_.store(false); return hr;
            }
        }
        CancelIoEx(pipe_, &operation);
        DWORD ignored = 0; GetOverlappedResult(pipe_, &operation, &ignored, TRUE); // Drain ONLY this owned operation.
        pending_.store(false); return hr;
    }

    HRESULT OutputPublisher::Accept() noexcept
    {
        try
        {
            std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
            if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
            HRESULT hr = Check(); if (FAILED(hr)) return hr;
            if (connected_) return Fail(E_INVALIDARG);
            ResetEvent(completed_); OVERLAPPED operation{}; operation.hEvent = completed_;
            if (!ConnectNamedPipe(pipe_, &operation))
            {
                const DWORD error = GetLastError();
                if (error == ERROR_IO_PENDING) { DWORD ignored = 0; hr = Complete(operation, 2000, ignored); }
                else if (error != ERROR_PIPE_CONNECTED) hr = HRESULT_FROM_WIN32(error);
            }
            if (FAILED(hr)) return Fail(hr);
            ULONG actual = 0;
            if (!GetNamedPipeClientProcessId(pipe_, &actual)) return Fail(HRESULT_FROM_WIN32(GetLastError()));
            if (!actual || actual != GetProcessId(child_)) return Fail(E_ACCESSDENIED);
            hr = Check(); if (FAILED(hr)) return hr;
            connected_ = true; return S_OK;
        }
        catch (...) { return Fail(E_FAIL); }
    }

    HRESULT OutputPublisher::Publish() noexcept
    {
        try
        {
            std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
            if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
            HRESULT hr = Check(); if (FAILED(hr)) return hr;
            if (!connected_ || sequence_ >= static_cast<std::uint64_t>((std::numeric_limits<LONGLONG>::max)())) return Fail(E_INVALIDARG);
            const HRESULT sending = owner_.sending(owner_.context);
            unsigned int phase = 0;
            if (sending == S_OK && phase_) phase = 2;
            else if (sending == E_ACCESSDENIED && phase_ != 2) phase = 1;
            else return Fail(FAILED(sending) ? sending : E_ACCESSDENIED);
            const ULONGLONG now = Now();
            if (now < lastNow_ || now > (std::numeric_limits<ULONGLONG>::max)() - 250) return Fail(E_INVALIDARG);
            const ULONGLONG until = now + 250;
            std::array<BYTE, 18> record{};
            struct Clear { BYTE* data; std::size_t size; ~Clear() { SecureZeroMemory(data, size); } } clear{record.data(), record.size()};
            record[0] = 1; record[1] = static_cast<BYTE>(phase);
            for (unsigned int i = 0; i < 8; ++i)
            { record[2 + i] = static_cast<BYTE>(sequence_ >> (56 - 8 * i)); record[10 + i] = static_cast<BYTE>(until >> (56 - 8 * i)); }
            ResetEvent(completed_); OVERLAPPED operation{}; operation.hEvent = completed_; DWORD bytes = 0;
            if (!WriteFile(pipe_, record.data(), static_cast<DWORD>(record.size()), &bytes, &operation))
            {
                const DWORD error = GetLastError();
                hr = error == ERROR_IO_PENDING ? Complete(operation, 50, bytes) : HRESULT_FROM_WIN32(error);
            }
            if (FAILED(hr)) return Fail(hr);
            if (bytes != record.size()) return Fail(E_UNEXPECTED);
            hr = Check(); if (FAILED(hr)) return hr;
            const ULONGLONG after = Now();
            if (after < now || after >= until) return Fail(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
            if (phase == 2 && owner_.sending(owner_.context) != S_OK) return Fail(E_ACCESSDENIED);
            phase_ = phase; lastNow_ = after; ++sequence_; return S_OK;
        }
        catch (...) { return Fail(E_FAIL); }
    }
    OutputPublisher::~OutputPublisher()
    {
        Stop();
        // Original owner signals and joins its publisher worker before destruction.
        std::lock_guard<std::mutex> lock(gate_);
        if (pipe_ != INVALID_HANDLE_VALUE) CloseHandle(pipe_);
        if (completed_) CloseHandle(completed_);
        if (stop_) CloseHandle(stop_);
        if (child_) CloseHandle(child_);
    }
}
