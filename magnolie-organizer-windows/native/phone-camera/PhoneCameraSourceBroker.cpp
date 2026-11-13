#include "PhoneCameraSourceBroker.h"
#include "PhoneCameraBrokerChannel.h"
#include "PhoneCameraBrokerProtocol.h"
#include "PhoneCameraFrameServerPeer.h"
#include "PhoneCameraOutputLease.h"
#include <aclapi.h>
#include <mferror.h>
#include <wrl.h>
#include <array>
#include <cstring>
#include <limits>
#include <vector>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        HRESULT Error() noexcept { return HRESULT_FROM_WIN32(GetLastError()); }
        HRESULT Exact(HRESULT hr) noexcept { return hr == S_OK ? S_OK : FAILED(hr) ? hr : E_ACCESSDENIED; }
        struct Handle { HANDLE value = nullptr; ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); } };
        struct Local { void* value = nullptr; ~Local() { if (value) LocalFree(value); } };
        struct Clear { BYTE* bytes; std::size_t size; ~Clear() { SecureZeroMemory(bytes, size); } };
        std::uint64_t Big(const BYTE* bytes) noexcept
        { std::uint64_t n = 0; for (unsigned int i = 0; i < 8; ++i) n = (n << 8) | bytes[i]; return n; }
        HRESULT RequireOriginalSecurity(HANDLE object, SE_OBJECT_TYPE type, PSID originalUser, bool stopEvent)
        {
            Local descriptor; PSID owner = nullptr; PACL dacl = nullptr;
            DWORD status = GetSecurityInfo(object, type, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &owner, nullptr, &dacl, nullptr, &descriptor.value);
            if (status != ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
            SECURITY_DESCRIPTOR_CONTROL control{}; DWORD revision = 0;
            if (!owner || !EqualSid(owner, originalUser) || !dacl || !IsValidAcl(dacl) || dacl->AceCount != 2 ||
                !GetSecurityDescriptorControl(descriptor.value, &control, &revision) || !(control & SE_DACL_PROTECTED)) return E_ACCESSDENIED;
            std::array<BYTE, SECURITY_MAX_SID_SIZE> local{}; DWORD size = static_cast<DWORD>(local.size());
            if (!CreateWellKnownSid(WinLocalServiceSid, nullptr, local.data(), &size)) return Error();
            bool userFound = false, serviceFound = false;
            for (DWORD i = 0; i < 2; ++i)
            {
                void* raw = nullptr; if (!GetAce(dacl, i, &raw)) return Error();
                auto ace = static_cast<const ACCESS_ALLOWED_ACE*>(raw);
                if (ace->Header.AceType != ACCESS_ALLOWED_ACE_TYPE || ace->Header.AceFlags ||
                    ace->Header.AceSize < offsetof(ACCESS_ALLOWED_ACE, SidStart) + 8) return E_ACCESSDENIED;
                const auto sid = const_cast<DWORD*>(&ace->SidStart);
                const auto sidBytes = reinterpret_cast<const BYTE*>(sid);
                if (8 + static_cast<DWORD>(sidBytes[1]) * sizeof(DWORD) > ace->Header.AceSize - offsetof(ACCESS_ALLOWED_ACE, SidStart) ||
                    !IsValidSid(sid)) return E_ACCESSDENIED;
                DWORD expected = BrokerChannel::PipeRights;
                if (EqualSid(sid, originalUser)) { if (userFound) return E_ACCESSDENIED; userFound = true; expected = stopEvent ? BrokerChannel::StopOwnerRights : BrokerChannel::PipeOwnerRights; }
                else if (EqualSid(sid, local.data())) { if (serviceFound) return E_ACCESSDENIED; serviceFound = true; if (stopEvent) expected = BrokerChannel::StopReaderRights; }
                else return E_ACCESSDENIED;
                if (ace->Mask != expected) return E_ACCESSDENIED;
            }
            return userFound && serviceFound ? S_OK : E_ACCESSDENIED;
        }
    }

    // Only THIS productive broker can create SourceBindingProof. No external
    // callback table/hash/PID/receipt can construct or adopt it by itself.
    class FrameServerSourceBroker final : public Microsoft::WRL::RuntimeClass<
        Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, ISourceBrokerLifetime>
    {
    public:
        FrameServerSourceBroker(RegistrationLifetime registration, std::shared_ptr<DormantSourceControl> control)
            : registration_(registration), registrationLifetime_(registration.lifetime), control_(std::move(control)) {}
        ~FrameServerSourceBroker()
        {
            RequestStop();
            // Worker owns an AddRef and an OS module pin until its FINAL exit;
            // never wait/join from registration callbacks or this worker's Release.
            if (thread_) CloseHandle(thread_);
            if (localStop_) CloseHandle(localStop_);
            if (parentStop_) CloseHandle(parentStop_);
            if (parent_) CloseHandle(parent_);
        }
        void STDMETHODCALLTYPE RequestStop() noexcept override
        { stopped_.store(true); if (localStop_) SetEvent(localStop_); }

        HRESULT Initialize(const BYTE* bytes, ULONG size)
        {
            HRESULT hr = Exact(registration_.current(registration_.context)); if (FAILED(hr)) return hr;
            hr = BrokerProperty::Decode(bytes, size, property_); if (FAILED(hr)) return hr;
            parent_ = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, property_.ParentPid());
            if (!parent_) return Error();
            FILETIME birth{}, exit{}, kernel{}, user{};
            if (!GetProcessTimes(parent_, &birth, &exit, &kernel, &user)) return Error();
            ULONGLONG actualBirth = 0; std::memcpy(&actualBirth, &birth, sizeof(birth));
            if (actualBirth != property_.ParentBirth()) return E_ACCESSDENIED;
            Handle token;
            if (!OpenProcessToken(parent_, TOKEN_QUERY, &token.value)) return Error();
            DWORD length = 0, session = 0; TOKEN_ELEVATION elevation{}; TOKEN_TYPE type{};
            if (!GetTokenInformation(token.value, TokenSessionId, &session, sizeof(session), &length) ||
                !GetTokenInformation(token.value, TokenType, &type, sizeof(type), &length) ||
                !GetTokenInformation(token.value, TokenElevation, &elevation, sizeof(elevation), &length)) return Error();
            if (type != TokenPrimary || elevation.TokenIsElevated || !session || session != property_.ParentSession()) return E_ACCESSDENIED;
            localStop_ = CreateEventW(nullptr, TRUE, FALSE, nullptr); if (!localStop_) return Error();
            parentStop_ = OpenEventW(SYNCHRONIZE | READ_CONTROL, FALSE, BrokerChannel::StopName(property_.Pipe()).c_str());
            if (!parentStop_) return Error();
            std::unique_ptr<BrokerChannel> connected;
            hr = BrokerChannel::Connect(property_.Pipe(), parent_, {TransportCurrent, this, this}, connected); if (FAILED(hr)) return hr;
            channel_ = std::move(connected);
            DWORD tokenSize = 0; GetTokenInformation(token.value, TokenUser, nullptr, 0, &tokenSize);
            if (tokenSize < sizeof(TOKEN_USER) || tokenSize > 65536) return E_ACCESSDENIED;
            std::vector<BYTE> tokenUser(tokenSize);
            if (!GetTokenInformation(token.value, TokenUser, tokenUser.data(), tokenSize, &tokenSize)) return Error();
            PSID sid = reinterpret_cast<TOKEN_USER*>(tokenUser.data())->User.Sid;
            hr = RequireOriginalSecurity(channel_->Pipe(), SE_FILE_OBJECT, sid, false); if (FAILED(hr)) return hr;
            hr = RequireOriginalSecurity(parentStop_, SE_KERNEL_OBJECT, sid, true); if (FAILED(hr)) return hr;
            std::array<BYTE, 32> parentNonce{}, expected{}, parentMac{}; std::array<BYTE, 64> response{};
            Clear clearA{parentNonce.data(), parentNonce.size()}, clearB{expected.data(), expected.size()},
                clearC{parentMac.data(), parentMac.size()}, clearD{response.data(), response.size()};
            hr = channel_->Read(parentNonce.data(), 32);
            if (SUCCEEDED(hr)) hr = BrokerProperty::Random(response.data());
            if (SUCCEEDED(hr)) hr = property_.Mac(true, parentNonce.data(), response.data(), response.data() + 32);
            if (SUCCEEDED(hr)) hr = channel_->Write(response.data(), 64);
            if (SUCCEEDED(hr)) hr = channel_->Read(parentMac.data(), 32);
            if (SUCCEEDED(hr)) hr = property_.Mac(false, parentNonce.data(), response.data(), expected.data());
            if (SUCCEEDED(hr) && !BrokerProperty::EqualMac(expected.data(), parentMac.data())) hr = E_ACCESSDENIED;
            property_.ClearKey();
            if (FAILED(hr)) return hr;
            authenticated_ = true;
            hr = ParentCurrent(this); if (FAILED(hr)) return hr;
            std::unique_ptr<PipeReader> reader;
            hr = PipeReader::AdoptBroker(channel_->Pipe(), parent_, localStop_, ParentCurrent, this, reader); if (FAILED(hr)) return hr;
            hr = OutputLease::Create(reader, {Retired, this, this, nullptr}, lease_); if (FAILED(hr)) return hr;
            BYTE tag = 0;
            hr = lease_->Control()->ReadExact(&tag, 1);
            if (SUCCEEDED(hr) && tag != 1) hr = E_INVALIDARG;
            if (SUCCEEDED(hr)) hr = lease_->ReceiveOne();
            if (SUCCEEDED(hr)) hr = lease_->RequireCurrent();
            if (FAILED(hr)) return hr;
            const ClockOwner clockOwner{Current, Sending, Retired, this, this, nullptr};
            auto clock = std::make_shared<PresentationClock>(clockOwner);
            clock_ = clock;
            // Receiver starts while Source construction is in progress, so the
            // actual original preparation lease can renew without a larger TTL.
            hr = StartWorker(); if (FAILED(hr)) return hr;
            const SourceOwner owner{Current, Sending, Retired, this, this};
            auto proof = std::unique_ptr<SourceBindingProof>(new SourceBindingProof(*control_, owner, property_.Scope(), clock));
            hr = control_->Adopt(std::move(proof));
            Microsoft::WRL::ComPtr<IFrameFeed> feed;
            if (SUCCEEDED(hr)) hr = control_->GetBoundFeed(&feed);
            if (SUCCEEDED(hr)) hr = Current(this);
            if (FAILED(hr)) { RequestStop(); return hr; }
            {
                std::lock_guard<std::mutex> lock(resources_);
                if (stopped_.load()) return MF_E_SHUTDOWN;
                feed_ = feed; bound_.store(true);
            }
            return Receipt("MGFSBND1", S_OK); // Binding accounting ONLY, never media Ready.
        }
        void AbortBeforePublication() noexcept
        {
            RequestStop(); property_.ClearKey();
            if (!thread_)
            {
                Cleanup();
                if (authenticated_) Receipt("MGFSEND1", S_OK);
                std::lock_guard<std::mutex> lock(resources_); channel_.reset();
            } // A running worker exclusively owns cleanup.
        }
    private:
        static HRESULT TransportCurrent(void* context) noexcept
        {
            auto& self = *static_cast<FrameServerSourceBroker*>(context);
            // Terminal ACK remains possible AFTER capture retirement. This path
            // never authorizes a lease/sample, only holds the original peer.
            return self.parent_ && WaitForSingleObject(self.parent_, 0) == WAIT_TIMEOUT ? S_OK : MF_E_SHUTDOWN;
        }
        static HRESULT ParentCurrent(void* context) noexcept
        {
            auto& self = *static_cast<FrameServerSourceBroker*>(context);
            if (self.stopped_.load() || !self.parentStop_ || WaitForSingleObject(self.parentStop_, 0) != WAIT_TIMEOUT) return MF_E_SHUTDOWN;
            HRESULT hr = Exact(self.registration_.current(self.registration_.context));
            if (SUCCEEDED(hr)) hr = TransportCurrent(context);
            if (FAILED(hr)) self.RequestStop();
            return hr;
        }
        static HRESULT Current(void* context) noexcept
        {
            auto& self = *static_cast<FrameServerSourceBroker*>(context);
            HRESULT hr = ParentCurrent(context); if (FAILED(hr)) return hr;
            std::lock_guard<std::mutex> lock(self.resources_);
            if (self.stopped_.load() || !self.lease_) return MF_E_SHUTDOWN;
            return self.lease_->RequireCurrent();
        }
        static HRESULT Sending(void* context) noexcept
        {
            auto& self = *static_cast<FrameServerSourceBroker*>(context);
            HRESULT hr = ParentCurrent(context); if (FAILED(hr)) return hr;
            std::lock_guard<std::mutex> lock(self.resources_);
            if (self.stopped_.load() || !self.lease_) return MF_E_SHUTDOWN;
            return self.lease_->RequireSending();
        }
        static void Retired(void* context, HRESULT) noexcept { static_cast<FrameServerSourceBroker*>(context)->RequestStop(); }
        HRESULT Receipt(const char* magic, HRESULT result) noexcept
        {
            std::shared_ptr<BrokerChannel> channel;
            { std::lock_guard<std::mutex> lock(resources_); channel = channel_; }
            if (!channel) return E_UNEXPECTED;
            std::array<BYTE, 32> record{}; std::memcpy(record.data(), magic, 8);
            const auto scope = property_.Scope(); std::memcpy(record.data() + 8, &scope, 16);
            std::memcpy(record.data() + 24, &result, sizeof(result));
            return channel->Write(record.data(), static_cast<DWORD>(record.size()));
        }
        HRESULT StartWorker() noexcept
        {
            HMODULE pin = nullptr;
            if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS, reinterpret_cast<LPCWSTR>(&ThreadMain), &pin)) return Error();
            modulePin_ = pin; AddRef();
            thread_ = CreateThread(nullptr, 0, ThreadMain, this, 0, nullptr);
            if (!thread_) { HRESULT hr = Error(); Release(); FreeLibrary(pin); modulePin_ = nullptr; return hr; }
            return S_OK;
        }
        static DWORD WINAPI ThreadMain(void* context) noexcept
        {
            auto self = static_cast<FrameServerSourceBroker*>(context); const auto pin = self->modulePin_;
            self->Run(); self->Cleanup();
            if (self->Receipt("MGFSEND1", S_OK) == S_OK)
            {
                std::shared_ptr<BrokerChannel> channel;
                { std::lock_guard<std::mutex> lock(self->resources_); channel = self->channel_; }
                std::array<BYTE, 32> ack{};
                HRESULT ackResult = channel ? channel->Read(ack.data(), static_cast<DWORD>(ack.size())) : E_UNEXPECTED;
                GUID scope{}; HRESULT result{}; DWORD reserved = 0;
                std::memcpy(&scope, ack.data() + 8, 16); std::memcpy(&result, ack.data() + 24, 4); std::memcpy(&reserved, ack.data() + 28, 4);
                if (channel && (ackResult != S_OK || std::memcmp(ack.data(), "MGFSDON1", 8) ||
                    scope != self->property_.Scope() || result != S_OK || reserved)) channel->Stop();
                // This bounded final read grants nothing and cannot revive the
                // retired source. Its only purpose is draining the original ACK.
            }
            { std::lock_guard<std::mutex> lock(self->resources_); self->channel_.reset(); }
            self->Release();
            // ModuleContext/COM counts alone cannot cover instructions AFTER
            // the final Release on this thread. Exit with the actual OS pin.
            FreeLibraryAndExitThread(pin, 0);
        }
        void Run() noexcept
        {
            try
            {
                std::vector<BYTE> video(18 + Samples::VideoBytes);
                Clear clear{video.data(), video.size()};
                while (ParentCurrent(this) == S_OK)
                {
                    BYTE type = 0; HRESULT hr = lease_->Control()->ReadExact(&type, 1);
                    if (FAILED(hr)) break;
                    if (type == 1) hr = lease_->ReceiveOne();
                    else if (!bound_.load()) hr = E_ACCESSDENIED;
                    else if (type == 2)
                    {
                        std::array<BYTE, PresentationClock::AnchorBytes> anchor{}; Clear wipe{anchor.data(), anchor.size()};
                        hr = lease_->Control()->ReadExact(anchor.data(), static_cast<DWORD>(anchor.size()));
                        if (SUCCEEDED(hr)) hr = Sending(this);
                        if (SUCCEEDED(hr)) hr = clock_->ImportAnchor(property_.Scope(), anchor.data(), anchor.size());
                    }
                    else if (type == 3)
                    {
                        hr = lease_->Control()->ReadExact(video.data(), video.size());
                        const auto sequence = Big(video.data() + 2), pts = Big(video.data() + 10);
                        if (SUCCEEDED(hr) && (video[0] != 1 || video[1] != 1 || sequence > static_cast<std::uint64_t>((std::numeric_limits<LONGLONG>::max)()) ||
                            pts > 9007199254740991ULL)) hr = E_INVALIDARG;
                        if (SUCCEEDED(hr)) hr = Sending(this);
                        if (SUCCEEDED(hr)) hr = feed_->PublishVideo(video.data() + 18, static_cast<DWORD>(Samples::VideoBytes),
                            static_cast<LONGLONG>(sequence), static_cast<LONGLONG>(pts));
                    }
                    else hr = E_INVALIDARG;
                    if (FAILED(hr)) break;
                }
            }
            catch (...) { }
            RequestStop();
        }
        void Cleanup() noexcept
        {
            RequestStop();
            control_->Stop(); // Exact original target; Stop races adoption safely.
            std::unique_ptr<OutputLease> lease; std::shared_ptr<PresentationClock> clock; Microsoft::WRL::ComPtr<IFrameFeed> feed;
            {
                std::lock_guard<std::mutex> lock(resources_);
                lease = std::move(lease_); clock = std::move(clock_); feed = std::move(feed_);
            }
            // Break cycles only AFTER terminal callbacks can no longer touch
            // these resources. Retained MF clients still hold this retired ctx.
            feed.Reset(); clock.reset(); lease.reset();
        }
        const RegistrationLifetime registration_;
        Microsoft::WRL::ComPtr<IUnknown> registrationLifetime_;
        const std::shared_ptr<DormantSourceControl> control_;
        BrokerProperty property_;
        HANDLE parent_ = nullptr, parentStop_ = nullptr, localStop_ = nullptr, thread_ = nullptr;
        HMODULE modulePin_ = nullptr;
        std::shared_ptr<BrokerChannel> channel_;
        std::unique_ptr<OutputLease> lease_;
        std::shared_ptr<PresentationClock> clock_;
        Microsoft::WRL::ComPtr<IFrameFeed> feed_;
        std::mutex resources_;
        std::atomic_bool stopped_{false}, bound_{false};
        bool authenticated_ = false;
    };
    HRESULT BindOriginalSourceBroker(RegistrationLifetime registration, const std::shared_ptr<DormantSourceControl>& target,
        const BYTE* property, ULONG bytes, ISourceBrokerLifetime** result) noexcept
    {
        if (!result) return E_POINTER; *result = nullptr;
        if (!target || !registration.current || !registration.context || !registration.lifetime || !property || bytes != BrokerProperty::Bytes) return E_INVALIDARG;
        HRESULT hr = FrameServerPeer::RequireCurrentHost(); if (FAILED(hr)) return hr;
        Microsoft::WRL::ComPtr<FrameServerSourceBroker> broker;
        try
        {
            broker = Microsoft::WRL::Make<FrameServerSourceBroker>(registration, target);
            if (!broker) return E_OUTOFMEMORY;
            hr = broker->Initialize(property, bytes);
            if (FAILED(hr)) { broker->AbortBeforePublication(); return hr; }
            return broker.CopyTo(result);
        }
        catch (...) { if (broker) broker->AbortBeforePublication(); return E_OUTOFMEMORY; }
    }
}
