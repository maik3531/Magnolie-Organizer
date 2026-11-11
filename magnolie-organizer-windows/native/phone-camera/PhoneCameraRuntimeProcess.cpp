#include "PhoneCameraRuntimeProcess.h"
#include <aclapi.h>
#include <bcrypt.h>
#include <mferror.h>
#include <objbase.h>
#include <algorithm>
#include <cwchar>
#include <limits>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        HRESULT Error() noexcept { return HRESULT_FROM_WIN32(GetLastError()); }
        struct Local { void* value = nullptr; ~Local() { if (value) LocalFree(value); } };
        struct Handle { HANDLE value = nullptr; ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); } };
        bool Protected(HANDLE file) noexcept
        {
            Local descriptor; PSID owner = nullptr; PACL acl = nullptr;
            if (GetSecurityInfo(file, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &owner, nullptr, &acl, nullptr, reinterpret_cast<PSECURITY_DESCRIPTOR*>(&descriptor.value)) != ERROR_SUCCESS || !acl) return false;
            BYTE admin[SECURITY_MAX_SID_SIZE]{}, system[SECURITY_MAX_SID_SIZE]{};
            DWORD a = sizeof(admin), s = sizeof(system);
            if (!CreateWellKnownSid(WinBuiltinAdministratorsSid, nullptr, admin, &a) ||
                !CreateWellKnownSid(WinLocalSystemSid, nullptr, system, &s)) return false;
            // The standard Windows installer service SID is also an immutable
            // owner. Never accept arbitrary service SIDs or the current user.
            constexpr SID_IDENTIFIER_AUTHORITY authority = SECURITY_NT_AUTHORITY;
            PSID installer = nullptr; SID_IDENTIFIER_AUTHORITY nt = authority;
            if (!AllocateAndInitializeSid(&nt, 6, SECURITY_SERVICE_ID_BASE_RID, 956008885, 3418522649UL,
                1831038044, 1853292631, 2271478464UL, 0, 0, &installer)) return false;
            struct Free { PSID sid; ~Free() { FreeSid(sid); } } free{installer};
            auto trusted = [&](PSID sid) { return sid && (EqualSid(sid, admin) || EqualSid(sid, system) || EqualSid(sid, installer)); };
            if (!trusted(owner) || acl->AceCount > 128) return false;
            constexpr DWORD mutate = GENERIC_WRITE | GENERIC_ALL | FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_EA |
                FILE_WRITE_ATTRIBUTES | FILE_DELETE_CHILD | DELETE | WRITE_DAC | WRITE_OWNER;
            for (DWORD i = 0; i < acl->AceCount; ++i)
            {
                void* raw = nullptr; if (!GetAce(acl, i, &raw)) return false;
                const auto header = static_cast<ACE_HEADER*>(raw);
                if (header->AceFlags & INHERIT_ONLY_ACE) continue;
                if (header->AceType == ACCESS_DENIED_ACE_TYPE) continue;
                if (header->AceType != ACCESS_ALLOWED_ACE_TYPE) return false;
                const auto ace = static_cast<ACCESS_ALLOWED_ACE*>(raw);
                if ((ace->Mask & mutate) && !trusted(&ace->SidStart)) return false;
            }
            return true;
        }
        HRESULT Hash(HANDLE file, const std::array<BYTE, 32>& expected) noexcept
        {
            BCRYPT_ALG_HANDLE algorithm = nullptr; BCRYPT_HASH_HANDLE hash = nullptr;
            struct Clear
            {
                BCRYPT_ALG_HANDLE& algorithm; BCRYPT_HASH_HANDLE& hash;
                ~Clear() { if (hash) BCryptDestroyHash(hash); if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0); }
            } clear{algorithm, hash};
            NTSTATUS status = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0);
            if (status >= 0) status = BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0);
            if (status < 0) return HRESULT_FROM_NT(status);
            LARGE_INTEGER size{}, zero{};
            if (!GetFileSizeEx(file, &size) || !SetFilePointerEx(file, zero, nullptr, FILE_BEGIN)) return Error();
            if (size.QuadPart < 128 || size.QuadPart > 8 * 1024 * 1024) return E_INVALIDARG;
            BYTE buffer[16384]{}; DWORD bytes = 0;
            do
            {
                if (!ReadFile(file, buffer, sizeof(buffer), &bytes, nullptr)) return Error();
                status = BCryptHashData(hash, buffer, bytes, 0); if (status < 0) return HRESULT_FROM_NT(status);
            } while (bytes);
            std::array<BYTE, 32> actual{}; status = BCryptFinishHash(hash, actual.data(), static_cast<ULONG>(actual.size()), 0);
            if (status < 0) return HRESULT_FROM_NT(status);
            return actual == expected ? S_OK : HRESULT_FROM_WIN32(ERROR_CRC);
        }
        std::wstring Guid(const GUID& value)
        { wchar_t text[40]{}; return StringFromGUID2(value, text, 40) ? text : L""; }
    }
    HRESULT RuntimeImage::Hold(const std::wstring& path, bool directory, bool acl)
    {
        Handle file; file.value = CreateFileW(path.c_str(), GENERIC_READ | READ_CONTROL, FILE_SHARE_READ,
            nullptr, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT | (directory ? FILE_FLAG_BACKUP_SEMANTICS : 0), nullptr);
        if (file.value == INVALID_HANDLE_VALUE) return Error();
        BY_HANDLE_FILE_INFORMATION info{};
        if (!GetFileInformationByHandle(file.value, &info)) return Error();
        if ((info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) ||
            bool(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != directory || (acl && !Protected(file.value))) return E_ACCESSDENIED;
        files_.push_back(file.value); file.value = nullptr; return S_OK;
    }
    RuntimeImage::~RuntimeImage() { for (auto file : files_) CloseHandle(file); }
    HRESULT RuntimeImage::VerifySibling(const std::array<BYTE, 32>& digest, std::shared_ptr<RuntimeImage>& result) noexcept
    {
        if (result || std::all_of(digest.begin(), digest.end(), [](BYTE value) { return value == 0; })) return E_INVALIDARG;
        try
        {
            wchar_t module[32768]{}; const DWORD length = GetModuleFileNameW(nullptr, module, 32768);
            if (!length || length >= 32768) return E_ACCESSDENIED;
            std::wstring path(module, length);
            if (path.size() < 4 || path[1] != L':' || path[2] != L'\\' || path.find(L'/') != std::wstring::npos) return E_ACCESSDENIED;
            const auto end = path.find_last_of(L'\\');
            std::shared_ptr<RuntimeImage> image(new RuntimeImage);
            image->directory_ = path.substr(0, end); image->path_ = image->directory_ + L"\\" + Filename;
            HRESULT hr = image->Hold(path.substr(0, 3), true, false); if (FAILED(hr)) return hr;
            for (auto at = path.find(L'\\', 3); at != std::wstring::npos; at = path.find(L'\\', at + 1))
            { hr = image->Hold(path.substr(0, at), true, true); if (FAILED(hr)) return hr; }
            hr = image->Hold(image->path_, false, true); if (FAILED(hr)) return hr;
            hr = Hash(image->files_.back(), digest); if (FAILED(hr)) return hr;
            result = std::move(image); return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    HRESULT RuntimeProcess::Fail(HRESULT reason) noexcept
    {
        if (!retired_.exchange(true))
        {
            if (stop_) SetEvent(stop_);
            owner_.retired(owner_.context, reason);
        }
        return reason;
    }
    void RuntimeProcess::Stop() noexcept { Fail(MF_E_SHUTDOWN); }
    HRESULT RuntimeProcess::Check() noexcept
    {
        if (IsRetired()) return MF_E_SHUTDOWN;
        HRESULT hr = owner_.current(owner_.context);
        if (hr != S_OK) return Fail(FAILED(hr) ? hr : E_ACCESSDENIED);
        const auto deadline = deadline_.load();
        if (deadline && GetTickCount64() >= deadline) return Fail(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
        if (process_ && WaitForSingleObject(process_, 0) != WAIT_TIMEOUT) return Fail(HRESULT_FROM_WIN32(ERROR_BROKEN_PIPE));
        return IsRetired() ? MF_E_SHUTDOWN : S_OK;
    }
    void RuntimeProcess::Guard() noexcept
    {
        // Timing/termination never depend on a callback, COM, publisher lock
        // or blocked UI/parent IO caller. Notify only AFTER termination request.
        HRESULT reason = MF_E_SHUTDOWN;
        for (;;)
        {
            const HANDLE waits[] = {stop_, process_};
            const DWORD wait = WaitForMultipleObjects(2, waits, FALSE, 10);
            if (wait == WAIT_OBJECT_0) break;
            if (wait == WAIT_OBJECT_0 + 1) { reason = HRESULT_FROM_WIN32(ERROR_BROKEN_PIPE); break; }
            if (wait == WAIT_FAILED) { reason = Error(); break; }
            const auto deadline = deadline_.load();
            if (deadline && GetTickCount64() >= deadline && deadline_.load() == deadline)
            { reason = HRESULT_FROM_WIN32(ERROR_TIMEOUT); break; }
        }
        // The job contains ONLY this freshly created fixed verified runtime,
        // assigned while suspended. No external PID lookup or installer target.
        TerminateJobObject(job_, ERROR_OPERATION_ABORTED);
        Fail(reason);
        exitConfirmed_.store(WaitForSingleObject(process_, 5000) == WAIT_OBJECT_0);
        SetEvent(finished_);
    }
    HRESULT RuntimeProcess::Create(const std::shared_ptr<RuntimeImage>& image, const GUID& control,
        const GUID& audio, const GUID& anchor, RuntimeProcessOwner owner, std::unique_ptr<RuntimeProcess>& result) noexcept
    {
        if (result || !image || image->files_.empty() || !owner.current || !owner.retired ||
            control == GUID_NULL || audio == GUID_NULL || anchor == GUID_NULL || control == audio || control == anchor || audio == anchor) return E_INVALIDARG;
        try
        {
            std::unique_ptr<RuntimeProcess> child(new RuntimeProcess(owner)); child->image_ = image;
            HRESULT hr = child->Check(); if (FAILED(hr)) return hr;
            child->job_ = CreateJobObjectW(nullptr, nullptr);
            child->stop_ = CreateEventW(nullptr, TRUE, FALSE, nullptr); child->finished_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            if (!child->job_ || !child->stop_ || !child->finished_) return child->Fail(Error());
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_ACTIVE_PROCESS | JOB_OBJECT_LIMIT_PROCESS_MEMORY;
            limits.BasicLimitInformation.ActiveProcessLimit = 1; limits.ProcessMemoryLimit = 256 * 1024 * 1024;
            if (!SetInformationJobObject(child->job_, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) return child->Fail(Error());
            Handle parent;
            if (!DuplicateHandle(GetCurrentProcess(), GetCurrentProcess(), GetCurrentProcess(), &parent.value,
                SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, TRUE, 0)) return child->Fail(Error());
            SIZE_T bytes = 0; InitializeProcThreadAttributeList(nullptr, 1, 0, &bytes);
            if (!bytes || bytes > 65536) return child->Fail(E_UNEXPECTED);
            std::vector<BYTE> storage(bytes); auto attributes = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
            if (!InitializeProcThreadAttributeList(attributes, 1, 0, &bytes)) return child->Fail(Error());
            struct Clear { LPPROC_THREAD_ATTRIBUTE_LIST value; ~Clear() { DeleteProcThreadAttributeList(value); } } clear{attributes};
            if (!UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, &parent.value, sizeof(HANDLE), nullptr, nullptr)) return child->Fail(Error());
            std::wstring command = L"\"" + image->path_ + L"\" --phone-audio-worker " + Guid(control) + L" " + Guid(audio) + L" " + Guid(anchor) + L" " + std::to_wstring(reinterpret_cast<ULONG_PTR>(parent.value));
            wchar_t windows[32768]{}; const UINT count = GetWindowsDirectoryW(windows, 32768);
            if (!count || count >= 32768) return child->Fail(E_ACCESSDENIED);
            const std::wstring root(windows, count);
            std::wstring environment = L"PATH=" + root + L"\\System32";
            environment.push_back(0); environment += L"SystemRoot=" + root;
            environment.push_back(0); environment += L"WINDIR=" + root; environment.push_back(0); environment.push_back(0);
            STARTUPINFOEXW startup{}; startup.StartupInfo.cb = sizeof(startup); startup.lpAttributeList = attributes;
            PROCESS_INFORMATION process{};
            if (!CreateProcessW(image->path_.c_str(), command.data(), nullptr, nullptr, TRUE,
                CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT,
                environment.data(), image->directory_.c_str(), &startup.StartupInfo, &process)) return child->Fail(Error());
            child->process_ = process.hProcess; child->thread_ = process.hThread;
            if (!AssignProcessToJobObject(child->job_, child->process_))
            {
                hr = Error(); TerminateProcess(child->process_, ERROR_OPERATION_ABORTED); // ONLY its just-created still-suspended worker, not yet in the job.
                child->exitConfirmed_ = WaitForSingleObject(child->process_, 5000) == WAIT_OBJECT_0;
                return child->Fail(hr);
            }
            child->deadline_ = GetTickCount64() + 10000;
            child->guard_ = std::thread([value = child.get()] { value->Guard(); });
            hr = child->Check(); if (FAILED(hr)) return hr;
            result = std::move(child); return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    HRESULT RuntimeProcess::Resume() noexcept
    {
        std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
        if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
        HRESULT hr = Check(); if (FAILED(hr)) return hr;
        if (resumed_) return Fail(E_INVALIDARG);
        const DWORD previous = ResumeThread(thread_);
        if (previous == static_cast<DWORD>(-1)) return Fail(Error());
        if (previous != 1) return Fail(E_UNEXPECTED);
        resumed_ = true; return Check();
    }
    HRESULT RuntimeProcess::CompletePreparation() noexcept
    {
        std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
        if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
        HRESULT hr = Check(); if (FAILED(hr)) return hr;
        if (!resumed_ || prepared_) return Fail(E_INVALIDARG);
        prepared_ = true; deadline_.store(0); return Check();
    }
    HRESULT RuntimeProcess::BeginOperation(ULONGLONG* token) noexcept
    {
        if (!token) return E_POINTER;
        *token = 0;
        std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
        if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
        HRESULT hr = Check(); if (FAILED(hr)) return hr;
        if (!prepared_ || operation_ || nextToken_ == (std::numeric_limits<ULONGLONG>::max)()) return Fail(E_INVALIDARG);
        operation_ = nextToken_++; deadline_.store(GetTickCount64() + 250);
        hr = Check(); if (FAILED(hr)) return hr;
        *token = operation_; return S_OK;
    }
    HRESULT RuntimeProcess::CompleteOperation(ULONGLONG token) noexcept
    {
        std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
        if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
        HRESULT hr = Check(); if (FAILED(hr)) return hr;
        if (!token || token != operation_) return Fail(E_INVALIDARG);
        operation_ = 0; deadline_.store(0); return Check();
    }
    HRESULT RuntimeProcess::WaitStopped(DWORD milliseconds) noexcept
    {
        if (!finished_ || milliseconds > 5000) return E_INVALIDARG;
        const DWORD wait = WaitForSingleObject(finished_, milliseconds);
        if (wait == WAIT_TIMEOUT) return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
        if (wait != WAIT_OBJECT_0) return Error();
        return exitConfirmed_.load() ? S_OK : E_FAIL;
    }
    RuntimeProcess::~RuntimeProcess()
    {
        Stop();
        if (guard_.joinable()) guard_.join();
        else if (process_ && !exitConfirmed_) // Guard allocation/assignment failure before Resume; owns exactly this child.
        { TerminateJobObject(job_, ERROR_OPERATION_ABORTED); WaitForSingleObject(process_, 5000); }
        if (thread_) CloseHandle(thread_);
        if (process_) CloseHandle(process_);
        if (job_) CloseHandle(job_);
        if (finished_) CloseHandle(finished_);
        if (stop_) CloseHandle(stop_);
    }
}
