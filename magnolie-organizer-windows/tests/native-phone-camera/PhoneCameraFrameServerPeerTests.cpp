#include "../../native/phone-camera/PhoneCameraFrameServerPeer.h"
#include <objbase.h>
#include <array>
#include <vector>
#include <cstring>
#include <cstdio>
#include <stdexcept>
#include <string>

using namespace Magnolie::PhoneCamera;
namespace
{
    void Check(bool value) { if (!value) throw std::runtime_error("FrameServer peer assertion"); }
    struct Handle { HANDLE value = nullptr; ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); } };
    struct Owner
    {
        HRESULT current = S_OK;
        int checks = 0, retired = 0;
        static HRESULT Current(void* value) noexcept { auto& self = *static_cast<Owner*>(value); ++self.checks; return self.current; }
        static void Retired(void* value, HRESULT) noexcept { ++static_cast<Owner*>(value)->retired; }
        FrameServerPeerOwner Callbacks() { return {Current, Retired, this}; }
    };
    struct Identity
    {
        std::array<BYTE, SECURITY_MAX_SID_SIZE> local{}, system{}, service{};
        std::vector<BYTE> bytes;
        explicit Identity(DWORD count = 1)
        {
            DWORD size = static_cast<DWORD>(local.size()); Check(!!CreateWellKnownSid(WinLocalServiceSid, nullptr, local.data(), &size));
            size = static_cast<DWORD>(system.size()); Check(!!CreateWellKnownSid(WinLocalSystemSid, nullptr, system.data(), &size));
            size = static_cast<DWORD>(service.size()); wchar_t domain[256]{}; DWORD domainSize = 256; SID_NAME_USE use{};
            Check(!!LookupAccountNameW(nullptr, L"NT SERVICE\\FrameServer", service.data(), &size, domain, &domainSize, &use));
            const auto offset = offsetof(TOKEN_GROUPS, Groups) + count * sizeof(SID_AND_ATTRIBUTES);
            bytes.resize(offset + size); auto groups = Groups(); groups->GroupCount = count;
            std::memcpy(bytes.data() + offset, service.data(), size);
            for (DWORD i = 0; i < count; ++i) { groups->Groups[i].Sid = bytes.data() + offset; groups->Groups[i].Attributes = SE_GROUP_ENABLED; }
        }
        TOKEN_GROUPS* Groups() { return reinterpret_cast<TOKEN_GROUPS*>(bytes.data()); }
        bool Allowed(DWORD session = 0) { return FrameServerPeer::AllowsIdentity(local.data(), session, Groups(), bytes.size()); }
    };
    struct Pipe
    {
        Handle server, client;
        explicit Pipe(bool message = false)
        {
            GUID guid{}; Check(SUCCEEDED(CoCreateGuid(&guid))); wchar_t text[40]{}; Check(!!StringFromGUID2(guid, text, 40));
            const auto name = std::wstring(L"\\\\.\\pipe\\Magnolie.FrameServer.PeerProbe.") + text;
            server.value = CreateNamedPipeW(name.c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
                (message ? PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE : PIPE_TYPE_BYTE | PIPE_READMODE_BYTE) | PIPE_REJECT_REMOTE_CLIENTS,
                1, 256, 256, 0, nullptr); Check(server.value != INVALID_HANDLE_VALUE);
            client.value = CreateFileW(name.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING,
                SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, nullptr); Check(client.value != INVALID_HANDLE_VALUE);
            Check(ConnectNamedPipe(server.value, nullptr) || GetLastError() == ERROR_PIPE_CONNECTED);
        }
    };
    void ExactServiceIdentityMemoryOnly()
    {
        Identity identity; Check(identity.Allowed());
        Check(!FrameServerPeer::AllowsIdentity(identity.system.data(), 0, identity.Groups(), identity.bytes.size()));
        Check(!identity.Allowed(1));
        Check(!FrameServerPeer::AllowsIdentity(nullptr, 0, identity.Groups(), identity.bytes.size()));
        // Positive SID policy is MEMORY ONLY; no privileged process, accepted
        // peer, ready output, capture permission or SEND is constructed here.
    }
    void EnabledServiceGroupRequired()
    {
        Identity identity; auto& group = identity.Groups()->Groups[0];
        group.Attributes = 0; Check(!identity.Allowed());
        group.Attributes = SE_GROUP_ENABLED | SE_GROUP_USE_FOR_DENY_ONLY; Check(!identity.Allowed());
        group.Attributes = SE_GROUP_ENABLED; group.Sid = identity.bytes.data(); Check(!identity.Allowed());
        Identity duplicate(2); Check(!duplicate.Allowed());
        Identity empty(0); Check(!empty.Allowed());
    }
    void BoundedOwnedTokenBlob()
    {
        Identity identity;
        Check(!FrameServerPeer::AllowsIdentity(identity.local.data(), 0, identity.Groups(), offsetof(TOKEN_GROUPS, Groups) - 1));
        Check(!FrameServerPeer::AllowsIdentity(identity.local.data(), 0, identity.Groups(), 65537));
        identity.Groups()->GroupCount = 129; Check(!identity.Allowed());
        identity.Groups()->GroupCount = 1; identity.Groups()->Groups[0].Sid = identity.service.data(); Check(!identity.Allowed());
        identity.Groups()->Groups[0].Sid = identity.bytes.data() + identity.bytes.size() - 1; Check(!identity.Allowed());
    }
    void ActualOwnUserPipeRejectedWithoutOwnerLoss()
    {
        Pipe pipe; ULONG pid = 0; Check(!!GetNamedPipeClientProcessId(pipe.server.value, &pid) && pid == GetCurrentProcessId());
        Owner owner; std::shared_ptr<FrameServerPeer> peer;
        Check(FrameServerPeer::Accept(pipe.server.value, owner.Callbacks(), peer) == E_ACCESSDENIED && !peer);
        Check(owner.checks == 1 && owner.retired == 0);
        BYTE sent = 42, received = 0; DWORD bytes = 0;
        Check(!!WriteFile(pipe.client.value, &sent, 1, &bytes, nullptr) && bytes == 1);
        Check(!!ReadFile(pipe.server.value, &received, 1, &bytes, nullptr) && bytes == 1 && received == sent);
        // Admission refusal must not close the caller's own base pipe/transport.
    }
    void EndpointRoleAndTypeRejected()
    {
        Owner owner; std::shared_ptr<FrameServerPeer> peer; Pipe byte;
        Check(FrameServerPeer::Accept(byte.client.value, owner.Callbacks(), peer) == E_ACCESSDENIED && !peer);
        Pipe message(true); Check(FrameServerPeer::Accept(message.server.value, owner.Callbacks(), peer) == E_ACCESSDENIED && !peer);
        Handle event; event.value = CreateEventW(nullptr, TRUE, FALSE, nullptr); Check(event.value);
        Check(FrameServerPeer::Accept(event.value, owner.Callbacks(), peer) == E_ACCESSDENIED && !peer);
        Check(owner.retired == 0);
    }
    void OriginalCurrentBeforePeerAndNoPositiveAlias()
    {
        Pipe pipe; Owner owner; std::shared_ptr<FrameServerPeer> peer;
        owner.current = E_ABORT; Check(FrameServerPeer::Accept(pipe.server.value, owner.Callbacks(), peer) == E_ABORT && !peer);
        owner.current = S_FALSE; Check(FrameServerPeer::Accept(pipe.server.value, owner.Callbacks(), peer) == E_ACCESSDENIED && !peer);
        owner.current = S_OK; auto invalid = owner.Callbacks(); invalid.current = nullptr;
        Check(FrameServerPeer::Accept(pipe.server.value, invalid, peer) == E_INVALIDARG && !peer);
        Check(owner.retired == 0);
    }
}
int main()
{
    const struct { const char* name; void (*run)(); } tests[] = {
        {"frameserver-peer-memory-fixed-service", ExactServiceIdentityMemoryOnly},
        {"frameserver-peer-memory-enabled-group", EnabledServiceGroupRequired},
        {"frameserver-peer-memory-bounded-token", BoundedOwnedTokenBlob},
        {"frameserver-peer-actual-user-pipe-denied", ActualOwnUserPipeRejectedWithoutOwnerLoss},
        {"frameserver-peer-actual-endpoint-role", EndpointRoleAndTypeRejected},
        {"frameserver-peer-original-current", OriginalCurrentBeforePeerAndNoPositiveAlias}
    };
    int failed = 0;
    for (const auto& test : tests) { try { test.run(); std::printf("PASS %s\n", test.name); } catch (...) { ++failed; std::printf("FAIL %s\n", test.name); } std::fflush(stdout); }
    return failed ? 1 : 0;
}
