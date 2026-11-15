#include "PhoneCameraVideoParent.h"
#include "PhoneCameraSourceBrokerParent.h"
#include "PhoneCameraClock.h"
#include "PhoneCameraSamples.h"
#include <mfapi.h>
#include <wrl.h>
#include <array>
#include <cstring>
#include <unordered_map>
#include <vector>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        HRESULT Exact(HRESULT hr) noexcept { return hr == S_OK ? S_OK : FAILED(hr) ? hr : E_ACCESSDENIED; }
        HRESULT Error() noexcept { return HRESULT_FROM_WIN32(GetLastError()); }
        ULONGLONG Integer(const BYTE* bytes) noexcept
        { ULONGLONG value = 0; for (unsigned int i = 0; i < 8; ++i) value = (value << 8) | bytes[i]; return value; }
        class VideoSession final : public Microsoft::WRL::RuntimeClass<
            Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, IUnknown>
        {
        public:
            VideoSession(const GUID& scope, const MagnoliePhoneVideoOwnerV1& owner) noexcept
                : scope_(scope), owner_(owner), mutedClock_({Current, Sending, Failed, this, nullptr, nullptr}) {}
            ~VideoSession()
            {
                Stop(); mutedClock_.Stop(); // Callbacks only while every member still exists.
                // Registry/worker/camera/broker retain this original until all
                // cleanup is confirmed. No last-Release lifecycle SDK calls.
                if (worker_) CloseHandle(worker_);
                if (stop_) CloseHandle(stop_);
                if (preparedEvent_) CloseHandle(preparedEvent_);
            }
            HRESULT Initialize() noexcept
            {
                HRESULT hr = Check(false); if (FAILED(hr)) return hr;
                stop_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
                preparedEvent_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
                return stop_ && preparedEvent_ ? S_OK : Error();
            }
            static HRESULT Current(void* context) noexcept { return static_cast<VideoSession*>(context)->Check(false); }
            static HRESULT Sending(void* context) noexcept { return static_cast<VideoSession*>(context)->Check(true); }
            static HRESULT RawSending(void* context) noexcept
            {
                auto& self = *static_cast<VideoSession*>(context);
                HRESULT hr = self.Check(false); return FAILED(hr) ? hr : self.owner_.sending(self.owner_.context);
            }
            static HRESULT Registration(void* context) noexcept
            {
                auto& self = *static_cast<VideoSession*>(context);
                // Never consult capture/SEND here: the original transport must
                // still drain its terminal Source receipt after capture stops.
                return self.registrationEnded_.load() ? MF_E_SHUTDOWN : Exact(self.owner_.registration(self.owner_.context));
            }
            static void Failed(void* context, HRESULT reason) noexcept { static_cast<VideoSession*>(context)->Fail(reason); }
            HRESULT Check(bool sending) noexcept
            {
                if (stopped_.load()) return MF_E_SHUTDOWN;
                HRESULT hr = Exact(owner_.current(owner_.context));
                if (FAILED(hr)) return Fail(hr);
                if (sending) hr = Exact(owner_.sending(owner_.context));
                return FAILED(hr) ? hr : stopped_.load() ? MF_E_SHUTDOWN : S_OK;
            }
            HRESULT Fail(HRESULT reason) noexcept
            {
                if (!stopped_.exchange(true)) { if (stop_) SetEvent(stop_); owner_.failed(owner_.context, reason); }
                return reason;
            }
            void Stop() noexcept { stopped_.store(true); if (stop_) SetEvent(stop_); }
            HRESULT Prepare() noexcept
            {
                {
                    std::lock_guard<std::mutex> lock(lifecycle_);
                    if (prepareCalled_ || closeCalled_) return E_INVALIDARG;
                    prepareCalled_ = true;
                    HRESULT hr = Check(false); if (FAILED(hr)) return hr;
                    AddRef();
                    worker_ = CreateThread(nullptr, 0, ThreadMain, this, 0, nullptr);
                    if (!worker_) { hr = Error(); Release(); return Fail(hr); }
                }
                // Await the ORIGINAL OS call even on cancellation, never detach
                // a late Start/property continuation or retry unknown outcomes.
                if (WaitForSingleObject(preparedEvent_, INFINITE) != WAIT_OBJECT_0) return Fail(Error());
                HRESULT hr = prepareResult_.load();
                return FAILED(hr) ? hr : Check(false); // Binding is not media Ready.
            }
            HRESULT Ready() noexcept
            {
                std::lock_guard<std::mutex> lock(media_);
                HRESULT hr = Check(false); if (FAILED(hr)) return hr;
                return broker_ ? broker_->RequireActive() : MF_E_NOT_INITIALIZED;
            }
            static HRESULT Export(void* context, BYTE* record, DWORD bytes) noexcept
            {
                auto& self = *static_cast<VideoSession*>(context);
                HRESULT hr = self.Check(true); if (FAILED(hr)) return hr;
                hr = self.owner_.flags == 1 ? self.mutedClock_.ExportAnchor(self.scope_, record, bytes) :
                    Exact(self.owner_.exportAnchor(self.owner_.context, record, bytes));
                return FAILED(hr) ? hr : self.Check(true);
            }
            HRESULT Write(const BYTE* bytes, DWORD size)
            {
                std::unique_lock<std::mutex> lock(media_, std::try_to_lock);
                if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
                HRESULT hr = Check(true); if (FAILED(hr)) return Fail(hr);
                if (!broker_) return Fail(MF_E_NOT_INITIALIZED);
                hr = broker_->RequireActive(); if (FAILED(hr)) return Fail(hr);
                if (!bytes || size != 18 + Samples::VideoBytes) return Fail(E_INVALIDARG);
                std::vector<BYTE> record(bytes, bytes + size);
                struct Clear { std::vector<BYTE>& bytes; ~Clear() { SecureZeroMemory(bytes.data(), bytes.size()); } } clear{record};
                const auto sequence = Integer(record.data() + 2), pts = Integer(record.data() + 10);
                if (record[0] != 1 || record[1] != 1 || sequence != sequence_ ||
                    sequence >= static_cast<ULONGLONG>((std::numeric_limits<LONGLONG>::max)()) ||
                    pts > 9007199254740991ULL || (seen_ && pts <= lastPts_)) return Fail(E_INVALIDARG);
                LONGLONG mapped = 0;
                hr = owner_.flags == 1 ? mutedClock_.Map(static_cast<LONGLONG>(pts), &mapped) :
                    Exact(owner_.observeVideo(owner_.context, static_cast<LONGLONG>(pts), &mapped));
                if (SUCCEEDED(hr)) hr = Check(true);
                // Preserve original PTS/sequence; Source imports this SAME epoch,
                // not the mapped PTS as a second independently anchored input.
                if (SUCCEEDED(hr)) hr = broker_->WriteVideo(record.data(), size);
                if (SUCCEEDED(hr)) hr = Check(true);
                if (FAILED(hr)) return Fail(hr);
                ++sequence_; lastPts_ = pts; seen_ = true; return S_OK;
            }
            HRESULT Close() noexcept
            {
                std::lock_guard<std::mutex> lock(lifecycle_);
                if (closeCalled_) return closeResult_;
                closeCalled_ = true; Stop();
                if (!worker_) { mutedClock_.Stop(); registrationEnded_.store(true); }
                if (worker_ && WaitForSingleObject(worker_, INFINITE) != WAIT_OBJECT_0) closeResult_ = Error();
                else closeResult_ = worker_ ? cleanupResult_.load() : S_OK;
                return closeResult_;
            }
        private:
            static DWORD WINAPI ThreadMain(void* context) noexcept
            {
                auto& self = *static_cast<VideoSession*>(context);
                HRESULT com = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
                HRESULT hr = com;
                if (SUCCEEDED(hr)) hr = CoIncrementMTAUsage(&self.mta_);
                if (SUCCEEDED(hr)) { hr = MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET); self.mf_ = SUCCEEDED(hr); }
                if (SUCCEEDED(hr))
                {
                    try { hr = self.StartOriginal(); }
                    catch (...) { hr = E_FAIL; }
                }
                self.prepareResult_.store(hr); SetEvent(self.preparedEvent_);
                if (SUCCEEDED(hr)) WaitForSingleObject(self.stop_, INFINITE);
                else self.Fail(hr);
                HRESULT cleanup = self.Cleanup();
                if (SUCCEEDED(cleanup))
                {
                    if (self.mf_)
                    {
                        cleanup = Exact(MFShutdown());
                        if (cleanup == S_OK) self.mf_ = false;
                    }
                    if (cleanup == S_OK && self.mta_)
                    {
                        cleanup = Exact(CoDecrementMTAUsage(self.mta_));
                        if (cleanup == S_OK) self.mta_ = nullptr;
                    }
                }
                self.cleanupResult_.store(cleanup);
                // On unknown cleanup keep the original MF reference/MTA cookie
                // with the registered root. No replacement, unload or live worker
                // remains; callbacks/module are retained by the C ABI registry.
                if (SUCCEEDED(com)) CoUninitialize();
                self.Release(); return 0; // Registry still holds the root until joined Close.
            }
            HRESULT StartOriginal()
            {
                std::lock_guard<std::mutex> lock(media_);
                HRESULT hr = Check(false); if (FAILED(hr)) return hr;
                hr = Registration(this); if (FAILED(hr)) return hr;
                std::unique_ptr<VirtualCamera> camera;
                hr = VirtualCamera::Create({Registration, this, this}, camera); if (FAILED(hr)) return hr;
                camera_ = std::move(camera);
                hr = Check(false); if (SUCCEEDED(hr)) hr = camera_->Start();
                if (SUCCEEDED(hr)) hr = Check(false);
                if (SUCCEEDED(hr)) hr = SourceBrokerParent::Prepare(scope_, camera_,
                    {{Current, RawSending, Failed, this, this, nullptr}, Export}, broker_);
                if (SUCCEEDED(hr)) hr = Check(false);
                return hr;
            }
            HRESULT Cleanup() noexcept
            {
                Stop();
                std::lock_guard<std::mutex> lock(media_);
                HRESULT hr = broker_ ? broker_->Close() : S_OK;
                if (FAILED(hr)) return hr; // Keep exact camera/Source/module; never close before ACK.
                broker_.reset();
                hr = camera_ ? camera_->Close() : S_OK;
                if (FAILED(hr)) return hr;
                camera_.reset(); mutedClock_.Stop(); registrationEnded_.store(true); return S_OK;
            }
            const GUID scope_;
            const MagnoliePhoneVideoOwnerV1 owner_;
            PresentationClock mutedClock_;
            std::shared_ptr<VirtualCamera> camera_;
            std::unique_ptr<SourceBrokerParent> broker_;
            std::mutex lifecycle_, media_;
            HANDLE stop_ = nullptr, preparedEvent_ = nullptr, worker_ = nullptr;
            CO_MTA_USAGE_COOKIE mta_ = nullptr;
            bool mf_ = false, prepareCalled_ = false, closeCalled_ = false, seen_ = false;
            HRESULT closeResult_ = S_OK;
            ULONGLONG sequence_ = 0, lastPts_ = 0;
            std::atomic_bool stopped_{false}, registrationEnded_{false};
            std::atomic<HRESULT> prepareResult_{E_PENDING}, cleanupResult_{E_PENDING};
        };
        std::mutex videoRegistryGate;
        std::unordered_map<ULONGLONG, Microsoft::WRL::ComPtr<VideoSession>> videoRegistry;
        ULONGLONG nextVideoHandle = 1;
        bool Valid(const MagnoliePhoneVideoOwnerV1& owner) noexcept
        {
            return owner.size == sizeof(owner) && owner.version == 1 && owner.flags <= 1 && !owner.reserved &&
                owner.current && owner.sending && owner.failed && owner.registration &&
                (owner.flags == 1 ? !owner.observeVideo && !owner.exportAnchor : owner.observeVideo && owner.exportAnchor);
        }
        template<class Work> HRESULT VideoCall(ULONGLONG handle, Work work) noexcept
        {
            Microsoft::WRL::ComPtr<VideoSession> session;
            try
            {
                { std::lock_guard<std::mutex> lock(videoRegistryGate); auto it = videoRegistry.find(handle); if (it != videoRegistry.end()) session = it->second; }
                return session ? work(*session.Get()) : E_INVALIDARG;
            }
            catch (...) { if (session) session->Fail(E_FAIL); return E_FAIL; }
        }
    }
}
using namespace Magnolie::PhoneCamera;
DWORD __cdecl MagnoliePhoneVideoVersion() noexcept { return 1; }
HRESULT __cdecl MagnoliePhoneVideoCreate(const GUID* scope, const MagnoliePhoneVideoOwnerV1* supplied, ULONGLONG* result) noexcept
{
    if (!result) return E_POINTER; *result = 0;
    if (!scope || *scope == GUID_NULL || !supplied) return E_INVALIDARG;
    const auto owner = *supplied;
    if (!Valid(owner)) return E_INVALIDARG;
    HRESULT hr = Exact(owner.current(owner.context)); if (FAILED(hr)) return hr;
    hr = Exact(owner.registration(owner.context)); if (FAILED(hr)) return hr;
    try
    {
        auto session = Microsoft::WRL::Make<VideoSession>(*scope, owner); if (!session) return E_OUTOFMEMORY;
        hr = session->Initialize(); if (FAILED(hr)) return hr;
        std::lock_guard<std::mutex> lock(videoRegistryGate);
        if (!videoRegistry.empty() || nextVideoHandle == (std::numeric_limits<ULONGLONG>::max)()) return HRESULT_FROM_WIN32(ERROR_BUSY);
        const auto handle = nextVideoHandle++; videoRegistry.emplace(handle, std::move(session)); *result = handle; return S_OK;
    }
    catch (...) { return E_FAIL; }
}
HRESULT __cdecl MagnoliePhoneVideoPrepare(ULONGLONG handle) noexcept { return VideoCall(handle, [](VideoSession& s) { return s.Prepare(); }); }
HRESULT __cdecl MagnoliePhoneVideoRequireReady(ULONGLONG handle) noexcept { return VideoCall(handle, [](VideoSession& s) { return s.Ready(); }); }
HRESULT __cdecl MagnoliePhoneVideoWrite(ULONGLONG handle, const BYTE* record, DWORD bytes) noexcept
{ return VideoCall(handle, [&](VideoSession& s) { return s.Write(record, bytes); }); }
HRESULT __cdecl MagnoliePhoneVideoStop(ULONGLONG handle) noexcept { return VideoCall(handle, [](VideoSession& s) { s.Stop(); return S_OK; }); }
HRESULT __cdecl MagnoliePhoneVideoClose(ULONGLONG handle) noexcept
{
    return VideoCall(handle, [&](VideoSession& s) {
        HRESULT hr = s.Close(); if (FAILED(hr)) return hr;
        std::lock_guard<std::mutex> lock(videoRegistryGate); videoRegistry.erase(handle); return S_OK;
    });
}
