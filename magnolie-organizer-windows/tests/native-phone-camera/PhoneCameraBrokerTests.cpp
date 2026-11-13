#include "../../native/phone-camera/PhoneCameraBrokerProtocol.h"
#include "../../native/phone-camera/PhoneCameraBrokerChannel.h"
#include "../../native/phone-camera/PhoneCameraSourceBroker.h"
#include "../../native/phone-camera/PhoneCameraFrameServerPeer.h"
#include "../../native/phone-camera/PhoneCameraSourceBrokerParent.h"
#include "../../native/phone-camera/PhoneCameraVideoParent.h"
#include <mfapi.h>
#include <mferror.h>
#include <ks.h>
#include <ksproxy.h>
#include <wrl.h>
#include <array>
#include <cstring>
#include <cstdio>
#include <stdexcept>
#include <string>

using namespace Magnolie::PhoneCamera;
namespace
{
    void Check(bool condition) { if (!condition) throw std::runtime_error("broker assertion"); }
    struct Handle { HANDLE handle = nullptr; ~Handle() { if (handle && handle != INVALID_HANDLE_VALUE) CloseHandle(handle); } };
    struct Owner final : Microsoft::WRL::RuntimeClass<Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, IUnknown>
    {
        HRESULT status = S_OK, bindStatus = S_OK;
        int binds = 0, closed = 0;
        std::atomic<int> retired{0};
        std::atomic<HRESULT> reason{S_OK};
        std::atomic<int> activeChanges{0};
        std::atomic_bool active{false};
        static HRESULT Current(void* context) noexcept { return static_cast<Owner*>(context)->status; }
        static void Closed(void* context) noexcept { ++static_cast<Owner*>(context)->closed; }
        static HRESULT Bind(void* context, const BYTE*, ULONG size) noexcept
        { auto& self = *static_cast<Owner*>(context); ++self.binds; return size == BrokerProperty::Bytes ? self.bindStatus : E_INVALIDARG; }
        static HRESULT Sending(void*) noexcept { return E_ACCESSDENIED; }
        static void Retired(void* context, HRESULT retirementReason) noexcept
        { auto& self = *static_cast<Owner*>(context); self.reason.store(retirementReason); ++self.retired; }
        static void Active(void* context, bool running) noexcept
        { auto& self = *static_cast<Owner*>(context); self.active.store(running); ++self.activeChanges; }
        BrokerChannelOwner Channel() { return {Current, this, this}; }
        RegistrationLifetime Registration() { return {Current, this, this, Closed, Bind}; }
    };
    GUID Fresh() { GUID guid{}; Check(CoCreateGuid(&guid) == S_OK); return guid; }
    std::array<BYTE, BrokerProperty::Bytes> Property()
    {
        std::array<BYTE, BrokerProperty::Bytes> bytes{};
        std::memcpy(bytes.data(), "MGFSB001", 8); DWORD version = 1, size = BrokerProperty::Bytes, pid = 123, session = 1; ULONGLONG birth = 1234;
        auto scope = Fresh(), pipe = Fresh(); std::memcpy(bytes.data() + 8, &version, 4); std::memcpy(bytes.data() + 12, &size, 4);
        std::memcpy(bytes.data() + 16, &scope, 16); std::memcpy(bytes.data() + 32, &pipe, 16); std::memcpy(bytes.data() + 48, &pid, 4);
        std::memcpy(bytes.data() + 52, &session, 4); std::memcpy(bytes.data() + 56, &birth, 8);
        for (std::size_t i = 64; i < bytes.size(); ++i) bytes[i] = static_cast<BYTE>(i);
        return bytes; // Synthetic bytes only, never actual process/OS/capture authority.
    }
    void OwnedPropertyAndMac()
    {
        auto bytes = Property(); BrokerProperty property, same;
        Check(BrokerProperty::Decode(bytes.data(), static_cast<ULONG>(bytes.size()), property) == S_OK);
        Check(BrokerProperty::Decode(bytes.data(), static_cast<ULONG>(bytes.size()), same) == S_OK);
        std::array<BYTE, 32> parent{}, source{}, mac{}, other{}; parent[0] = 1; source[0] = 2;
        bytes[64] ^= 1;
        Check(property.Mac(true, parent.data(), source.data(), mac.data()) == S_OK);
        Check(same.Mac(true, parent.data(), source.data(), other.data()) == S_OK && BrokerProperty::EqualMac(mac.data(), other.data()));
        Check(same.Mac(false, parent.data(), source.data(), other.data()) == S_OK && !BrokerProperty::EqualMac(mac.data(), other.data()));
        source[3] ^= 1;
        Check(same.Mac(true, parent.data(), source.data(), other.data()) == S_OK && !BrokerProperty::EqualMac(mac.data(), other.data()));
        Check(BrokerProperty::Decode(bytes.data(), static_cast<ULONG>(bytes.size()), property) == E_INVALIDARG);
        property.ClearKey(); Check(FAILED(property.Mac(true, parent.data(), source.data(), other.data())));
        Check(!BrokerProperty::EqualMac(nullptr, other.data()));
    }
    void PropertyShapeAndIdentity()
    {
        const auto original = Property();
        for (const auto offset : {0, 8, 12})
        {
            auto changed = original; changed[static_cast<std::size_t>(offset)] ^= 0x40; BrokerProperty denied;
            Check(FAILED(BrokerProperty::Decode(changed.data(), static_cast<ULONG>(changed.size()), denied)));
        }
        for (const auto range : {std::pair<int, int>{16,16}, {32,16}, {48,4}, {52,4}, {56,8}, {64,32}})
        {
            auto changed = original; std::memset(changed.data() + range.first, 0, static_cast<std::size_t>(range.second)); BrokerProperty denied;
            Check(FAILED(BrokerProperty::Decode(changed.data(), static_cast<ULONG>(changed.size()), denied)));
        }
        BrokerProperty shortInput;
        Check(FAILED(BrokerProperty::Decode(original.data(), BrokerProperty::Bytes - 1, shortInput)));
        std::array<BYTE, 32> parent{}, source{}, base{}, changedMac{};
        BrokerProperty first; Check(BrokerProperty::Decode(original.data(), BrokerProperty::Bytes, first) == S_OK);
        Check(first.Mac(true, parent.data(), source.data(), base.data()) == S_OK);
        for (std::size_t offset : {16u,32u,48u,52u,56u,64u})
        {
            auto changed = original; changed[offset] ^= 0x20; BrokerProperty different;
            Check(BrokerProperty::Decode(changed.data(), BrokerProperty::Bytes, different) == S_OK);
            Check(different.Mac(true, parent.data(), source.data(), changedMac.data()) == S_OK && !BrokerProperty::EqualMac(base.data(), changedMac.data()));
        }
    }
    void ChannelGuardNoFallback()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); owner->status = S_FALSE; std::unique_ptr<BrokerChannel> channel;
        Check(BrokerChannel::CreateServer(Fresh(), owner->Channel(), channel) == E_ACCESSDENIED && !channel);
        Check(BrokerChannel::Name(GUID_NULL).empty() && BrokerChannel::StopName(GUID_NULL).empty());
        Check(BrokerChannel::Name(Fresh()).find(L"\\\\.\\pipe\\Magnolie.PhoneCamera.Broker.") == 0);
        Check(BrokerChannel::StopName(Fresh()).find(L"Global\\Magnolie.PhoneCamera.SourceStop.") == 0);
        Check(FAILED(FrameServerPeer::RequireCurrentHost())); // Actual primary token/image, no metadata grant.
    }
    void ActualOriginalResourceCreationPolicy()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); Handle token;
        Check(!!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token.handle));
        TOKEN_ELEVATION elevation{}; DWORD bytes = 0, session = 0;
        Check(!!GetTokenInformation(token.handle, TokenElevation, &elevation, sizeof(elevation), &bytes));
        Check(!!ProcessIdToSessionId(GetCurrentProcessId(), &session));
        wchar_t strict[2]{};
        if (GetEnvironmentVariableW(L"MAGNOLIE_BROKER_TEST_REQUIRE_ORDINARY", strict, 2))
            Check(strict[0] == L'1' && !elevation.TokenIsElevated && session != 0); // TEST ONLY, stricter, never a product bypass.
        const auto pipe = Fresh(); std::unique_ptr<BrokerChannel> channel; Handle stop;
        HRESULT hr = BrokerChannel::CreateServer(pipe, owner->Channel(), channel);
        if (elevation.TokenIsElevated || !session)
        { Check(hr == E_ACCESSDENIED && !channel); Check(BrokerChannel::CreateStopEvent(pipe, stop.handle) == E_ACCESSDENIED && !stop.handle); }
        else
        {
            Check(hr == S_OK && channel);
            Check(BrokerChannel::CreateStopEvent(pipe, stop.handle) == S_OK && stop.handle);
            std::unique_ptr<BrokerChannel> collision;
            Check(FAILED(BrokerChannel::CreateServer(pipe, owner->Channel(), collision)) && !collision);
            Handle eventCollision;
            Check(BrokerChannel::CreateStopEvent(pipe, eventCollision.handle) == HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS) && !eventCollision.handle);
        }
    }
    void Complete(HANDLE pipe, bool write, BYTE* bytes, DWORD size)
    {
        Handle event; event.handle = CreateEventW(nullptr, TRUE, FALSE, nullptr); Check(!!event.handle);
        OVERLAPPED operation{}; operation.hEvent = event.handle; DWORD count = 0;
        BOOL done = write ? WriteFile(pipe, bytes, size, &count, &operation) : ReadFile(pipe, bytes, size, &count, &operation);
        if (!done)
        {
            Check(GetLastError() == ERROR_IO_PENDING);
            const bool signaled = WaitForSingleObject(event.handle, 2000) == WAIT_OBJECT_0;
            if (!signaled) { CancelIoEx(pipe, &operation); GetOverlappedResult(pipe, &operation, &count, TRUE); }
            Check(signaled && GetOverlappedResult(pipe, &operation, &count, FALSE));
        }
        Check(count == size);
    }
    void ActualOwnKernelChannelNoAdmission()
    {
        // Test-owned synthetic peer, not production CreateServer, service or
        // elevated compatibility fallback. Source authentication MUST reject it.
        auto owner = Microsoft::WRL::Make<Owner>(); const auto guid = Fresh(); Handle server, process;
        server.handle = CreateNamedPipeW(BrokerChannel::Name(guid).c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_REJECT_REMOTE_CLIENTS, 1, 4096, 4096, 0, nullptr);
        Check(server.handle != INVALID_HANDLE_VALUE);
        process.handle = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, GetCurrentProcessId()); Check(!!process.handle);
        std::unique_ptr<BrokerChannel> channel;
        Check(BrokerChannel::Connect(guid, process.handle, owner->Channel(), channel) == S_OK);
        OVERLAPPED connection{}; Check(!ConnectNamedPipe(server.handle, &connection) && GetLastError() == ERROR_PIPE_CONNECTED);
        std::shared_ptr<FrameServerPeer> rejected;
        Check(FAILED(FrameServerPeer::Accept(server.handle, {Owner::Current, Owner::Retired, owner.Get(), owner.Get()}, rejected)) && !rejected);
        std::array<BYTE, 3> sent{1,2,3}, got{}; Complete(server.handle, true, sent.data(), 3);
        Check(channel->Read(got.data(), 3) == S_OK && got == sent);
        Check(channel->Write(sent.data(), 3) == S_OK); got.fill(0); Complete(server.handle, false, got.data(), 3); Check(got == sent);
        owner->status = S_FALSE; got.fill(0xff);
        Check(channel->Read(got.data(), 3) == E_ACCESSDENIED && got == std::array<BYTE,3>{});
        owner->status = S_OK; Check(FAILED(channel->Read(got.data(), 3))); // No revival/reconnect.
    }
    void ReturnValueCannotBindSource()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); Microsoft::WRL::ComPtr<IMFMediaSourceEx> source;
        std::unique_ptr<DormantSourceControl> unique;
        Check(CreateDormantSource(owner->Registration(), &source, unique) == S_OK);
        auto control = std::shared_ptr<DormantSourceControl>(std::move(unique));
        Microsoft::WRL::ComPtr<IKsControl> ks; Check(source.As(&ks) == S_OK);
        auto body = Property(); std::array<BYTE, sizeof(KSPROPERTY) + BrokerProperty::Bytes> packet{};
        KSPROPERTY header{}; header.Set = BrokerProperty::PropertySet; header.Id = BrokerProperty::PropertyId; header.Flags = KSPROPERTY_TYPE_SET;
        std::memcpy(packet.data(), &header, sizeof(header)); std::memcpy(packet.data() + sizeof(header), body.data(), body.size());
        ULONG written = 123;
        Check(ks->KsProperty(reinterpret_cast<PKSPROPERTY>(packet.data()), static_cast<ULONG>(packet.size()), nullptr, 0, &written) == S_OK && !written && owner->binds == 1);
        Check(control->RequireBound() == MF_E_NOT_INITIALIZED); // Successful fake callback did not make a proof.
        Check(FAILED(ks->KsProperty(reinterpret_cast<PKSPROPERTY>(packet.data()), static_cast<ULONG>(packet.size()), nullptr, 0, &written)) && owner->binds == 1);
        source->Shutdown();
    }
    void ActualSourceBrokerRejectsOrdinaryHost()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); Microsoft::WRL::ComPtr<IMFMediaSourceEx> source;
        std::unique_ptr<DormantSourceControl> unique;
        Check(CreateDormantSource(owner->Registration(), &source, unique) == S_OK);
        auto control = std::shared_ptr<DormantSourceControl>(std::move(unique)); auto body = Property();
        Microsoft::WRL::ComPtr<ISourceBrokerLifetime> lifetime;
        Check(FAILED(BindOriginalSourceBroker(owner->Registration(), control, body.data(), static_cast<ULONG>(body.size()), &lifetime)) && !lifetime);
        Check(control->RequireBound() == MF_E_NOT_INITIALIZED); source->Shutdown();
    }
    void PreparationDoesNotConsumeSendTimeout()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); Microsoft::WRL::ComPtr<IMFMediaSourceEx> source;
        Microsoft::WRL::ComPtr<IFrameFeed> feed;
        Check(CreateSource({Owner::Current, Owner::Sending, Owner::Retired, owner.Get(), owner.Get()}, &source, &feed) == S_OK);
        Microsoft::WRL::ComPtr<IMFPresentationDescriptor> descriptor; Check(source->CreatePresentationDescriptor(&descriptor) == S_OK);
        PROPVARIANT start{}; start.vt = VT_EMPTY;
        Check(source->Start(descriptor.Get(), &GUID_NULL, &start) == S_OK);
        Sleep(5300); // Bounded REAL native timer regression; no virtual camera/device/capture or SEND.
        DWORD flags = 0; const HRESULT current = source->GetCharacteristics(&flags);
        const int retired = owner->retired.load(); source->Shutdown();
        if (current != S_OK || retired != 0) throw std::runtime_error("source retired during preparation before actual SEND");
    }
    void ActualOutputActivityIsNotBindingOrSending()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); Microsoft::WRL::ComPtr<IMFMediaSourceEx> source;
        Microsoft::WRL::ComPtr<IFrameFeed> feed;
        Check(CreateSource({Owner::Current, Owner::Sending, Owner::Retired, owner.Get(), owner.Get(), Owner::Active}, &source, &feed) == S_OK);
        Microsoft::WRL::ComPtr<IMFPresentationDescriptor> descriptor; Check(source->CreatePresentationDescriptor(&descriptor) == S_OK);
        Check(!owner->active.load() && owner->activeChanges.load() == 0);
        PROPVARIANT start{}; start.vt = VT_EMPTY;
        Check(source->Start(descriptor.Get(), &GUID_NULL, &start) == S_OK && owner->active.load() && owner->activeChanges.load() == 1);
        Check(Owner::Sending(owner.Get()) == E_ACCESSDENIED); // Actual MF Start grants no phone SEND.
        Check(source->Start(descriptor.Get(), &GUID_NULL, &start) == MF_E_INVALID_STATE_TRANSITION && owner->activeChanges.load() == 1);
        Microsoft::WRL::ComPtr<IMFMediaEvent> event;
        Check(source->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event) == S_OK);
        MediaEventType type{}; Check(event->GetType(&type) == S_OK && type == MENewStream);
        PROPVARIANT value{}; PropVariantInit(&value);
        Check(event->GetValue(&value) == S_OK);
        Microsoft::WRL::ComPtr<IMFMediaStream2> stream;
        const HRESULT queried = value.vt == VT_UNKNOWN && value.punkVal ? value.punkVal->QueryInterface(IID_PPV_ARGS(&stream)) : E_NOINTERFACE;
        PropVariantClear(&value); Check(queried == S_OK);
        Check(stream->SetStreamState(MF_STREAM_STATE_PAUSED) == S_OK && !owner->active.load() && owner->activeChanges.load() == 2);
        Check(stream->SetStreamState(MF_STREAM_STATE_PAUSED) == S_OK && owner->activeChanges.load() == 2);
        Check(stream->SetStreamState(MF_STREAM_STATE_RUNNING) == S_OK && owner->active.load() && owner->activeChanges.load() == 3);
        Check(source->Stop() == S_OK && !owner->active.load() && owner->activeChanges.load() == 4);
        Check(stream->SetStreamState(MF_STREAM_STATE_RUNNING) == MF_E_INVALID_STATE_TRANSITION && owner->activeChanges.load() == 4);
        Check(source->Start(descriptor.Get(), &GUID_NULL, &start) == S_OK && owner->active.load() && owner->activeChanges.load() == 5);
        Check(source->Shutdown() == S_OK && !owner->active.load() && owner->activeChanges.load() == 6);
        Check(FAILED(stream->SetStreamState(MF_STREAM_STATE_RUNNING)) && owner->activeChanges.load() == 6);
    }
    void ActivityAccountingDrainsAfterTerminalStopWithoutReadiness()
    {
        SourceBrokerActivity activity;
        Check(!activity.Active());
        Check(activity.Observe(1, 1, false, false) == E_ACCESSDENIED && !activity.Active());
        Check(activity.Observe(2, 1, true, false) == E_ACCESSDENIED && !activity.Active());
        Check(activity.Observe(1, 0, true, false) == E_ACCESSDENIED && !activity.Active());
        Check(activity.Observe(1, 2, true, false) == E_ACCESSDENIED && !activity.Active());
        Check(activity.Observe(1, 1, true, false) == S_OK && activity.Active());
        Check(activity.Observe(1, 1, true, false) == E_ACCESSDENIED); // Replay cannot advance accounting.
        Check(activity.Observe(0, 2, true, true) == S_OK && !activity.Active());
        Check(activity.Observe(1, 3, true, true) == S_OK && !activity.Active()); // Drain ONLY, never Ready.
        Check(activity.Observe(0, 4, true, true) == S_OK && !activity.Active());
        SourceBrokerActivity live;
        Check(live.Observe(1, 1, true, false) == S_OK && live.Active());
        Check(live.Observe(0, 2, true, false) == MF_E_SHUTDOWN && !live.Active());
        Check(live.Observe(1, 3, true, false) == S_OK && !live.Active()); // Terminal accounting itself cannot revive.
    }
    void VideoAbiGuardsWithoutStartingAnyOutput()
    {
        auto owner = Microsoft::WRL::Make<Owner>(); const auto scope = Fresh(); ULONGLONG handle = 123;
        MagnoliePhoneVideoOwnerV1 original{sizeof(original), 1, 1, 0, Owner::Current, Owner::Sending, Owner::Retired,
            Owner::Current, nullptr, nullptr, owner.Get()};
        Check(MagnoliePhoneVideoVersion() == 1);
        Check(static_cast<DWORD>(MF_E_NOT_INITIALIZED) == 0xc00d36b6u); // Exact managed readiness-poll contract from the actual SDK.
        owner->status = S_FALSE;
        Check(MagnoliePhoneVideoCreate(&scope, &original, &handle) == E_ACCESSDENIED && !handle);
        owner->status = S_OK;
        for (const DWORD flag : {2u, 0u})
        {
            auto invalid = original; invalid.flags = flag;
            Check(MagnoliePhoneVideoCreate(&scope, &invalid, &handle) == E_INVALIDARG && !handle);
        }
        Check(MagnoliePhoneVideoCreate(&scope, &original, &handle) == S_OK && handle);
        // Create owns ONLY events/clock context. Never call productive Prepare:
        // no MF startup, OS manager, broker/property, service or camera is opened.
        Check(MagnoliePhoneVideoRequireReady(handle) == MF_E_NOT_INITIALIZED);
        ULONGLONG collision = 123;
        Check(MagnoliePhoneVideoCreate(&scope, &original, &collision) == HRESULT_FROM_WIN32(ERROR_BUSY) && !collision);
        Check(MagnoliePhoneVideoStop(handle) == S_OK);
        Check(MagnoliePhoneVideoPrepare(handle) == MF_E_SHUTDOWN); // Refused BEFORE starting an MTA/MF worker.
        Check(FAILED(MagnoliePhoneVideoRequireReady(handle)));
        Check(MagnoliePhoneVideoClose(handle) == S_OK);
        Check(MagnoliePhoneVideoStop(handle) == E_INVALIDARG && MagnoliePhoneVideoClose(handle) == E_INVALIDARG);
        Check(MagnoliePhoneVideoCreate(&scope, &original, &collision) == S_OK && collision != handle);
        Check(MagnoliePhoneVideoClose(collision) == S_OK);
    }
}
int main(int argc, char** argv)
{
    HRESULT com = CoInitializeEx(nullptr, COINIT_MULTITHREADED); if (FAILED(com)) return 1;
    HRESULT mf = MFStartup(MF_VERSION, MFSTARTUP_LITE); if (FAILED(mf)) { CoUninitialize(); return 1; }
    int result = 0;
    try
    {
        const std::string only = argc == 2 ? std::string(",") + argv[1] + "," : "";
        struct Case { const char* name; void (*run)(); };
        const Case cases[] = {{"broker-owned-property-directional-MAC", OwnedPropertyAndMac}, {"broker-property-shape-original-identity", PropertyShapeAndIdentity},
            {"broker-guard-no-host-fallback", ChannelGuardNoFallback}, {"broker-own-kernel-channel-is-not-admission", ActualOwnKernelChannelNoAdmission},
            {"broker-original-resource-creation-policy", ActualOriginalResourceCreationPolicy},
            {"broker-property-success-is-not-source-proof", ReturnValueCannotBindSource}, {"broker-actual-ordinary-host-denied-before-adoption", ActualSourceBrokerRejectsOrdinaryHost},
            {"broker-prepare-before-send-no-media-timeout", PreparationDoesNotConsumeSendTimeout},
            {"broker-actual-source-output-activity-is-not-send", ActualOutputActivityIsNotBindingOrSending},
            {"broker-activity-terminal-drain-is-not-readiness", ActivityAccountingDrainsAfterTerminalStopWithoutReadiness},
            {"broker-video-cabi-guards-no-output-start", VideoAbiGuardsWithoutStartingAnyOutput}};
        int ran = 0;
        for (const auto& test : cases)
            if (only.empty() || only.find(std::string(",") + test.name + ",") != std::string::npos)
            { test.run(); ++ran; std::printf("PASS %s\n", test.name); }
        if (!ran) result = 87;
    }
    catch (const std::exception& error) { std::fprintf(stderr, "%s\n", error.what()); result = 1; }
    MFShutdown(); CoUninitialize(); return result;
}
