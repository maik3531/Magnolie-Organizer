#include "PhoneCameraFrameServerPeer.h"
#include <mferror.h>
#include <array>
#include <vector>
#include <string>
#include <cwchar>
#include <cstdint>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        HRESULT Error() noexcept { return HRESULT_FROM_WIN32(GetLastError()); }
        struct Handle { HANDLE value = nullptr; ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); } };
        bool TokenBlob(HANDLE token, TOKEN_INFORMATION_CLASS kind, std::vector<BYTE>& bytes)
        {
            DWORD size = 0; GetTokenInformation(token, kind, nullptr, 0, &size);
            if (size < sizeof(DWORD) || size > 65536) return false;
            bytes.resize(size); return !!GetTokenInformation(token, kind, bytes.data(), size, &size);
        }
        bool ServiceSid(std::array<BYTE, SECURITY_MAX_SID_SIZE>& sid) noexcept
        {
            DWORD size = static_cast<DWORD>(sid.size()), domainSize = 256; wchar_t domain[256]{}; SID_NAME_USE use{};
            // The service's fixed OS identity, not LocalService as a whole or
            // a service name selected from metadata. This does not start SCM.
            return !!LookupAccountNameW(nullptr, L"NT SERVICE\\FrameServer", sid.data(), &size, domain, &domainSize, &use);
        }
        bool InBlob(PSID sid, const TOKEN_GROUPS* groups, std::size_t bytes) noexcept
        {
            const auto begin = reinterpret_cast<std::uintptr_t>(groups), value = reinterpret_cast<std::uintptr_t>(sid);
            if (!sid || bytes < 8 || value < begin || value - begin > bytes - 8) return false;
            const auto offset = static_cast<std::size_t>(value - begin);
            const auto raw = static_cast<const BYTE*>(sid);
            const auto length = 8 + static_cast<std::size_t>(raw[1]) * sizeof(DWORD);
            return length <= bytes - offset && IsValidSid(sid);
        }
    }
    bool FrameServerPeer::AllowsIdentity(PSID user, DWORD session, const TOKEN_GROUPS* groups, std::size_t bytes) noexcept
    {
        if (!user || !IsValidSid(user) || session != 0 || !groups || bytes < offsetof(TOKEN_GROUPS, Groups) ||
            bytes > 65536 || groups->GroupCount > 128 ||
            groups->GroupCount > (bytes - offsetof(TOKEN_GROUPS, Groups)) / sizeof(SID_AND_ATTRIBUTES)) return false;
        std::array<BYTE, SECURITY_MAX_SID_SIZE> local{}, service{}; DWORD size = static_cast<DWORD>(local.size());
        if (!CreateWellKnownSid(WinLocalServiceSid, nullptr, local.data(), &size) || !EqualSid(user, local.data()) || !ServiceSid(service)) return false;
        bool found = false;
        for (DWORD i = 0; i < groups->GroupCount; ++i)
        {
            const auto& group = groups->Groups[i]; if (!InBlob(group.Sid, groups, bytes)) return false;
            if (EqualSid(group.Sid, service.data()))
            {
                if (found || !(group.Attributes & SE_GROUP_ENABLED) || (group.Attributes & SE_GROUP_USE_FOR_DENY_ONLY)) return false;
                found = true;
            }
        }
        return found;
    }
    HRESULT FrameServerPeer::RequireCurrentHost() noexcept
    {
        try
        {
            Handle token;
            if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token.value)) return Error();
            TOKEN_TYPE type{}; DWORD length = 0, session = 0;
            if (!GetTokenInformation(token.value, TokenType, &type, sizeof(type), &length) || type != TokenPrimary ||
                !GetTokenInformation(token.value, TokenSessionId, &session, sizeof(session), &length)) return E_ACCESSDENIED;
            std::vector<BYTE> user, groups;
            if (!TokenBlob(token.value, TokenUser, user) || user.size() < sizeof(TOKEN_USER) || !TokenBlob(token.value, TokenGroups, groups) ||
                !AllowsIdentity(reinterpret_cast<TOKEN_USER*>(user.data())->User.Sid, session,
                    reinterpret_cast<TOKEN_GROUPS*>(groups.data()), groups.size())) return E_ACCESSDENIED;
            wchar_t image[32768]{}, system[32768]{}; DWORD count = 32768;
            if (!QueryFullProcessImageNameW(GetCurrentProcess(), 0, image, &count)) return Error();
            const UINT size = GetSystemDirectoryW(system, 32768);
            return size && size < 32768 && !_wcsicmp(image, (std::wstring(system, size) + L"\\svchost.exe").c_str()) ? S_OK : E_ACCESSDENIED;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    HRESULT FrameServerPeer::Accept(HANDLE pipe, const FrameServerPeerOwner& owner, std::shared_ptr<FrameServerPeer>& result) noexcept
    {
        if (result || !pipe || pipe == INVALID_HANDLE_VALUE || !owner.current || !owner.retired) return E_INVALIDARG;
        try
        {
            HRESULT hr = owner.current(owner.context); if (hr != S_OK) return FAILED(hr) ? hr : E_ACCESSDENIED;
            DWORD flags = 0; ULONG pid = 0, session = 0;
            if (GetFileType(pipe) != FILE_TYPE_PIPE || !GetNamedPipeInfo(pipe, &flags, nullptr, nullptr, nullptr)) return E_ACCESSDENIED;
            if (!(flags & PIPE_SERVER_END) || (flags & PIPE_TYPE_MESSAGE)) return E_ACCESSDENIED;
            if (!GetNamedPipeClientProcessId(pipe, &pid) || !GetNamedPipeClientSessionId(pipe, &session) || !pid || session != 0) return E_ACCESSDENIED;
            std::shared_ptr<FrameServerPeer> peer(new FrameServerPeer(owner));
            if (!DuplicateHandle(GetCurrentProcess(), pipe, GetCurrentProcess(), &peer->pipe_, 0, FALSE, DUPLICATE_SAME_ACCESS)) return Error();
            peer->process_ = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
            if (!peer->process_) return Error();
            peer->pid_ = pid;
            Handle token; if (!OpenProcessToken(peer->process_, TOKEN_QUERY, &token.value)) return Error();
            TOKEN_TYPE type{}; DWORD length = 0, tokenSession = 0;
            if (!GetTokenInformation(token.value, TokenType, &type, sizeof(type), &length) || type != TokenPrimary ||
                !GetTokenInformation(token.value, TokenSessionId, &tokenSession, sizeof(tokenSession), &length) || tokenSession != session) return E_ACCESSDENIED;
            std::vector<BYTE> user, groups;
            if (!TokenBlob(token.value, TokenUser, user) || user.size() < sizeof(TOKEN_USER) || !TokenBlob(token.value, TokenGroups, groups) ||
                !AllowsIdentity(reinterpret_cast<TOKEN_USER*>(user.data())->User.Sid, tokenSession,
                    reinterpret_cast<TOKEN_GROUPS*>(groups.data()), groups.size())) return E_ACCESSDENIED;
            wchar_t image[32768]{}, system[32768]{}; DWORD count = 32768;
            if (!QueryFullProcessImageNameW(peer->process_, 0, image, &count)) return Error();
            const UINT systemLength = GetSystemDirectoryW(system, 32768);
            if (!systemLength || systemLength >= 32768 || _wcsicmp(image, (std::wstring(system, systemLength) + L"\\svchost.exe").c_str())) return E_ACCESSDENIED;
            ULONG repeated = 0, repeatedSession = 0;
            if (!GetNamedPipeClientProcessId(peer->pipe_, &repeated) || repeated != pid ||
                !GetNamedPipeClientSessionId(peer->pipe_, &repeatedSession) || repeatedSession != session ||
                WaitForSingleObject(peer->process_, 0) != WAIT_TIMEOUT) return E_ACCESSDENIED;
            hr = owner.current(owner.context); if (hr != S_OK) return FAILED(hr) ? hr : E_ACCESSDENIED;
            peer->admitted_ = true; result = std::move(peer); return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    HRESULT FrameServerPeer::Fail(HRESULT reason) noexcept
    {
        if (!retired_.exchange(true) && admitted_) owner_.retired(owner_.context, reason);
        return reason;
    }
    HRESULT FrameServerPeer::RequireCurrent() noexcept
    {
        if (retired_.load() || !admitted_) return MF_E_SHUTDOWN;
        HRESULT hr = owner_.current(owner_.context);
        if (hr != S_OK) return Fail(FAILED(hr) ? hr : E_ACCESSDENIED);
        ULONG pid = 0, session = 0;
        if (WaitForSingleObject(process_, 0) != WAIT_TIMEOUT || !GetNamedPipeClientProcessId(pipe_, &pid) || pid != pid_ ||
            !GetNamedPipeClientSessionId(pipe_, &session) || session != 0) return Fail(E_ACCESSDENIED);
        return retired_.load() ? MF_E_SHUTDOWN : S_OK;
    }
    void FrameServerPeer::Stop() noexcept { Fail(MF_E_SHUTDOWN); }
    FrameServerPeer::~FrameServerPeer()
    {
        Stop(); // Unadmitted rejections never retire a genuine original owner.
        if (pipe_ != INVALID_HANDLE_VALUE) CloseHandle(pipe_);
        if (process_) CloseHandle(process_);
    }
}
