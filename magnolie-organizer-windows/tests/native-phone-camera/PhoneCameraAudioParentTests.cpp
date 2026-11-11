#include "../../native/phone-camera/PhoneCameraAudioParent.h"
#include "../../native/phone-camera/PhoneCameraOutputLease.h"
#include "../../native/phone-camera/PhoneCameraOutputPublisher.h"
#include "../../native/phone-camera/PhoneCameraRuntimeStatus.h"
#include "../../native/phone-camera/PhoneCameraSamples.h"
#include <mferror.h>
#include <objbase.h>
#include <atomic>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cwchar>
#include <stdexcept>
#include <thread>

using namespace Magnolie::PhoneCamera;
namespace Magnolie::PhoneCamera
{
    struct RuntimeProcessTestAccess
    {
        static std::shared_ptr<RuntimeImage> OwnImage()
        {
            wchar_t path[32768]{}; if (!GetModuleFileNameW(nullptr, path, 32768)) return {};
            const std::wstring full(path); const auto end = full.find_last_of(L'\\');
            if (end == std::wstring::npos || full.substr(end + 1) != L"PhoneCameraSamplesTests.exe") return {};
            std::shared_ptr<RuntimeImage> image(new RuntimeImage); image->path_ = full; image->directory_ = full.substr(0, end);
            return SUCCEEDED(image->Hold(full, false, false)) ? image : nullptr;
        }
    };
}
namespace
{
    void Check(bool value) { if (!value) throw std::runtime_error("audio parent assertion"); }
    void Ok(HRESULT hr) { if (hr != S_OK) { std::printf("HRESULT %08lx\n", static_cast<unsigned long>(hr)); Check(false); } }
    struct Handle { HANDLE value = nullptr; ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); } };
    std::wstring Event(const GUID& scope)
    { wchar_t text[40]{}; Check(StringFromGUID2(scope, text, 40)); return std::wstring(L"Local\\Magnolie.AudioParent.TestRead.") + text; }
    struct State
    {
        std::atomic_bool current{true}, sending{false};
        std::atomic_int failed{0};
        ULONGLONG handle = 0;
        static HRESULT __cdecl Current(void* value) noexcept { return static_cast<State*>(value)->current ? S_OK : E_ACCESSDENIED; }
        static HRESULT __cdecl Sending(void* value) noexcept { return static_cast<State*>(value)->sending ? S_OK : E_ACCESSDENIED; }
        static void __cdecl Failed(void* value, HRESULT) noexcept
        { auto& state = *static_cast<State*>(value); ++state.failed; if (state.handle) MagnoliePhoneAudioStop(state.handle); }
        MagnoliePhoneAudioOwnerV1 Owner() { return {sizeof(MagnoliePhoneAudioOwnerV1), 1, Current, Sending, Failed, this}; }
    };
    struct Fixture
    {
        State state;
        GUID scope{};
        Handle read;
        explicit Fixture(bool stall = false)
        {
            Ok(CoCreateGuid(&scope)); scope.Data4[7] = stall ? 0xa0 : 0xa1;
            read.value = CreateEventW(nullptr, TRUE, FALSE, Event(scope).c_str()); Check(read.value);
            Ok(AudioParentCreateTestImage(scope, RuntimeProcessTestAccess::OwnImage(), state.Owner(), &state.handle));
        }
        void Prepare() { Ok(MagnoliePhoneAudioPrepare(state.handle)); Ok(MagnoliePhoneAudioRequireReady(state.handle)); }
        void Close() { Ok(MagnoliePhoneAudioClose(state.handle)); state.handle = 0; }
        ~Fixture() { if (state.handle) MagnoliePhoneAudioClose(state.handle); }
    };
    std::array<BYTE, Samples::AudioRecordBytes> Packet(ULONGLONG sequence, ULONGLONG pts)
    {
        std::array<BYTE, Samples::AudioRecordBytes> record{}; record.fill(42); record[0] = 1; record[1] = 2;
        for (unsigned int i = 0; i < 8; ++i) { record[2 + i] = static_cast<BYTE>(sequence >> (56 - 8 * i)); record[10 + i] = static_cast<BYTE>(pts >> (56 - 8 * i)); }
        return record;
    }
    ULONGLONG Integer(const BYTE* bytes) { ULONGLONG value = 0; for (int i = 0; i < 8; ++i) value = (value << 8) | bytes[i]; return value; }
    struct Child
    {
        HANDLE parent = nullptr, stop = nullptr;
        std::atomic_bool retired{false};
        static HRESULT Current(void* value) noexcept
        {
            auto& c = *static_cast<Child*>(value); const HANDLE waits[] = {c.parent, c.stop};
            return !c.retired && WaitForMultipleObjects(2, waits, FALSE, 0) == WAIT_TIMEOUT ? S_OK : E_ACCESSDENIED;
        }
        static void Retired(void* value, HRESULT) noexcept { static_cast<Child*>(value)->retired = true; }
    };
    bool Report(HANDLE pipe, BYTE phase, ULONGLONG sequence)
    {
        std::array<BYTE, 18> bytes{}; bytes[0] = 1; bytes[1] = phase;
        for (unsigned int i = 0; i < 8; ++i) { bytes[2 + i] = static_cast<BYTE>(sequence >> (56 - 8 * i)); bytes[10 + i] = bytes[2 + i]; }
        DWORD written = 0; return WriteFile(pipe, bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr) && written == bytes.size();
    }
    int DiagnosticPeer(wchar_t** argv)
    {
        GUID control{}, audio{}, anchor{};
        if (FAILED(CLSIDFromString(argv[2], &control)) || FAILED(CLSIDFromString(argv[3], &audio)) || FAILED(CLSIDFromString(argv[4], &anchor))) return 10;
        const auto raw = std::wcstoull(argv[5], nullptr, 10); if (!raw) return 11;
        Handle parent, stop, report, read; parent.value = reinterpret_cast<HANDLE>(static_cast<ULONG_PTR>(raw));
        stop.value = OpenEventW(SYNCHRONIZE, FALSE, OutputPublisher::StopName(control).c_str());
        read.value = OpenEventW(EVENT_MODIFY_STATE, FALSE, Event(control).c_str());
        if (!stop.value || !read.value) return 12;
        Child context; context.parent = parent.value; context.stop = stop.value;
        std::unique_ptr<PipeReader> controlReader; std::unique_ptr<OutputLease> lease; std::thread controls;
        struct Finish { Child& c; std::unique_ptr<OutputLease>& l; std::thread& t; ~Finish() { c.retired = true; if (l) l->Stop(); if (t.joinable()) t.join(); } } finish{context, lease, controls};
        HRESULT hr = PipeReader::Connect(control, parent.value, Child::Current, &context, controlReader);
        if (SUCCEEDED(hr)) hr = OutputLease::Create(controlReader, {Child::Retired, &context, nullptr, nullptr}, lease);
        if (SUCCEEDED(hr)) hr = lease->ReceiveOne(); if (FAILED(hr)) return 13;
        controls = std::thread([&] { while (!context.retired && SUCCEEDED(lease->ReceiveOne())) {} context.retired = true; });
        report.value = CreateFileW(RuntimeStatus::Name(control).c_str(), GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
        if (report.value == INVALID_HANDLE_VALUE || !Report(report.value, 1, 0)) return 14;
        // This is a CONTROLLED diagnostic peer: Ready/Done are NOT actual Open/
        // Write. Production worker source, not this fixture, supplies those IOs.
        for (;;)
        {
            hr = lease->RequireSending(); if (hr == S_OK) break;
            if (FAILED(lease->RequireCurrent())) return 15;
            const HANDLE waits[] = {parent.value, stop.value};
            if (WaitForMultipleObjects(2, waits, FALSE, 5) != WAIT_TIMEOUT) return 16;
        }
        auto sending = [](void* value) noexcept { return static_cast<OutputLease*>(value)->RequireSending(); };
        std::unique_ptr<PipeReader> epochReader;
        hr = PipeReader::Connect(anchor, parent.value, sending, lease.get(), epochReader); if (FAILED(hr)) return 17;
        std::array<BYTE, PresentationClock::AnchorBytes> epoch{};
        hr = epochReader->ReadExact(epoch.data(), epoch.size()); if (FAILED(hr)) return 18;
        PresentationClock clock(lease->Callbacks()); hr = clock.ImportAnchor(control, epoch.data(), epoch.size()); if (FAILED(hr)) return 19;
        std::unique_ptr<PipeReader> audioReader;
        hr = PipeReader::Connect(audio, parent.value, sending, lease.get(), audioReader); if (FAILED(hr)) return 20;
        for (ULONGLONG sequence = 0; sequence < 3; ++sequence)
        {
            std::array<BYTE, Samples::AudioRecordBytes> packet{};
            hr = audioReader->ReadExact(packet.data(), packet.size()); if (FAILED(hr)) return 21;
            if (packet[0] != 1 || packet[1] != 2 || Integer(packet.data() + 2) != sequence ||
                !std::all_of(packet.begin() + 18, packet.end(), [](BYTE b) { return b == 42; })) return 22;
            LONGLONG mapped = 0; hr = clock.Map(static_cast<LONGLONG>(Integer(packet.data() + 10)), &mapped); if (FAILED(hr)) return 23;
            if (!sequence) SetEvent(read.value);
            if (control.Data4[7] == 0xa0) { WaitForSingleObject(stop.value, 30000); return 24; }
            if (!Report(report.value, 2, sequence + 1)) return 25;
        }
        return 0;
    }
    void CapiInvalidAndProtectedImage()
    {
        Check(MagnoliePhoneAudioVersion() == 1 && MagnoliePhoneAudioRequireReady(0) == E_INVALIDARG && MagnoliePhoneAudioClose(0) == E_INVALIDARG);
        State state; GUID scope{}; Ok(CoCreateGuid(&scope)); auto owner = state.Owner(); BYTE hash[32]{}; hash[0] = 1; ULONGLONG handle = 99;
        Check(MagnoliePhoneAudioCreate(&scope, hash, 31, &owner, &handle) == E_INVALIDARG && handle == 0);
        owner.version = 2; Check(MagnoliePhoneAudioCreate(&scope, hash, 32, &owner, &handle) == E_INVALIDARG && !handle);
        owner = state.Owner(); state.current = false;
        Check(MagnoliePhoneAudioCreate(&scope, hash, 32, &owner, &handle) == E_ACCESSDENIED && !handle);
        state.current = true; Check(FAILED(MagnoliePhoneAudioCreate(&scope, hash, 32, &owner, &handle)) && !handle); // User-writable host is NOT protected installed runtime.
    }
    void JoinedKernelAnchorAndRecords()
    {
        Fixture f; Check(MagnoliePhoneAudioRequireReady(f.state.handle) == E_ACCESSDENIED); f.Prepare(); f.state.sending = true;
        LONGLONG mapped = -1; Ok(MagnoliePhoneAudioObserveVideo(f.state.handle, 1000, &mapped)); Check(mapped >= 0);
        std::array<BYTE, PresentationClock::AnchorBytes> first{}, second{};
        Ok(MagnoliePhoneAudioExportAnchor(f.state.handle, first.data(), static_cast<DWORD>(first.size())));
        Check(Integer(first.data() + 17) == 1000 && Integer(first.data() + 25) == static_cast<ULONGLONG>(mapped));
        for (ULONGLONG i = 0; i < 2; ++i) { auto packet = Packet(i, 1000 + i * 20000); Ok(MagnoliePhoneAudioWrite(f.state.handle, packet.data(), static_cast<DWORD>(packet.size()))); }
        Ok(MagnoliePhoneAudioExportAnchor(f.state.handle, second.data(), static_cast<DWORD>(second.size()))); Check(first == second && f.state.failed == 0);
        const auto old = f.state.handle; f.Close(); Check(MagnoliePhoneAudioRequireReady(old) == E_INVALIDARG);
    }
    void NoSendMalformedAndReplay()
    {
        { Fixture f; f.Prepare(); auto packet = Packet(0, 0); Check(MagnoliePhoneAudioWrite(f.state.handle, packet.data(), static_cast<DWORD>(packet.size())) == E_ACCESSDENIED); f.Close(); Check(f.state.failed == 1); }
        { Fixture f; f.Prepare(); f.state.sending = true; auto packet = Packet(0, 0); Check(MagnoliePhoneAudioWrite(f.state.handle, packet.data(), 1937) == E_INVALIDARG); f.Close(); Check(f.state.failed == 1); }
        { Fixture f; f.Prepare(); f.state.sending = true; auto packet = Packet(0, 0); Ok(MagnoliePhoneAudioWrite(f.state.handle, packet.data(), static_cast<DWORD>(packet.size())));
          Check(MagnoliePhoneAudioWrite(f.state.handle, packet.data(), static_cast<DWORD>(packet.size())) == E_INVALIDARG); f.Close(); Check(f.state.failed == 1); }
    }
    void OriginalLossExclusiveAndNoRevival()
    {
        Fixture f; f.Prepare(); State other; GUID scope{}; Ok(CoCreateGuid(&scope)); ULONGLONG replacement = 0;
        Check(AudioParentCreateTestImage(scope, RuntimeProcessTestAccess::OwnImage(), other.Owner(), &replacement) == HRESULT_FROM_WIN32(ERROR_BUSY) && !replacement);
        Ok(MagnoliePhoneAudioRequireReady(f.state.handle)); f.state.current = false;
        Check(FAILED(MagnoliePhoneAudioRequireReady(f.state.handle))); f.state.current = true;
        Check(FAILED(MagnoliePhoneAudioRequireReady(f.state.handle))); const auto old = f.state.handle; f.Close(); Check(f.state.failed == 1);
        Fixture next; Check(next.state.handle != old); next.Prepare(); Check(MagnoliePhoneAudioStop(old) == E_INVALIDARG); Ok(MagnoliePhoneAudioRequireReady(next.state.handle)); next.Close(); Check(next.state.failed == 0);
    }
    void PendingStopAndConcurrentClose()
    {
        Fixture f(true); f.Prepare(); f.state.sending = true; auto packet = Packet(0, 0); std::atomic<HRESULT> result{S_OK};
        std::thread writer([&] { result = MagnoliePhoneAudioWrite(f.state.handle, packet.data(), static_cast<DWORD>(packet.size())); });
        const DWORD read = WaitForSingleObject(f.read.value, 2000); const auto start = GetTickCount64();
        const HRESULT stopped = MagnoliePhoneAudioStop(f.state.handle); const auto elapsed = GetTickCount64() - start;
        const HRESULT closed = MagnoliePhoneAudioClose(f.state.handle); writer.join(); f.state.handle = 0;
        Check(read == WAIT_OBJECT_0 && stopped == S_OK && elapsed < 250 && closed == S_OK && FAILED(result));
    }
    void ProductionDllExportsOnlyInvalidCalls()
    {
        wchar_t path[32768]{}; Check(GetModuleFileNameW(nullptr, path, 32768)); std::wstring name(path); name = name.substr(0, name.find_last_of(L'\\') + 1) + L"PhoneAudioParentProduction.dll";
        HMODULE library = LoadLibraryExW(name.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32); Check(library);
        struct Free { HMODULE value; ~Free() { FreeLibrary(value); } } free{library};
        const auto version = reinterpret_cast<decltype(&MagnoliePhoneAudioVersion)>(GetProcAddress(library, "MagnoliePhoneAudioVersion"));
        const auto ready = reinterpret_cast<decltype(&MagnoliePhoneAudioRequireReady)>(GetProcAddress(library, "MagnoliePhoneAudioRequireReady"));
        const auto create = reinterpret_cast<decltype(&MagnoliePhoneAudioCreate)>(GetProcAddress(library, "MagnoliePhoneAudioCreate"));
        Check(version && ready && create && version() == 1 && ready(0) == E_INVALIDARG);
        State state; state.current = false; GUID scope{}; Ok(CoCreateGuid(&scope)); BYTE hash[32]{}; hash[0] = 1; auto owner = state.Owner(); ULONGLONG handle = 99;
        Check(create(&scope, hash, 32, &owner, &handle) == E_ACCESSDENIED && !handle); // Ends before image/runtime/device access.
    }
}
int wmain(int argc, wchar_t** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (argc == 6 && !std::wcscmp(argv[1], L"--phone-audio-worker")) { const int result = DiagnosticPeer(argv); CoUninitialize(); return result; }
    if (argc != 1) { CoUninitialize(); return 3; }
    int failed = 0;
    const struct { const char* name; void (*run)(); } tests[] = {
        {"parent-capi-invalid-protected", CapiInvalidAndProtectedImage}, {"parent-joined-anchor-records", JoinedKernelAnchorAndRecords},
        {"parent-no-send-malformed-replay", NoSendMalformedAndReplay}, {"parent-original-loss-exclusive", OriginalLossExclusiveAndNoRevival},
        {"parent-pending-stop-close", PendingStopAndConcurrentClose}, {"parent-production-dll-exports", ProductionDllExportsOnlyInvalidCalls}
    };
    for (const auto& test : tests) { try { test.run(); std::printf("PASS %s\n", test.name); } catch (...) { ++failed; std::printf("FAIL %s\n", test.name); } std::fflush(stdout); }
    CoUninitialize(); return failed ? 1 : 0;
}
