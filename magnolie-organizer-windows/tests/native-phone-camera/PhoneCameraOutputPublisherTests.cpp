#include "../../native/phone-camera/PhoneCameraOutputPublisher.h"
#include "../../native/phone-camera/PhoneCameraOutputLease.h"
#include <mferror.h>
#include <objbase.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cwchar>
#include <stdexcept>
#include <thread>

using namespace Magnolie::PhoneCamera;
namespace Magnolie::PhoneCamera
{
    struct OutputPublisherTestAccess
    { static bool Pending(OutputPublisher* value) { return value && value->pending_.load(); } };
}
namespace
{
    void Check(bool value) { if (!value) throw std::runtime_error("publisher assertion"); }
    void Ok(HRESULT hr) { if (FAILED(hr)) { std::printf("HRESULT %08lx\n", static_cast<unsigned long>(hr)); Check(false); } }
    struct Handle
    {
        HANDLE value = nullptr;
        ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    };
    std::wstring Ack(const GUID& scope, const wchar_t* part)
    { return OutputPublisher::StopName(scope) + L".Test." + part; }
    struct State
    {
        std::atomic_bool current{true}, sending{false}, signalPending{false};
        std::atomic_int retired{0};
        std::atomic<ULONGLONG> now{1000};
        OutputPublisher* publisher = nullptr;
        Handle pending;
        State() { pending.value = CreateEventW(nullptr, TRUE, FALSE, nullptr); Check(pending.value); }
        static HRESULT Current(void* context) noexcept
        {
            auto& state = *static_cast<State*>(context);
            if (state.signalPending && OutputPublisherTestAccess::Pending(state.publisher)) SetEvent(state.pending.value);
            return state.current ? S_OK : E_ACCESSDENIED;
        }
        static HRESULT Sending(void* context) noexcept { return static_cast<State*>(context)->sending ? S_OK : E_ACCESSDENIED; }
        static void Retired(void* context, HRESULT) noexcept
        { auto& state = *static_cast<State*>(context); ++state.retired; if (state.publisher) state.publisher->Stop(); }
        static ULONGLONG Now(void* context) noexcept { return static_cast<State*>(context)->now.load(); }
        OutputPublisherOwner Callbacks() { return {Current, Sending, Retired, this, nullptr, Now}; }
    };
    struct ChildContext
    {
        HANDLE stop = nullptr;
        int retired = 0;
        static HRESULT Current(void* value) noexcept
        { return WaitForSingleObject(static_cast<ChildContext*>(value)->stop, 0) == WAIT_TIMEOUT ? S_OK : E_ACCESSDENIED; }
        static void Retired(void* value, HRESULT) noexcept { ++static_cast<ChildContext*>(value)->retired; }
        static ULONGLONG Now(void*) noexcept { return 1000; } // Explicit native test clock, never productive runtime default.
    };
    int Client(const wchar_t* guid, const wchar_t* pid, const wchar_t* kind)
    {
        GUID scope{}; wchar_t* end = nullptr; const unsigned long long number = std::wcstoull(pid, &end, 10);
        if (!number || number > 0xffffffffULL || !end || *end || FAILED(CLSIDFromString(guid, &scope))) return 10;
        Handle parent, stop, ready, prepared, sent;
        parent.value = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, static_cast<DWORD>(number));
        stop.value = OpenEventW(SYNCHRONIZE, FALSE, OutputPublisher::StopName(scope).c_str());
        ready.value = OpenEventW(EVENT_MODIFY_STATE, FALSE, Ack(scope, L"Ready").c_str());
        prepared.value = OpenEventW(EVENT_MODIFY_STATE, FALSE, Ack(scope, L"Prepare").c_str());
        sent.value = OpenEventW(EVENT_MODIFY_STATE, FALSE, Ack(scope, L"Send").c_str());
        if (!parent.value || !stop.value || !ready.value || !prepared.value || !sent.value) return 11;
        ChildContext context; context.stop = stop.value; std::unique_ptr<PipeReader> reader;
        HRESULT hr = PipeReader::Connect(scope, parent.value, ChildContext::Current, &context, reader);
        if (FAILED(hr)) return 12;
        if (!std::wcscmp(kind, L"stall"))
        { SetEvent(ready.value); return WaitForSingleObject(stop.value, 3000) == WAIT_OBJECT_0 ? 0 : 13; }
        std::unique_ptr<OutputLease> lease;
        hr = OutputLease::Create(reader, {ChildContext::Retired, &context, nullptr, ChildContext::Now}, lease);
        if (FAILED(hr)) return 14;
        SetEvent(ready.value);
        hr = lease->ReceiveOne();
        if (FAILED(hr) || FAILED(lease->RequireCurrent()) || lease->RequireSending() != E_ACCESSDENIED) return 15;
        SetEvent(prepared.value);
        if (!std::wcscmp(kind, L"phases"))
        {
            hr = lease->ReceiveOne(); if (FAILED(hr) || FAILED(lease->RequireSending())) return 16;
            SetEvent(sent.value);
        }
        if (WaitForSingleObject(stop.value, 3000) != WAIT_OBJECT_0) return 17;
        // Fake lease time never expires here: failure MUST come from the
        // original terminal stop event via the admitted control guard.
        return FAILED(lease->RequireCurrent()) && context.retired == 1 ? 0 : 18;
    }
    struct Fixture
    {
        State state;
        GUID scope{};
        HANDLE process = nullptr, thread = nullptr;
        Handle ready, prepared, sent;
        std::unique_ptr<OutputPublisher> publisher;
        explicit Fixture(const wchar_t* kind)
        {
            try
            {
                Ok(CoCreateGuid(&scope));
                ready.value = CreateEventW(nullptr, TRUE, FALSE, Ack(scope, L"Ready").c_str());
                prepared.value = CreateEventW(nullptr, TRUE, FALSE, Ack(scope, L"Prepare").c_str());
                sent.value = CreateEventW(nullptr, TRUE, FALSE, Ack(scope, L"Send").c_str());
                Check(ready.value && prepared.value && sent.value);
                wchar_t path[32768]{}, guid[40]{}; Check(GetModuleFileNameW(nullptr, path, 32768) && StringFromGUID2(scope, guid, 40));
                std::wstring command = std::wstring(L"\"") + path + L"\" --client " + guid + L" " + std::to_wstring(GetCurrentProcessId()) + L" " + kind;
                STARTUPINFOW startup{}; startup.cb = sizeof(startup); PROCESS_INFORMATION child{};
                Check(CreateProcessW(path, command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW | CREATE_SUSPENDED,
                    nullptr, nullptr, &startup, &child) != FALSE);
                process = child.hProcess; thread = child.hThread;
            }
            catch (...) { Close(); throw; }
        }
        void Create()
        { Ok(OutputPublisher::Create(scope, process, state.Callbacks(), publisher)); state.publisher = publisher.get(); }
        void Connect()
        {
            Check(ResumeThread(thread) != static_cast<DWORD>(-1));
            Ok(publisher->Accept()); Check(WaitForSingleObject(ready.value, 1500) == WAIT_OBJECT_0);
        }
        void Prepare()
        { Ok(publisher->Publish()); Check(WaitForSingleObject(prepared.value, 1500) == WAIT_OBJECT_0); }
        void Send()
        { state.sending = true; Ok(publisher->Publish()); Check(WaitForSingleObject(sent.value, 1500) == WAIT_OBJECT_0); }
        void Exited()
        { Check(WaitForSingleObject(process, 3000) == WAIT_OBJECT_0); DWORD code = ~0UL; Check(GetExitCodeProcess(process, &code) && code == 0); }
        void Close() noexcept
        {
            if (publisher) publisher->Stop();
            if (process)
            {
                if (WaitForSingleObject(process, 500) != WAIT_OBJECT_0)
                { TerminateProcess(process, 99); WaitForSingleObject(process, 3000); } // ONLY this newly created fixed test executable.
                CloseHandle(process); process = nullptr;
            }
            if (thread) { CloseHandle(thread); thread = nullptr; }
            publisher.reset(); state.publisher = nullptr;
        }
        ~Fixture() { Close(); }
    };
    void ActualPrepareSendStop()
    {
        Fixture f(L"phases"); f.Create(); f.Connect(); f.Prepare(); f.Send();
        f.publisher->Stop(); f.publisher->Stop(); f.Exited(); Check(f.state.retired == 1);
    }
    void NoCurrentOrSendFirst()
    {
        Fixture denied(L"stall"); denied.state.current = false;
        Check(OutputPublisher::Create(denied.scope, denied.process, denied.state.Callbacks(), denied.publisher) == E_ACCESSDENIED && !denied.publisher && denied.state.retired == 1);
        Fixture early(L"stall"); early.state.sending = true; early.Create(); early.Connect();
        Check(early.publisher->Publish() == E_ACCESSDENIED && early.publisher->IsRetired()); early.Exited();
    }
    void NoPhaseOrClockRollback()
    {
        Fixture phase(L"phases"); phase.Create(); phase.Connect(); phase.Prepare(); phase.Send(); phase.state.sending = false;
        Check(phase.publisher->Publish() == E_ACCESSDENIED && phase.state.retired == 1); phase.Exited();
        Fixture clock(L"prepare-only"); clock.Create(); clock.Connect(); clock.Prepare(); clock.state.now = 999;
        Check(clock.publisher->Publish() == E_INVALIDARG && clock.state.retired == 1); clock.Exited();
    }
    void ExactKernelPeerAndUntouchedCollision()
    {
        Fixture invalid(L"stall"); Handle self;
        Check(DuplicateHandle(GetCurrentProcess(), GetCurrentProcess(), GetCurrentProcess(), &self.value, 0, FALSE, DUPLICATE_SAME_ACCESS) != FALSE);
        Check(OutputPublisher::Create(invalid.scope, self.value, invalid.state.Callbacks(), invalid.publisher) == E_ACCESSDENIED && !invalid.publisher && invalid.state.retired == 0);
        Fixture wrong(L"stall"); wrong.Create(); Handle impostor;
        impostor.value = CreateFileW(PipeReader::Name(wrong.scope).c_str(), GENERIC_READ, 0, nullptr, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
        Check(impostor.value != INVALID_HANDLE_VALUE);
        Check(wrong.publisher->Accept() == E_ACCESSDENIED && wrong.state.retired == 1);
        Fixture collision(L"stall"); Handle existing;
        existing.value = CreateEventW(nullptr, TRUE, FALSE, OutputPublisher::StopName(collision.scope).c_str()); Check(existing.value);
        Check(OutputPublisher::Create(collision.scope, collision.process, collision.state.Callbacks(), collision.publisher) == HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS) && !collision.publisher);
        Check(WaitForSingleObject(existing.value, 0) == WAIT_TIMEOUT); // Neither reset nor signal an unknown existing event.
    }
    void StopInterruptsOwnPendingPublish()
    {
        Fixture f(L"stall"); f.Create(); f.Connect(); ResetEvent(f.state.pending.value); f.state.signalPending = true;
        std::atomic<HRESULT> status{S_OK};
        std::thread publishing([&] { for (int i = 0; i < 4096; ++i) { status = f.publisher->Publish(); if (FAILED(status)) break; } });
        const DWORD pending = WaitForSingleObject(f.state.pending.value, 1500);
        const ULONGLONG before = GetTickCount64(); f.publisher->Stop(); const ULONGLONG elapsed = GetTickCount64() - before;
        publishing.join(); f.Exited();
        Check(pending == WAIT_OBJECT_0 && elapsed < 250 && FAILED(status) && f.publisher->IsRetired() && f.state.retired == 1);
    }
}

int wmain(int argc, wchar_t** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (argc == 5 && !std::wcscmp(argv[1], L"--client"))
    { const int result = Client(argv[2], argv[3], argv[4]); CoUninitialize(); return result; }
    if (argc != 1) { CoUninitialize(); return 3; }
    int failed = 0;
    const struct { const char* name; void (*run)(); } tests[] = {
        {"publisher-original-prepare-send-stop", ActualPrepareSendStop},
        {"publisher-no-current-send-first", NoCurrentOrSendFirst},
        {"publisher-no-phase-clock-rollback", NoPhaseOrClockRollback},
        {"publisher-kernel-peer-collision", ExactKernelPeerAndUntouchedCollision},
        {"publisher-stop-pending-write", StopInterruptsOwnPendingPublish}
    };
    for (const auto& test : tests)
    {
        try { test.run(); std::printf("PASS %s\n", test.name); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
    }
    CoUninitialize(); return failed ? 1 : 0;
}
