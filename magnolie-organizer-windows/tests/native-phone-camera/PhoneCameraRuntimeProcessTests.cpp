#include "../../native/phone-camera/PhoneCameraRuntimeProcess.h"
#include <mferror.h>
#include <objbase.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cwchar>
#include <stdexcept>

using namespace Magnolie::PhoneCamera;
namespace Magnolie::PhoneCamera
{
    struct RuntimeProcessTestAccess
    {
        static std::shared_ptr<RuntimeImage> OwnExecutable()
        {
            wchar_t path[32768]{}; if (!GetModuleFileNameW(nullptr, path, 32768)) return {};
            std::wstring full(path); const auto slash = full.find_last_of(L'\\');
            if (slash == std::wstring::npos || full.substr(slash + 1) != L"PhoneCameraSamplesTests.exe") return {};
            std::shared_ptr<RuntimeImage> image(new RuntimeImage);
            image->path_ = full; image->directory_ = full.substr(0, slash);
            // TEST ONLY: the existing user-writable build stage is NOT a
            // protected runtime package. No productive trust path calls this.
            if (FAILED(image->Hold(full, false, false))) return {};
            return image;
        }
        static HANDLE Job(RuntimeProcess& process) { return process.job_; }
    };
}
namespace
{
    void Check(bool value) { if (!value) throw std::runtime_error("runtime process assertion"); }
    void Ok(HRESULT value) { if (value != S_OK) { std::printf("HRESULT %08lx\n", static_cast<unsigned long>(value)); Check(false); } }
    struct Handle
    {
        HANDLE value = nullptr;
        ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    };
    std::wstring ReadyName(const GUID& scope)
    { wchar_t guid[40]{}; Check(StringFromGUID2(scope, guid, 40)); return std::wstring(L"Local\\Magnolie.RuntimeTest.Ready.") + guid; }
    struct Owner
    {
        std::atomic_bool current{true};
        std::atomic_int retired{0};
        std::atomic<HRESULT> reason{S_OK};
        RuntimeProcess* process = nullptr;
        static HRESULT Current(void* value) noexcept { return static_cast<Owner*>(value)->current ? S_OK : E_ACCESSDENIED; }
        static void Retired(void* value, HRESULT reason) noexcept
        { auto& o = *static_cast<Owner*>(value); o.reason = reason; ++o.retired; if (o.process) o.process->Stop(); }
        RuntimeProcessOwner Callbacks() { return {Current, Retired, this, nullptr}; }
    };
    struct Fixture
    {
        Owner owner;
        GUID control{}, audio{}, anchor{};
        Handle ready;
        std::shared_ptr<RuntimeImage> image;
        std::unique_ptr<RuntimeProcess> process;
        Fixture()
        {
            Ok(CoCreateGuid(&control)); Ok(CoCreateGuid(&audio)); Ok(CoCreateGuid(&anchor));
            ready.value = CreateEventW(nullptr, TRUE, FALSE, ReadyName(control).c_str()); Check(ready.value);
            image = RuntimeProcessTestAccess::OwnExecutable(); Check(bool(image));
        }
        void Create()
        { Ok(RuntimeProcess::Create(image, control, audio, anchor, owner.Callbacks(), process)); owner.process = process.get(); }
        void Resume()
        { Ok(process->Resume()); Check(WaitForSingleObject(ready.value, 2000) == WAIT_OBJECT_0); }
        void Prepared() { Create(); Resume(); Ok(process->CompletePreparation()); }
        void Stopped()
        { Ok(process->WaitStopped(5000)); Check(WaitForSingleObject(process->Child(), 0) == WAIT_OBJECT_0 && owner.retired == 1); }
        ~Fixture() { if (process) { process->Stop(); process->WaitStopped(5000); } owner.process = nullptr; }
    };
    int Worker(const wchar_t* scope, const wchar_t* parentText)
    {
        GUID id{}; wchar_t* end = nullptr; const auto raw = std::wcstoull(parentText, &end, 10);
        if (!end || *end || !raw || FAILED(CLSIDFromString(scope, &id))) return 10;
        const HANDLE parent = reinterpret_cast<HANDLE>(static_cast<ULONG_PTR>(raw));
        if (!GetProcessId(parent) || GetProcessId(parent) == GetCurrentProcessId()) return 11;
        Handle ready; ready.value = OpenEventW(EVENT_MODIFY_STATE, FALSE, ReadyName(id).c_str());
        if (!ready.value) return 12;
        SetEvent(ready.value);
        // Deliberately blocked OWN native worker model. No COM/audio activation,
        // settings, endpoints, installers or network. Outer process must stop it.
        Handle blocked; blocked.value = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!blocked.value) return 13;
        // Deliberately do NOT stop when parent exits: parent-death test must
        // prove the kernel job kills this process, not voluntary child cleanup.
        WaitForSingleObject(blocked.value, 30000); return 14;
    }
    void GuardBeforeFirstResume()
    {
        Fixture f; f.Create();
        Check(WaitForSingleObject(f.ready.value, 0) == WAIT_TIMEOUT);
        BOOL assigned = FALSE; Check(IsProcessInJob(f.process->Child(), nullptr, &assigned) && assigned);
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        Check(QueryInformationJobObject(RuntimeProcessTestAccess::Job(*f.process), JobObjectExtendedLimitInformation, &limits, sizeof(limits), nullptr));
        Check((limits.BasicLimitInformation.LimitFlags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) &&
            limits.BasicLimitInformation.ActiveProcessLimit == 1 && limits.ProcessMemoryLimit == 256 * 1024 * 1024);
        f.Resume(); Ok(f.process->CompletePreparation());
        ULONGLONG token = 0; Ok(f.process->BeginOperation(&token)); Check(token == 1); Ok(f.process->CompleteOperation(token));
        f.process->Stop(); f.Stopped();
    }
    void OperationsLateAndReplay()
    {
        Fixture replay; replay.Prepared(); ULONGLONG token = 0;
        Ok(replay.process->BeginOperation(&token)); Ok(replay.process->CompleteOperation(token));
        Check(replay.process->CompleteOperation(token) == E_INVALIDARG); replay.Stopped();
        Fixture late; late.Prepared(); Ok(late.process->BeginOperation(&token));
        Check(WaitForSingleObject(late.process->Child(), 2000) == WAIT_OBJECT_0); late.Stopped();
        Check(late.owner.reason == HRESULT_FROM_WIN32(ERROR_TIMEOUT) && FAILED(late.process->CompleteOperation(token)));
        token = 99; Check(FAILED(late.process->BeginOperation(&token)) && token == 0 && late.owner.retired == 1);
    }
    void OriginalWithdrawAndStop()
    {
        Fixture withdrawn; withdrawn.Prepared(); withdrawn.owner.current = false; ULONGLONG token = 99;
        Check(withdrawn.process->BeginOperation(&token) == E_ACCESSDENIED && token == 0); withdrawn.Stopped();
        Fixture stopped; stopped.Prepared(); const auto start = GetTickCount64();
        stopped.process->Stop(); stopped.process->Stop(); Check(GetTickCount64() - start < 250); stopped.Stopped();
    }
    void FixedBootstrapDeadline()
    {
        Fixture f; const auto start = GetTickCount64(); f.Create();
        // Never resume: demonstrates guard is already active for a suspended
        // child, without a productive/test heartbeat shortcut or lowered limit.
        Check(WaitForSingleObject(f.process->Child(), 12000) == WAIT_OBJECT_0);
        f.Stopped(); Check(GetTickCount64() - start >= 9900 && f.owner.reason == HRESULT_FROM_WIN32(ERROR_TIMEOUT));
        Check(WaitForSingleObject(f.ready.value, 0) == WAIT_TIMEOUT && FAILED(f.process->Resume()));
    }
    void NoMutableArtifactOrInvalidPhases()
    {
        std::shared_ptr<RuntimeImage> image; std::array<BYTE, 32> digest{};
        Check(RuntimeImage::VerifySibling(digest, image) == E_INVALIDARG && !image);
        digest[0] = 1; Check(FAILED(RuntimeImage::VerifySibling(digest, image)) && !image);
        Fixture f; std::unique_ptr<RuntimeProcess> result;
        Check(RuntimeProcess::Create(f.image, f.control, f.control, f.anchor, f.owner.Callbacks(), result) == E_INVALIDARG && !result);
        Check(RuntimeProcess::Create({}, f.control, f.audio, f.anchor, f.owner.Callbacks(), result) == E_INVALIDARG && !result);
        f.owner.current = false;
        Check(RuntimeProcess::Create(f.image, f.control, f.audio, f.anchor, f.owner.Callbacks(), result) == E_ACCESSDENIED && !result);
        Fixture phase; phase.Create(); Check(phase.process->CompletePreparation() == E_INVALIDARG); phase.Stopped();
        Fixture overlapping; overlapping.Prepared(); ULONGLONG token = 0; Ok(overlapping.process->BeginOperation(&token));
        token = 99; Check(overlapping.process->BeginOperation(&token) == E_INVALIDARG && token == 0); overlapping.Stopped();
    }
    int AbruptParent(const wchar_t* rootText, const wchar_t* writeText)
    {
        const auto rootRaw = std::wcstoull(rootText, nullptr, 10), pipeRaw = std::wcstoull(writeText, nullptr, 10);
        if (!rootRaw || !pipeRaw) return 20;
        const auto root = reinterpret_cast<HANDLE>(static_cast<ULONG_PTR>(rootRaw));
        const auto pipe = reinterpret_cast<HANDLE>(static_cast<ULONG_PTR>(pipeRaw));
        Fixture own; own.Create(); own.Resume(); HANDLE remote = nullptr;
        if (!DuplicateHandle(GetCurrentProcess(), own.process->Child(), root, &remote,
            SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, 0)) return 21;
        DWORD written = 0;
        if (!WriteFile(pipe, &remote, sizeof(remote), &written, nullptr) || written != sizeof(remote)) return 22;
        // Actual parent process exit, not a Stop call/destructor. The inherited
        // child has NO job handle, so kernel closes the final parent job handle.
        ExitProcess(0);
    }
    void ParentDeathClosesOwnJob()
    {
        Handle read, write, root; SECURITY_ATTRIBUTES security{sizeof(security), nullptr, TRUE};
        Check(CreatePipe(&read.value, &write.value, &security, 0)); Check(SetHandleInformation(read.value, HANDLE_FLAG_INHERIT, 0));
        Check(DuplicateHandle(GetCurrentProcess(), GetCurrentProcess(), GetCurrentProcess(), &root.value, PROCESS_DUP_HANDLE, TRUE, 0));
        SIZE_T size = 0; InitializeProcThreadAttributeList(nullptr, 1, 0, &size); Check(size > 0);
        std::vector<BYTE> storage(size); auto attributes = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
        Check(InitializeProcThreadAttributeList(attributes, 1, 0, &size));
        struct Clear { LPPROC_THREAD_ATTRIBUTE_LIST value; ~Clear() { DeleteProcThreadAttributeList(value); } } clear{attributes};
        const HANDLE inherited[] = {root.value, write.value};
        Check(UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, const_cast<HANDLE*>(inherited), sizeof(inherited), nullptr, nullptr));
        wchar_t path[32768]{}; Check(GetModuleFileNameW(nullptr, path, 32768));
        std::wstring command = std::wstring(L"\"") + path + L"\" --abrupt-parent " + std::to_wstring(reinterpret_cast<ULONG_PTR>(root.value)) + L" " + std::to_wstring(reinterpret_cast<ULONG_PTR>(write.value));
        STARTUPINFOEXW startup{}; startup.StartupInfo.cb = sizeof(startup); startup.lpAttributeList = attributes; PROCESS_INFORMATION child{};
        Check(CreateProcessW(path, command.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT,
            nullptr, nullptr, &startup.StartupInfo, &child));
        Handle parent, thread; parent.value = child.hProcess; thread.value = child.hThread;
        const DWORD waited = WaitForSingleObject(parent.value, 5000); DWORD code = ~0UL;
        if (waited != WAIT_OBJECT_0) { TerminateProcess(parent.value, 99); WaitForSingleObject(parent.value, 5000); }
        else GetExitCodeProcess(parent.value, &code);
        CloseHandle(write.value); write.value = nullptr;
        Handle worker; DWORD bytes = 0;
        const bool transferred = ReadFile(read.value, &worker.value, sizeof(worker.value), &bytes, nullptr) != FALSE;
        Check(waited == WAIT_OBJECT_0 && code == 0 && transferred && bytes == sizeof(worker.value) && worker.value);
        Check(WaitForSingleObject(worker.value, 3000) == WAIT_OBJECT_0); // Held wait-only object, never reopen/kill by PID.
    }
}
int wmain(int argc, wchar_t** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (argc == 6 && !std::wcscmp(argv[1], L"--phone-audio-worker"))
    { const int code = Worker(argv[2], argv[5]); CoUninitialize(); return code; }
    if (argc == 4 && !std::wcscmp(argv[1], L"--abrupt-parent"))
    { const int code = AbruptParent(argv[2], argv[3]); CoUninitialize(); return code; }
    if (argc != 1) { CoUninitialize(); return 3; }
    int failed = 0;
    const struct { const char* name; void (*run)(); } tests[] = {
        {"runtime-guard-before-resume", GuardBeforeFirstResume},
        {"runtime-operation-expiry-replay", OperationsLateAndReplay},
        {"runtime-original-withdraw-stop", OriginalWithdrawAndStop},
        {"runtime-bootstrap-fixed-deadline", FixedBootstrapDeadline},
        {"runtime-artifact-phase-refusal", NoMutableArtifactOrInvalidPhases},
        {"runtime-parent-death-job", ParentDeathClosesOwnJob}
    };
    for (const auto& test : tests)
    {
        try { test.run(); std::printf("PASS %s\n", test.name); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
        std::fflush(stdout);
    }
    CoUninitialize(); return failed ? 1 : 0;
}
