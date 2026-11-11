#include "PhoneCameraAudioParent.h"
#include "PhoneCameraClock.h"
#include "PhoneCameraOutputPublisher.h"
#include "PhoneCameraRuntimeProcess.h"
#include "PhoneCameraRuntimeStatus.h"
#include "PhoneCameraSamples.h"
#include <mferror.h>
#include <objbase.h>
#include <sddl.h>
#include <algorithm>
#include <cstring>
#include <limits>
#include <unordered_map>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        HRESULT Error() noexcept { return HRESULT_FROM_WIN32(GetLastError()); }
        struct Handle { HANDLE value = nullptr; ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); } };
        struct Local { void* value = nullptr; ~Local() { if (value) LocalFree(value); } };
        HRESULT Security(Local& descriptor)
        {
            Handle token; if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token.value)) return Error();
            DWORD bytes = 0; GetTokenInformation(token.value, TokenUser, nullptr, 0, &bytes);
            if (!bytes || bytes > 65536) return E_ACCESSDENIED;
            std::vector<BYTE> data(bytes); if (!GetTokenInformation(token.value, TokenUser, data.data(), bytes, &bytes)) return Error();
            Local sid; if (!ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(data.data())->User.Sid, reinterpret_cast<wchar_t**>(&sid.value))) return Error();
            const auto text = std::wstring(L"D:P(A;;GA;;;SY)(A;;GA;;;") + static_cast<wchar_t*>(sid.value) + L")";
            return ConvertStringSecurityDescriptorToSecurityDescriptorW(text.c_str(), SDDL_REVISION_1,
                reinterpret_cast<PSECURITY_DESCRIPTOR*>(&descriptor.value), nullptr) ? S_OK : Error();
        }
        ULONGLONG Integer(const BYTE* bytes) noexcept
        { ULONGLONG result = 0; for (unsigned int i = 0; i < 8; ++i) result = (result << 8) | bytes[i]; return result; }
        class DataPipe final
        {
        public:
            using Current = HRESULT (*)(void*) noexcept;
            DataPipe(HANDLE child, Current current, void* context) noexcept : child_(child), current_(current), context_(context) {}
            HRESULT Open(const GUID& scope)
            {
                Local descriptor; HRESULT hr = Security(descriptor); if (FAILED(hr)) return hr;
                SECURITY_ATTRIBUTES attributes{sizeof(attributes), descriptor.value, FALSE};
                pipe_.value = CreateNamedPipeW(PipeReader::Name(scope).c_str(), PIPE_ACCESS_OUTBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE | FILE_FLAG_OVERLAPPED,
                    PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, 1, 4096, 4096, 0, &attributes);
                if (pipe_.value == INVALID_HANDLE_VALUE) return Error();
                stop_.value = CreateEventW(nullptr, TRUE, FALSE, nullptr); if (!stop_.value) return Error();
                done_.value = CreateEventW(nullptr, TRUE, FALSE, nullptr); return done_.value ? S_OK : Error();
            }
            void Stop() noexcept
            {
                stopped_.store(true); if (stop_.value) SetEvent(stop_.value);
                if (pipe_.value && pipe_.value != INVALID_HANDLE_VALUE) CancelIoEx(pipe_.value, nullptr);
            }
            HRESULT Send(const BYTE* bytes, DWORD size) noexcept
            {
                HRESULT hr = Check(); if (FAILED(hr)) return hr;
                const auto deadline = GetTickCount64() + 250;
                if (!connected_)
                {
                    OVERLAPPED op{}; op.hEvent = done_.value; ResetEvent(done_.value);
                    if (!ConnectNamedPipe(pipe_.value, &op))
                    {
                        const DWORD error = GetLastError();
                        if (error == ERROR_IO_PENDING) { DWORD ignored = 0; hr = Complete(op, deadline, ignored); }
                        else if (error != ERROR_PIPE_CONNECTED) hr = HRESULT_FROM_WIN32(error);
                    }
                    if (FAILED(hr)) return hr;
                    ULONG actual = 0; if (!GetNamedPipeClientProcessId(pipe_.value, &actual)) return Error();
                    if (!actual || actual != GetProcessId(child_)) return E_ACCESSDENIED;
                    connected_ = true;
                }
                hr = Check(); if (FAILED(hr)) return hr;
                OVERLAPPED op{}; op.hEvent = done_.value; ResetEvent(done_.value); DWORD written = 0;
                if (!WriteFile(pipe_.value, bytes, size, &written, &op))
                {
                    const DWORD error = GetLastError();
                    hr = error == ERROR_IO_PENDING ? Complete(op, deadline, written) : HRESULT_FROM_WIN32(error);
                }
                if (FAILED(hr)) return hr;
                if (written != size) return E_UNEXPECTED;
                hr = Check(); return FAILED(hr) ? hr : GetTickCount64() >= deadline ? HRESULT_FROM_WIN32(ERROR_TIMEOUT) : S_OK;
            }
            ~DataPipe() { Stop(); } // Parent serializes and joins its caller before destruction.
        private:
            HRESULT Check() noexcept
            {
                if (stopped_.load()) return MF_E_SHUTDOWN;
                if (WaitForSingleObject(child_, 0) != WAIT_TIMEOUT) return HRESULT_FROM_WIN32(ERROR_BROKEN_PIPE);
                return current_(context_);
            }
            HRESULT Complete(OVERLAPPED& op, ULONGLONG deadline, DWORD& bytes) noexcept
            {
                HRESULT hr = S_OK;
                for (;;)
                {
                    hr = Check(); if (FAILED(hr)) break;
                    if (GetTickCount64() >= deadline) { hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT); break; }
                    const HANDLE waits[] = {stop_.value, child_, done_.value};
                    const DWORD wait = WaitForMultipleObjects(3, waits, FALSE, 5);
                    if (wait == WAIT_OBJECT_0 || wait == WAIT_OBJECT_0 + 1) { hr = MF_E_SHUTDOWN; break; }
                    if (wait == WAIT_FAILED) { hr = Error(); break; }
                    if (wait == WAIT_OBJECT_0 + 2) return GetOverlappedResult(pipe_.value, &op, &bytes, FALSE) ? S_OK : Error();
                }
                CancelIoEx(pipe_.value, &op); DWORD ignored = 0; GetOverlappedResult(pipe_.value, &op, &ignored, TRUE); return hr;
            }
            const HANDLE child_;
            const Current current_;
            void* const context_;
            Handle pipe_, stop_, done_;
            std::atomic_bool stopped_{false};
            bool connected_ = false;
        };
        class ParentSession final
        {
        public:
            ParentSession(const GUID& scope, std::shared_ptr<RuntimeImage> image, const MagnoliePhoneAudioOwnerV1& owner) noexcept :
                owner_(owner), image_(std::move(image)), scope_(scope), clock_({Current, Sending, Failed, this, nullptr, nullptr})
            {
                // Immutable before registration: Stop must never race a handle
                // assignment while Prepare is constructing child resources.
                wake_.value = CreateEventW(nullptr, TRUE, FALSE, nullptr);
                controlReady_.value = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            }
            static HRESULT Current(void* context) noexcept { return static_cast<ParentSession*>(context)->Check(false); }
            static HRESULT Sending(void* context) noexcept { return static_cast<ParentSession*>(context)->Check(true); }
            static void Failed(void* context, HRESULT reason) noexcept { static_cast<ParentSession*>(context)->Fail(reason); }
            HRESULT Fail(HRESULT reason) noexcept
            {
                if (!stopped_.exchange(true)) { Signals(); owner_.failed(owner_.context, reason); }
                return reason;
            }
            void Stop() noexcept { if (!stopped_.exchange(true)) Signals(); }
            HRESULT Check(bool sending) noexcept
            {
                if (stopped_.load()) return MF_E_SHUTDOWN;
                if (!wake_.value || !controlReady_.value) return Fail(E_OUTOFMEMORY);
                HRESULT hr = owner_.current(owner_.context);
                if (hr != S_OK) return Fail(FAILED(hr) ? hr : E_ACCESSDENIED);
                if (sending) { hr = owner_.sending(owner_.context); if (hr != S_OK) return FAILED(hr) ? hr : E_ACCESSDENIED; }
                return stopped_.load() ? MF_E_SHUTDOWN : S_OK;
            }
            HRESULT Prepare()
            {
                std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
                if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
                HRESULT hr = Check(false); if (FAILED(hr)) return hr;
                if (started_) return Fail(E_INVALIDARG); started_ = true;
                GUID audio{}, anchor{}; hr = CoCreateGuid(&audio); if (SUCCEEDED(hr)) hr = CoCreateGuid(&anchor); if (FAILED(hr)) return Fail(hr);
                hr = RuntimeProcess::Create(image_, scope_, audio, anchor, {Current, Failed, this, nullptr}, runtime_); if (FAILED(hr)) return Fail(hr);
                runtimeSignal_.store(runtime_.get()); if (stopped_.load()) { Signals(); return MF_E_SHUTDOWN; }
                hr = OutputPublisher::Create(scope_, runtime_->Child(), {Current, RawSending, Failed, this, nullptr, nullptr}, control_); if (FAILED(hr)) return Fail(hr);
                controlSignal_.store(control_.get());
                hr = RuntimeStatus::Create(scope_, runtime_.get(), status_); if (FAILED(hr)) return Fail(hr);
                statusSignal_.store(status_.get());
                audio_ = std::make_unique<DataPipe>(runtime_->Child(), Sending, this); hr = audio_->Open(audio); if (FAILED(hr)) return Fail(hr);
                audioSignal_.store(audio_.get());
                anchor_ = std::make_unique<DataPipe>(runtime_->Child(), Sending, this); hr = anchor_->Open(anchor); if (FAILED(hr)) return Fail(hr);
                anchorSignal_.store(anchor_.get());
                hr = Check(false); if (FAILED(hr)) return hr;
                publisher_ = std::thread([this] {
                    HRESULT result = control_->Accept();
                    while (SUCCEEDED(result) && !stopped_.load())
                    {
                        result = control_->Publish();
                        if (SUCCEEDED(result)) { controlAt_.store(GetTickCount64()); SetEvent(controlReady_.value); }
                        if (FAILED(result) || WaitForSingleObject(wake_.value, 40) != WAIT_TIMEOUT) break;
                    }
                    if (FAILED(result)) Fail(result);
                });
                hr = runtime_->Resume(); if (FAILED(hr)) return Fail(hr);
                const HANDLE initial[] = {wake_.value, runtime_->Child(), controlReady_.value};
                if (WaitForMultipleObjects(3, initial, FALSE, 2000) != WAIT_OBJECT_0 + 2) return Fail(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
                hr = status_->WaitPrepared(); if (FAILED(hr)) return Fail(hr);
                hr = Check(false); if (FAILED(hr)) return hr;
                prepared_.store(true); return Ready();
            }
            HRESULT Ready() noexcept
            {
                HRESULT hr = Check(false); if (FAILED(hr)) return hr;
                if (!prepared_.load()) return E_ACCESSDENIED;
                auto* child = runtimeSignal_.load(); const auto at = controlAt_.load(), now = GetTickCount64();
                if (!child || child->IsRetired() || WaitForSingleObject(child->Child(), 0) != WAIT_TIMEOUT || !at || now < at || now - at >= 250)
                    return Fail(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
                return S_OK;
            }
            HRESULT ObserveVideo(LONGLONG pts, LONGLONG* mapped)
            {
                if (!mapped) return E_POINTER; *mapped = 0;
                std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
                if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
                HRESULT hr = Ready(); if (SUCCEEDED(hr)) hr = Check(true);
                if (SUCCEEDED(hr)) hr = Map(pts, mapped);
                return FAILED(hr) ? Fail(hr) : S_OK;
            }
            HRESULT Write(const BYTE* bytes, DWORD size)
            {
                std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
                if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
                HRESULT hr = Ready(); if (SUCCEEDED(hr)) hr = Check(true); if (FAILED(hr)) return Fail(hr);
                if (!bytes || size != Samples::AudioRecordBytes) return Fail(E_INVALIDARG);
                std::array<BYTE, Samples::AudioRecordBytes> record{}; std::memcpy(record.data(), bytes, size);
                struct Clear { BYTE* data; std::size_t size; ~Clear() { SecureZeroMemory(data, size); } } clear{record.data(), record.size()};
                const auto sequence = Integer(record.data() + 2), pts = Integer(record.data() + 10);
                if (record[0] != 1 || record[1] != 2 || sequence != audioSequence_ || sequence >= static_cast<ULONGLONG>((std::numeric_limits<LONGLONG>::max)()) ||
                    pts > 9007199254740991ULL || (seenAudio_ && pts <= audioPts_)) return Fail(E_INVALIDARG);
                LONGLONG mapped = 0; hr = Map(static_cast<LONGLONG>(pts), &mapped); if (FAILED(hr)) return Fail(hr);
                ULONGLONG token = 0; hr = runtime_->BeginOperation(&token);
                if (SUCCEEDED(hr)) hr = audio_->Send(record.data(), static_cast<DWORD>(record.size()));
                if (SUCCEEDED(hr)) hr = status_->WaitWritten(token);
                if (SUCCEEDED(hr)) hr = Check(true);
                if (FAILED(hr)) return Fail(hr);
                ++audioSequence_; audioPts_ = pts; seenAudio_ = true; return S_OK;
            }
            HRESULT Export(BYTE* target, DWORD size)
            {
                std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
                if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
                HRESULT hr = Ready(); if (SUCCEEDED(hr)) hr = Check(true);
                if (SUCCEEDED(hr)) hr = clock_.ExportAnchor(scope_, target, size);
                return FAILED(hr) ? Fail(hr) : S_OK;
            }
            HRESULT Close() noexcept
            {
                Stop(); clock_.Stop(); // Retire while callback context/members are still alive.
                std::lock_guard<std::mutex> lock(gate_);
                if (publisher_.joinable()) publisher_.join();
                return runtime_ ? runtime_->WaitStopped(5000) : S_OK;
            }
            ~ParentSession() { Close(); }
        private:
            static HRESULT RawSending(void* context) noexcept
            {
                auto& self = *static_cast<ParentSession*>(context);
                HRESULT hr = self.Check(false); return FAILED(hr) ? hr : self.owner_.sending(self.owner_.context);
            }
            void Signals() noexcept
            {
                prepared_.store(false); if (wake_.value) SetEvent(wake_.value);
                if (auto* value = audioSignal_.load()) value->Stop();
                if (auto* value = anchorSignal_.load()) value->Stop();
                if (auto* value = statusSignal_.load()) value->Stop();
                if (auto* value = controlSignal_.load()) value->Stop();
                if (auto* value = runtimeSignal_.load()) value->Stop();
            }
            HRESULT Map(LONGLONG pts, LONGLONG* mapped) noexcept
            {
                HRESULT hr = clock_.Map(pts, mapped); if (FAILED(hr)) return hr;
                if (!anchorSent_)
                {
                    std::array<BYTE, PresentationClock::AnchorBytes> epoch{};
                    hr = clock_.ExportAnchor(scope_, epoch.data(), epoch.size());
                    if (SUCCEEDED(hr)) hr = anchor_->Send(epoch.data(), static_cast<DWORD>(epoch.size()));
                    SecureZeroMemory(epoch.data(), epoch.size()); if (FAILED(hr)) { *mapped = 0; return hr; }
                    anchorSent_ = true;
                }
                return S_OK;
            }
            const MagnoliePhoneAudioOwnerV1 owner_;
            const std::shared_ptr<RuntimeImage> image_;
            const GUID scope_;
            PresentationClock clock_;
            std::mutex gate_;
            Handle wake_, controlReady_;
            std::atomic_bool stopped_{false}, prepared_{false};
            std::atomic<ULONGLONG> controlAt_{0};
            std::unique_ptr<RuntimeProcess> runtime_;
            std::unique_ptr<OutputPublisher> control_;
            std::unique_ptr<RuntimeStatus> status_;
            std::unique_ptr<DataPipe> audio_, anchor_;
            std::atomic<RuntimeProcess*> runtimeSignal_{nullptr};
            std::atomic<OutputPublisher*> controlSignal_{nullptr};
            std::atomic<RuntimeStatus*> statusSignal_{nullptr};
            std::atomic<DataPipe*> audioSignal_{nullptr}, anchorSignal_{nullptr};
            std::thread publisher_;
            bool started_ = false, anchorSent_ = false, seenAudio_ = false;
            ULONGLONG audioSequence_ = 0, audioPts_ = 0;
        };
        std::mutex registryGate;
        std::unordered_map<ULONGLONG, std::shared_ptr<ParentSession>> registry;
        ULONGLONG nextHandle = 1;
        bool creating = false;
        bool OwnerValid(const MagnoliePhoneAudioOwnerV1* owner) noexcept
        { return owner && owner->size == sizeof(MagnoliePhoneAudioOwnerV1) && owner->version == 1 && owner->current && owner->sending && owner->failed; }
        std::shared_ptr<ParentSession> Find(ULONGLONG handle)
        { std::lock_guard<std::mutex> lock(registryGate); auto found = registry.find(handle); return found == registry.end() ? nullptr : found->second; }
        template<class Work> HRESULT Call(ULONGLONG handle, Work work) noexcept
        {
            try { auto session = Find(handle); return session ? work(*session) : E_INVALIDARG; }
            catch (...) { try { if (auto session = Find(handle)) session->Fail(E_FAIL); } catch (...) {} return E_FAIL; }
        }
        HRESULT Register(const GUID& scope, const std::shared_ptr<RuntimeImage>& image, const MagnoliePhoneAudioOwnerV1& owner, ULONGLONG* result)
        {
            auto session = std::make_shared<ParentSession>(scope, image, owner);
            HRESULT hr = session->Check(false); if (FAILED(hr)) return hr;
            std::lock_guard<std::mutex> lock(registryGate);
            if (!registry.empty() || nextHandle == (std::numeric_limits<ULONGLONG>::max)()) return HRESULT_FROM_WIN32(ERROR_BUSY);
            const auto handle = nextHandle++; registry.emplace(handle, std::move(session)); *result = handle; return S_OK;
        }
    }
#ifdef MAGNOLIE_NATIVE_AUDIO_PARENT_TESTS
    HRESULT AudioParentCreateTestImage(const GUID& scope, const std::shared_ptr<RuntimeImage>& image, const MagnoliePhoneAudioOwnerV1& owner, ULONGLONG* result) noexcept
    {
        if (!result || !image || scope == GUID_NULL || !OwnerValid(&owner)) return E_INVALIDARG;
        *result = 0; try { return Register(scope, image, owner, result); } catch (...) { return E_FAIL; }
    }
#endif
}
using namespace Magnolie::PhoneCamera;
DWORD __cdecl MagnoliePhoneAudioVersion() noexcept { return 1; }
HRESULT __cdecl MagnoliePhoneAudioCreate(const GUID* scope, const BYTE* digest, DWORD bytes, const MagnoliePhoneAudioOwnerV1* owner, ULONGLONG* result) noexcept
{
    if (!result) return E_POINTER; *result = 0;
    if (!scope || *scope == GUID_NULL || !digest || bytes != 32 || !OwnerValid(owner)) return E_INVALIDARG;
    try
    {
        const HRESULT current = owner->current(owner->context); if (current != S_OK) return FAILED(current) ? current : E_ACCESSDENIED;
        { std::lock_guard<std::mutex> lock(registryGate); if (creating || !registry.empty()) return HRESULT_FROM_WIN32(ERROR_BUSY); creating = true; }
        struct Release { ~Release() { std::lock_guard<std::mutex> lock(registryGate); creating = false; } } release;
        std::array<BYTE, 32> expected{}; std::memcpy(expected.data(), digest, expected.size());
        std::shared_ptr<RuntimeImage> image; HRESULT hr = RuntimeImage::VerifySibling(expected, image);
        return FAILED(hr) ? hr : Register(*scope, image, *owner, result);
    }
    catch (...) { return E_FAIL; }
}
HRESULT __cdecl MagnoliePhoneAudioPrepare(ULONGLONG handle) noexcept { return Call(handle, [](ParentSession& session) { return session.Prepare(); }); }
HRESULT __cdecl MagnoliePhoneAudioRequireReady(ULONGLONG handle) noexcept { return Call(handle, [](ParentSession& session) { return session.Ready(); }); }
HRESULT __cdecl MagnoliePhoneAudioObserveVideo(ULONGLONG handle, LONGLONG pts, LONGLONG* mapped) noexcept
{ if (mapped) *mapped = 0; return Call(handle, [&](ParentSession& session) { return session.ObserveVideo(pts, mapped); }); }
HRESULT __cdecl MagnoliePhoneAudioWrite(ULONGLONG handle, const BYTE* record, DWORD bytes) noexcept { return Call(handle, [&](ParentSession& session) { return session.Write(record, bytes); }); }
HRESULT __cdecl MagnoliePhoneAudioExportAnchor(ULONGLONG handle, BYTE* record, DWORD bytes) noexcept { return Call(handle, [&](ParentSession& session) { return session.Export(record, bytes); }); }
HRESULT __cdecl MagnoliePhoneAudioStop(ULONGLONG handle) noexcept { return Call(handle, [](ParentSession& session) { session.Stop(); return S_OK; }); }
HRESULT __cdecl MagnoliePhoneAudioClose(ULONGLONG handle) noexcept
{
    return Call(handle, [&](ParentSession& session) {
        const HRESULT hr = session.Close(); if (FAILED(hr)) return hr;
        std::lock_guard<std::mutex> lock(registryGate); registry.erase(handle); return S_OK;
    });
}
