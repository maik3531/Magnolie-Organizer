#include "PhoneCameraBrokerChannel.h"
#include <sddl.h>
#include <objbase.h>
#include <vector>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        HRESULT Error() noexcept { return HRESULT_FROM_WIN32(GetLastError()); }
        struct Handle { HANDLE value = nullptr; ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); } };
        struct Local { void* value = nullptr; ~Local() { if (value) LocalFree(value); } };
        HRESULT OriginalUserPipeSecurity(Local& descriptor, bool stopEvent = false) noexcept
        {
            Handle thread;
            if (OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, TRUE, &thread.value)) return E_ACCESSDENIED;
            if (GetLastError() != ERROR_NO_TOKEN) return Error();
            Handle token;
            if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token.value)) return Error();
            TOKEN_ELEVATION elevation{}; DWORD length = 0, session = 0;
            if (!GetTokenInformation(token.value, TokenElevation, &elevation, sizeof(elevation), &length) ||
                !GetTokenInformation(token.value, TokenSessionId, &session, sizeof(session), &length)) return Error();
            if (elevation.TokenIsElevated || !session) return E_ACCESSDENIED;
            DWORD size = 0; GetTokenInformation(token.value, TokenUser, nullptr, 0, &size);
            if (size < sizeof(TOKEN_USER) || size > 65536) return E_ACCESSDENIED;
            try
            {
                std::vector<BYTE> bytes(size);
                if (!GetTokenInformation(token.value, TokenUser, bytes.data(), size, &size)) return Error();
                Local sid;
                if (!ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(bytes.data())->User.Sid,
                    reinterpret_cast<LPWSTR*>(&sid.value))) return Error();
                const auto user = static_cast<const wchar_t*>(sid.value);
                // Fresh OWN pipe only. No World/AuthenticatedUsers/admin-group
                // grant, impersonation privilege, foreign ACL repair or SCM call.
                const auto sddl = std::wstring(L"O:") + user + (stopEvent ? L"D:P(A;;0x001f0003;;;" : L"D:P(A;;0x001f01ff;;;") + user +
                    (stopEvent ? L")(A;;0x00120000;;;LS)" : L")(A;;0x00120083;;;LS)");
                return ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1, &descriptor.value, nullptr) ? S_OK : Error();
            }
            catch (...) { return E_OUTOFMEMORY; }
        }
    }
    std::wstring BrokerChannel::Name(const GUID& pipe)
    {
        wchar_t text[40]{};
        if (pipe == GUID_NULL || !StringFromGUID2(pipe, text, 40)) return {};
        return std::wstring(L"\\\\.\\pipe\\Magnolie.PhoneCamera.Broker.") + text;
    }
    HRESULT BrokerChannel::Initialize() noexcept
    {
        stop_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        readDone_ = CreateEventW(nullptr, TRUE, FALSE, nullptr); writeDone_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        return stop_ && readDone_ && writeDone_ ? S_OK : Error();
    }
    std::wstring BrokerChannel::StopName(const GUID& pipe)
    {
        wchar_t text[40]{};
        if (pipe == GUID_NULL || !StringFromGUID2(pipe, text, 40)) return {};
        return std::wstring(L"Global\\Magnolie.PhoneCamera.SourceStop.") + text;
    }
    HRESULT BrokerChannel::CreateStopEvent(const GUID& pipe, HANDLE& event) noexcept
    {
        if (event || pipe == GUID_NULL) return E_INVALIDARG;
        try
        {
            Local descriptor; HRESULT hr = OriginalUserPipeSecurity(descriptor, true); if (FAILED(hr)) return hr;
            SECURITY_ATTRIBUTES security{sizeof(security), descriptor.value, FALSE};
            HANDLE created = CreateEventW(&security, TRUE, FALSE, StopName(pipe).c_str());
            if (!created) return Error();
            if (GetLastError() == ERROR_ALREADY_EXISTS) { CloseHandle(created); return HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS); }
            event = created; return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    HRESULT BrokerChannel::Current() noexcept
    {
        if (stopped_.load()) return HRESULT_FROM_WIN32(ERROR_OPERATION_ABORTED);
        HRESULT hr = owner_.current(owner_.context);
        if (hr != S_OK) { Stop(); return FAILED(hr) ? hr : E_ACCESSDENIED; }
        if (peer_ && WaitForSingleObject(peer_, 0) != WAIT_TIMEOUT) { Stop(); return HRESULT_FROM_WIN32(ERROR_BROKEN_PIPE); }
        return stopped_.load() ? HRESULT_FROM_WIN32(ERROR_OPERATION_ABORTED) : S_OK;
    }
    HRESULT BrokerChannel::CreateServer(const GUID& pipe, BrokerChannelOwner owner, std::unique_ptr<BrokerChannel>& result) noexcept
    {
        if (result || pipe == GUID_NULL || !owner.current || !owner.lifetime) return E_INVALIDARG;
        try
        {
            auto channel = std::unique_ptr<BrokerChannel>(new BrokerChannel(owner));
            HRESULT hr = channel->Current(); if (FAILED(hr)) return hr;
            hr = channel->Initialize(); if (FAILED(hr)) return hr;
            Local descriptor; hr = OriginalUserPipeSecurity(descriptor); if (FAILED(hr)) return hr;
            SECURITY_ATTRIBUTES security{sizeof(security), descriptor.value, FALSE};
            channel->pipe_ = CreateNamedPipeW(Name(pipe).c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, 1, 65536, 65536, 0, &security);
            if (channel->pipe_ == INVALID_HANDLE_VALUE) return Error();
            channel->server_ = true; result = std::move(channel); return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    HRESULT BrokerChannel::Connect(const GUID& pipe, HANDLE originalParent, BrokerChannelOwner owner,
        std::unique_ptr<BrokerChannel>& result) noexcept
    {
        if (result || pipe == GUID_NULL || !originalParent || originalParent == INVALID_HANDLE_VALUE || !owner.current || !owner.lifetime) return E_INVALIDARG;
        try
        {
            auto channel = std::unique_ptr<BrokerChannel>(new BrokerChannel(owner));
            HRESULT hr = channel->Initialize(); if (FAILED(hr)) return hr;
            if (!DuplicateHandle(GetCurrentProcess(), originalParent, GetCurrentProcess(), &channel->peer_, 0, FALSE, DUPLICATE_SAME_ACCESS)) return Error();
            hr = channel->Current(); if (FAILED(hr)) return hr;
            channel->pipe_ = CreateFileW(Name(pipe).c_str(), PipeRights, 0, nullptr, OPEN_EXISTING,
                FILE_FLAG_OVERLAPPED | SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, nullptr);
            if (channel->pipe_ == INVALID_HANDLE_VALUE) return Error();
            ULONG actual = 0; DWORD flags = 0;
            if (!GetNamedPipeServerProcessId(channel->pipe_, &actual) || !GetNamedPipeInfo(channel->pipe_, &flags, nullptr, nullptr, nullptr)) return Error();
            if (!actual || actual != GetProcessId(channel->peer_) || (flags & PIPE_TYPE_MESSAGE)) return E_ACCESSDENIED;
            hr = channel->Current(); if (FAILED(hr)) return hr;
            channel->connected_ = true; result = std::move(channel); return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    HRESULT BrokerChannel::Complete(OVERLAPPED& operation, ULONGLONG start, DWORD& count) noexcept
    {
        HRESULT hr = S_OK;
        for (;;)
        {
            hr = Current(); if (FAILED(hr)) break;
            const auto now = GetTickCount64();
            if (now < start || now - start >= 2000) { hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT); break; }
            const HANDLE handles[] = {stop_, operation.hEvent, peer_};
            const DWORD wait = WaitForMultipleObjects(peer_ ? 3 : 2, handles, FALSE, 10);
            if (wait == WAIT_FAILED) { hr = Error(); break; }
            if (wait == WAIT_OBJECT_0 || wait == WAIT_OBJECT_0 + 2) { hr = HRESULT_FROM_WIN32(ERROR_OPERATION_ABORTED); break; }
            if (wait == WAIT_OBJECT_0 + 1) return GetOverlappedResult(pipe_, &operation, &count, FALSE) ? Current() : Error();
        }
        // Cancel/drain exactly our operation before its stack/event goes away.
        CancelIoEx(pipe_, &operation); DWORD ignored = 0; GetOverlappedResult(pipe_, &operation, &ignored, TRUE);
        return hr;
    }
    HRESULT BrokerChannel::Accept() noexcept
    {
        std::lock_guard<std::mutex> lock(read_);
        if (!server_ || acceptAttempted_) return E_INVALIDARG;
        acceptAttempted_ = true;
        HRESULT hr = Current(); if (FAILED(hr)) return hr;
        ResetEvent(readDone_); OVERLAPPED operation{}; operation.hEvent = readDone_; DWORD ignored = 0;
        if (!ConnectNamedPipe(pipe_, &operation))
        {
            DWORD error = GetLastError();
            if (error == ERROR_IO_PENDING) hr = Complete(operation, GetTickCount64(), ignored);
            else if (error != ERROR_PIPE_CONNECTED) hr = HRESULT_FROM_WIN32(error);
        }
        if (FAILED(hr)) { Stop(); return hr; }
        ULONG pid = 0;
        if (!GetNamedPipeClientProcessId(pipe_, &pid) || !pid) { Stop(); return E_ACCESSDENIED; }
        peer_ = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
        if (!peer_) { Stop(); return Error(); }
        ULONG repeated = 0;
        if (!GetNamedPipeClientProcessId(pipe_, &repeated) || repeated != pid) { Stop(); return E_ACCESSDENIED; }
        hr = Current(); if (FAILED(hr)) return hr;
        connected_ = true; return S_OK; // Kernel connection ONLY, not FrameServer admission.
    }
    HRESULT BrokerChannel::Transfer(bool write, BYTE* bytes, DWORD size) noexcept
    {
        if (!bytes || !size || size > Maximum) { Stop(); return E_INVALIDARG; }
        std::unique_lock<std::mutex> lock(write ? write_ : read_, std::try_to_lock);
        if (!lock.owns_lock()) { Stop(); return HRESULT_FROM_WIN32(ERROR_BUSY); }
        HRESULT hr = connected_ ? Current() : E_ACCESSDENIED;
        const auto begin = GetTickCount64(); DWORD at = 0;
        while (SUCCEEDED(hr) && at < size)
        {
            const auto now = GetTickCount64();
            if (now < begin || now - begin >= 2000) { hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT); break; }
            hr = Current(); if (FAILED(hr)) break;
            HANDLE done = write ? writeDone_ : readDone_; ResetEvent(done);
            OVERLAPPED operation{}; operation.hEvent = done; DWORD count = 0;
            BOOL finished = write ? WriteFile(pipe_, bytes + at, size - at, &count, &operation) : ReadFile(pipe_, bytes + at, size - at, &count, &operation);
            if (!finished)
            {
                DWORD error = GetLastError();
                hr = error == ERROR_IO_PENDING ? Complete(operation, begin, count) : HRESULT_FROM_WIN32(error);
                if (FAILED(hr)) break;
            }
            if (!count) { hr = HRESULT_FROM_WIN32(ERROR_BROKEN_PIPE); break; }
            at += count;
        }
        if (SUCCEEDED(hr)) hr = Current();
        if (FAILED(hr)) { Stop(); if (!write) SecureZeroMemory(bytes, size); }
        return hr;
    }
    HRESULT BrokerChannel::Read(BYTE* bytes, DWORD size) noexcept { return Transfer(false, bytes, size); }
    HRESULT BrokerChannel::Write(const BYTE* bytes, DWORD size) noexcept { return Transfer(true, const_cast<BYTE*>(bytes), size); }
    void BrokerChannel::Stop() noexcept { stopped_.store(true); if (stop_) SetEvent(stop_); }
    BrokerChannel::~BrokerChannel()
    {
        Stop(); std::scoped_lock<std::mutex, std::mutex> lock(read_, write_);
        if (pipe_ != INVALID_HANDLE_VALUE) CloseHandle(pipe_);
        if (peer_) CloseHandle(peer_);
        if (stop_) CloseHandle(stop_);
        if (readDone_) CloseHandle(readDone_);
        if (writeDone_) CloseHandle(writeDone_);
    }
}
