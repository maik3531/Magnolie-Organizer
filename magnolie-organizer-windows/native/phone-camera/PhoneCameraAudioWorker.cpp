#include "PhoneCameraAudioWorker.h"
#include "PhoneCameraAudioRender.h"
#include "PhoneCameraOutputLease.h"
#include "PhoneCameraOutputPublisher.h"
#include "PhoneCameraRuntimeStatus.h"
#include "PhoneCameraRelay.h"
#include <mfapi.h>
#include <mferror.h>
#include <objbase.h>
#include <tlhelp32.h>
#include <array>
#include <cwchar>
#include <limits>
#include <thread>

namespace Magnolie::PhoneCamera
{
#ifdef MAGNOLIE_NATIVE_AUDIO_WORKER_TESTS
    static std::atomic_uint testStage{0};
    unsigned int AudioWorkerTestStage() noexcept { return testStage.load(); }
#endif
    namespace
    {
        struct Handle { HANDLE value = nullptr; ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); } };
        struct Context
        {
            Handle parent, parentStop, localStop;
            std::atomic_bool retired{false};
            static void Retire(void* value, HRESULT) noexcept
            { auto& c = *static_cast<Context*>(value); c.retired.store(true); if (c.localStop.value) SetEvent(c.localStop.value); }
            static HRESULT Current(void* value) noexcept
            {
                auto& c = *static_cast<Context*>(value);
                if (c.retired.load()) return MF_E_SHUTDOWN;
                const HANDLE waits[] = {c.localStop.value, c.parentStop.value, c.parent.value};
                const DWORD wait = WaitForMultipleObjects(3, waits, FALSE, 0);
                return wait == WAIT_TIMEOUT ? S_OK : E_ACCESSDENIED;
            }
        };
        struct Media
        {
            bool com = false, mf = false;
            HRESULT Start() noexcept
            {
                HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED); if (FAILED(hr)) return hr;
                com = true; hr = MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET); mf = SUCCEEDED(hr); return hr;
            }
            ~Media() { if (mf) MFShutdown(); if (com) CoUninitialize(); }
        };
        bool Scope(const wchar_t* text, GUID& scope) noexcept
        {
            if (!text || wcsnlen_s(text, 40) != 38 || FAILED(CLSIDFromString(text, &scope)) || scope == GUID_NULL) return false;
            wchar_t canonical[40]{};
            return StringFromGUID2(scope, canonical, 40) && !std::wcscmp(text, canonical);
        }
        bool Parent(const wchar_t* text, HANDLE& parent) noexcept
        {
            if (!text || !*text || *text == L'0' || wcsnlen_s(text, 21) > 20) return false;
            ULONG_PTR value = 0;
            for (const wchar_t* c = text; *c; ++c)
            {
                if (*c < L'0' || *c > L'9' || value > ((std::numeric_limits<ULONG_PTR>::max)() - static_cast<ULONG_PTR>(*c - L'0')) / 10) return false;
                value = value * 10 + static_cast<ULONG_PTR>(*c - L'0');
            }
            parent = reinterpret_cast<HANDLE>(value); DWORD flags = 0;
            if (!GetHandleInformation(parent, &flags) || !(flags & HANDLE_FLAG_INHERIT) || WaitForSingleObject(parent, 0) != WAIT_TIMEOUT) return false;
            const DWORD pid = GetProcessId(parent), self = GetCurrentProcessId();
            if (!pid || pid == self) return false;
            Handle snapshot; snapshot.value = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if (snapshot.value == INVALID_HANDLE_VALUE) return false;
            PROCESSENTRY32W entry{}; entry.dwSize = sizeof(entry);
            if (Process32FirstW(snapshot.value, &entry)) do
            {
                if (entry.th32ProcessID == self) return entry.th32ParentProcessID == pid;
            } while (Process32NextW(snapshot.value, &entry));
            return false;
        }
        bool Guarded() noexcept
        {
            BOOL assigned = FALSE; JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
            return IsProcessInJob(GetCurrentProcess(), nullptr, &assigned) && assigned &&
                QueryInformationJobObject(nullptr, JobObjectExtendedLimitInformation, &limits, sizeof(limits), nullptr) &&
                (limits.BasicLimitInformation.LimitFlags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) &&
                (limits.BasicLimitInformation.LimitFlags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS) &&
                (limits.BasicLimitInformation.LimitFlags & JOB_OBJECT_LIMIT_PROCESS_MEMORY) &&
                limits.BasicLimitInformation.ActiveProcessLimit == 1 && limits.ProcessMemoryLimit > 0 && limits.ProcessMemoryLimit <= 256 * 1024 * 1024;
        }
        class Reports final
        {
        public:
            HRESULT Connect(const GUID& scope, Context& context, OutputLease& lease) noexcept
            {
                context_ = &context; lease_ = &lease;
                HRESULT hr = Current(false); if (FAILED(hr)) return hr;
                pipe_.value = CreateFileW(RuntimeStatus::Name(scope).c_str(), GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
                if (pipe_.value == INVALID_HANDLE_VALUE) return HRESULT_FROM_WIN32(GetLastError());
                ULONG server = 0;
                if (!GetNamedPipeServerProcessId(pipe_.value, &server)) return HRESULT_FROM_WIN32(GetLastError());
                if (!server || server != GetProcessId(context.parent.value)) return E_ACCESSDENIED;
                completed_.value = CreateEventW(nullptr, TRUE, FALSE, nullptr);
                return completed_.value ? Current(false) : HRESULT_FROM_WIN32(GetLastError());
            }
            HRESULT Ready(AudioRender& renderer) noexcept
            {
                if (renderer.IsRetired() || sequence_) return E_ACCESSDENIED;
                return Send(1, 0); // Only called below AFTER actual AudioRender::Open succeeded.
            }
            HRESULT Written(ULONGLONG token) noexcept
            {
                if (!sequence_ || token != sequence_) return E_INVALIDARG;
                return Send(2, token); // Only called below AFTER actual renderer.Write succeeded.
            }
        private:
            HRESULT Current(bool sending) noexcept
            {
                HRESULT hr = Context::Current(context_); if (FAILED(hr)) return hr;
                return sending ? lease_->RequireSending() : lease_->RequireCurrent();
            }
            HRESULT Send(BYTE phase, ULONGLONG token) noexcept
            {
                HRESULT hr = Current(phase == 2); if (FAILED(hr)) return hr;
                const auto deadline = GetTickCount64() + 50;
                std::array<BYTE, RuntimeStatus::RecordBytes> record{};
                struct Clear { BYTE* data; std::size_t size; ~Clear() { SecureZeroMemory(data, size); } } clear{record.data(), record.size()};
                record[0] = 1; record[1] = phase;
                for (unsigned int i = 0; i < 8; ++i)
                { record[2 + i] = static_cast<BYTE>(sequence_ >> (56 - 8 * i)); record[10 + i] = static_cast<BYTE>(token >> (56 - 8 * i)); }
                OVERLAPPED operation{}; operation.hEvent = completed_.value; ResetEvent(completed_.value); DWORD bytes = 0;
                if (!WriteFile(pipe_.value, record.data(), static_cast<DWORD>(record.size()), &bytes, &operation))
                {
                    if (GetLastError() != ERROR_IO_PENDING) return HRESULT_FROM_WIN32(GetLastError());
                    bool pending = true;
                    while (pending)
                    {
                        hr = Current(phase == 2); if (FAILED(hr)) break;
                        if (GetTickCount64() >= deadline) { hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT); break; }
                        const HANDLE waits[] = {context_->localStop.value, context_->parentStop.value, context_->parent.value, completed_.value};
                        const DWORD wait = WaitForMultipleObjects(4, waits, FALSE, 5);
                        if (wait < WAIT_OBJECT_0 + 3) { hr = MF_E_SHUTDOWN; break; }
                        if (wait == WAIT_FAILED) { hr = HRESULT_FROM_WIN32(GetLastError()); break; }
                        if (wait == WAIT_OBJECT_0 + 3)
                        {
                            if (!GetOverlappedResult(pipe_.value, &operation, &bytes, FALSE)) hr = HRESULT_FROM_WIN32(GetLastError());
                            pending = false;
                        }
                    }
                    if (pending) { CancelIoEx(pipe_.value, &operation); DWORD ignored = 0; GetOverlappedResult(pipe_.value, &operation, &ignored, TRUE); }
                }
                if (FAILED(hr)) return hr;
                if (bytes != record.size()) return E_UNEXPECTED;
                hr = Current(phase == 2); if (FAILED(hr)) return hr;
                if (GetTickCount64() >= deadline) return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
                ++sequence_; return S_OK;
            }
            Context* context_ = nullptr;
            OutputLease* lease_ = nullptr;
            Handle pipe_, completed_;
            ULONGLONG sequence_ = 0;
        };
        HRESULT Run(const GUID& control, const GUID& audio, const GUID& anchor, Context& context) noexcept
        {
            Media media;
            std::unique_ptr<PipeReader> reader;
            std::unique_ptr<OutputLease> lease;
            std::unique_ptr<AudioRender> output;
            std::thread controls;
            struct Finish
            {
                Context& context; std::unique_ptr<OutputLease>& lease; std::thread& controls;
                ~Finish() { Context::Retire(&context, MF_E_SHUTDOWN); if (lease) lease->Stop(); if (controls.joinable()) controls.join(); }
            } finish{context, lease, controls};
            try
            {
                HRESULT hr = PipeReader::Connect(control, context.parent.value, Context::Current, &context, reader);
                if (SUCCEEDED(hr)) hr = OutputLease::Create(reader, {Context::Retire, &context, nullptr, nullptr}, lease);
                if (SUCCEEDED(hr)) hr = lease->ReceiveOne();
                if (FAILED(hr)) return hr;
                controls = std::thread([&] { while (!context.retired.load() && SUCCEEDED(lease->ReceiveOne())) {} Context::Retire(&context, MF_E_SHUTDOWN); });
#ifdef MAGNOLIE_NATIVE_AUDIO_WORKER_TESTS
                testStage.store(1);
#endif
                hr = media.Start(); if (FAILED(hr)) return hr;
                Reports reports; hr = reports.Connect(control, context, *lease); if (FAILED(hr)) return hr;
#ifdef MAGNOLIE_NATIVE_AUDIO_WORKER_TESTS
                testStage.store(2);
#endif
                hr = AudioRender::Open(lease.get(), output); if (FAILED(hr)) return hr;
                hr = reports.Ready(*output); if (FAILED(hr)) return hr;
                const auto sendDeadline = GetTickCount64() + 10000;
                while ((hr = lease->RequireSending()) == E_ACCESSDENIED)
                {
                    hr = lease->RequireCurrent(); if (FAILED(hr)) return hr;
                    if (GetTickCount64() >= sendDeadline) return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
                    const HANDLE waits[] = {context.localStop.value, context.parentStop.value, context.parent.value};
                    const DWORD wait = WaitForMultipleObjects(3, waits, FALSE, 10);
                    if (wait != WAIT_TIMEOUT) return MF_E_SHUTDOWN;
                }
                if (FAILED(hr)) return hr;
                auto sending = [](void* value) noexcept { return static_cast<OutputLease*>(value)->RequireSending(); };
                std::unique_ptr<PipeReader> anchorReader;
                hr = PipeReader::Connect(anchor, context.parent.value, sending, lease.get(), anchorReader); if (FAILED(hr)) return hr;
                std::array<BYTE, PresentationClock::AnchorBytes> epoch{};
                hr = anchorReader->ReadExact(epoch.data(), epoch.size()); if (FAILED(hr)) return hr;
                PresentationClock clock(lease->Callbacks()); hr = clock.ImportAnchor(control, epoch.data(), epoch.size());
                SecureZeroMemory(epoch.data(), epoch.size()); if (FAILED(hr)) return hr;
                anchorReader->Stop(); anchorReader.reset();
                std::unique_ptr<PipeReader> audioReader;
                hr = PipeReader::Connect(audio, context.parent.value, sending, lease.get(), audioReader); if (FAILED(hr)) return hr;
                auto samples = std::make_shared<Samples>(sending, lease.get(), false);
                std::unique_ptr<AudioRelay> relay; hr = AudioRelay::Create(audioReader, samples, relay); if (FAILED(hr)) return hr;
                for (ULONGLONG token = 1; token < static_cast<ULONGLONG>((std::numeric_limits<LONGLONG>::max)()); ++token)
                {
                    Microsoft::WRL::ComPtr<IMFSample> sample; hr = relay->ReceiveOne(&sample); if (FAILED(hr)) return hr;
                    LONGLONG phoneTime = -1, nativeTime = -1; hr = sample->GetSampleTime(&phoneTime); if (FAILED(hr)) return hr;
                    if (phoneTime < 0 || phoneTime % 10) return E_INVALIDARG;
                    hr = clock.Map(phoneTime / 10, &nativeTime); if (FAILED(hr)) return hr;
                    hr = output->Write(sample.Get(), nativeTime); if (FAILED(hr)) return hr;
                    hr = reports.Written(token); if (FAILED(hr)) return hr;
                }
                return E_INVALIDARG;
            }
            catch (...) { return E_FAIL; }
        }
    }
    int AudioWorkerMain(int argc, wchar_t** argv) noexcept
    {
#ifdef MAGNOLIE_NATIVE_AUDIO_WORKER_TESTS
        testStage.store(0);
#endif
        if (argc != 6 || !argv || !argv[1] || std::wcscmp(argv[1], L"--phone-audio-worker")) return 64;
        GUID control{}, audio{}, anchor{};
        if (!Scope(argv[2], control) || !Scope(argv[3], audio) || !Scope(argv[4], anchor) ||
            control == audio || control == anchor || audio == anchor) return 64;
        HANDLE parent = nullptr;
        if (!Parent(argv[5], parent) || !Guarded()) return 65;
        try
        {
            Context context; context.parent.value = parent;
            context.localStop.value = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            context.parentStop.value = OpenEventW(SYNCHRONIZE, FALSE, OutputPublisher::StopName(control).c_str());
            // Missing original stop/control bootstrap is refused BEFORE MF/COM,
            // journal, topology or any AudioClient operation. No event creation.
            if (!context.localStop.value || !context.parentStop.value || FAILED(Context::Current(&context))) return 65;
            if (!SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_APPLICATION_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32)) return 65;
            SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
            return SUCCEEDED(Run(control, audio, anchor, context)) ? 0 : 66;
        }
        catch (...) { return 66; }
    }
}
#ifndef MAGNOLIE_NATIVE_AUDIO_WORKER_TESTS
int wmain(int argc, wchar_t** argv) { return Magnolie::PhoneCamera::AudioWorkerMain(argc, argv); }
#endif
