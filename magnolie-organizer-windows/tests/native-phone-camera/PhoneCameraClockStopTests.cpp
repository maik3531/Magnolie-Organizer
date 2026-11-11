#include "../../native/phone-camera/PhoneCameraClock.h"
#include <mferror.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

using namespace Magnolie::PhoneCamera;
namespace
{
    struct Owner
    {
        PresentationClock* clock = nullptr;
        bool current = true, pauseMapper = false, stopOnSecond = false, stopOnRetire = false;
        std::atomic_int checks{0}, retired{0};
        HANDLE entered = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        HANDLE release = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        ~Owner() { if (entered) CloseHandle(entered); if (release) CloseHandle(release); }
        static HRESULT Current(void* context) noexcept
        {
            auto& o = *static_cast<Owner*>(context);
            if (++o.checks == 2 && o.stopOnSecond) o.clock->Stop();
            return o.current ? S_OK : E_ACCESSDENIED;
        }
        static HRESULT Sending(void*) noexcept { return S_OK; }
        static void Retired(void* context, HRESULT) noexcept
        { auto& o = *static_cast<Owner*>(context); ++o.retired; if (o.stopOnRetire) o.clock->Stop(); }
        static LONGLONG Now(void* context) noexcept
        {
            auto& o = *static_cast<Owner*>(context);
            if (o.pauseMapper) { SetEvent(o.entered); WaitForSingleObject(o.release, 1500); }
            return 1000000;
        }
        ClockOwner Callbacks() { return {Current, Sending, Retired, this, nullptr, Now}; }
    };

    int PendingMapper()
    {
        Owner owner; owner.pauseMapper = true;
        if (!owner.entered || !owner.release) return 10;
        PresentationClock clock(owner.Callbacks()); owner.clock = &clock;
        LONGLONG value = 99; std::atomic<HRESULT> mapped{S_OK};
        std::thread map([&] { mapped = clock.Map(0, &value); });
        const DWORD entered = WaitForSingleObject(owner.entered, 1000);
        HANDLE stopped = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!stopped) { SetEvent(owner.release); map.join(); return 11; }
        std::thread stop([&] { clock.Stop(); SetEvent(stopped); });
        // Controlled own-thread pause models a descheduled mapper. It is NOT a
        // claim that productive original callbacks are allowed to block.
        const bool nonblocking = WaitForSingleObject(stopped, 250) == WAIT_OBJECT_0;
        SetEvent(owner.release); map.join(); stop.join(); CloseHandle(stopped);
        LONGLONG again = 99;
        return entered == WAIT_OBJECT_0 && nonblocking && FAILED(mapped) && value == 0 &&
            clock.Map(0, &again) == MF_E_SHUTDOWN && again == 0 && owner.retired == 1 ? 0 : 12;
    }
    int ReentrantRetirement()
    {
        Owner owner; owner.current = false; owner.stopOnRetire = true;
        PresentationClock clock(owner.Callbacks()); owner.clock = &clock;
        LONGLONG value = 99; const HRESULT hr = clock.Map(0, &value);
        return FAILED(hr) && value == 0 && owner.retired == 1 ? 0 : 13;
    }
    int StopAtFinalGuard()
    {
        Owner owner; owner.stopOnSecond = true; owner.stopOnRetire = true;
        PresentationClock clock(owner.Callbacks()); owner.clock = &clock;
        LONGLONG value = 99; const HRESULT hr = clock.Map(0, &value);
        return FAILED(hr) && value == 0 && owner.retired == 1 ? 0 : 14;
    }
    int ConcurrentStopOnce()
    {
        Owner owner; PresentationClock clock(owner.Callbacks()); owner.clock = &clock;
        std::vector<std::thread> stopping;
        for (int i = 0; i < 8; ++i) stopping.emplace_back([&] { clock.Stop(); });
        for (auto& thread : stopping) thread.join();
        LONGLONG value = 99;
        return owner.retired == 1 && clock.Map(0, &value) == MF_E_SHUTDOWN && value == 0 ? 0 : 15;
    }

    bool Child(const wchar_t* mode)
    {
        wchar_t path[32768]{};
        if (!GetModuleFileNameW(nullptr, path, 32768)) return false;
        std::wstring command = std::wstring(L"\"") + path + L"\" " + mode;
        STARTUPINFOW startup{}; startup.cb = sizeof(startup); PROCESS_INFORMATION child{};
        if (!CreateProcessW(path, command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
            nullptr, nullptr, &startup, &child)) return false;
        CloseHandle(child.hThread);
        const DWORD wait = WaitForSingleObject(child.hProcess, 3500); DWORD code = ~0UL;
        if (wait == WAIT_OBJECT_0) GetExitCodeProcess(child.hProcess, &code);
        else
        {
            // ONLY the just-created fixed own diagnostic executable, never PID
            // lookup, an installer, service or arbitrary supplied process.
            TerminateProcess(child.hProcess, 99); WaitForSingleObject(child.hProcess, 3000);
            std::fprintf(stderr, "Owned clock diagnostic child timed out\n");
        }
        CloseHandle(child.hProcess); return wait == WAIT_OBJECT_0 && code == 0;
    }
}

int main(int argc, char** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    int result = 0;
    if (argc == 2)
    {
        if (!std::strcmp(argv[1], "--child-pending-map")) result = PendingMapper();
        else if (!std::strcmp(argv[1], "--child-reentrant-retire")) result = ReentrantRetirement();
        else if (!std::strcmp(argv[1], "--child-final-guard")) result = StopAtFinalGuard();
        else if (!std::strcmp(argv[1], "--child-concurrent")) result = ConcurrentStopOnce();
        else result = 3;
    }
    else if (argc == 1)
    {
        const struct { const char* name; const wchar_t* mode; } tests[] = {
            {"clock-stop-nonblocking-map", L"--child-pending-map"},
            {"clock-stop-reentrant-retire", L"--child-reentrant-retire"},
            {"clock-stop-final-guard", L"--child-final-guard"},
            {"clock-stop-concurrent-once", L"--child-concurrent"}
        };
        for (const auto& test : tests)
        {
            const bool passed = Child(test.mode);
            std::printf("%s %s\n", passed ? "PASS" : "FAIL", test.name); std::fflush(stdout);
            if (!passed) result = 1;
        }
    }
    else result = 4;
    CoUninitialize(); return result;
}
