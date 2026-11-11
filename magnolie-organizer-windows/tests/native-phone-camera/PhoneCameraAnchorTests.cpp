#include "../../native/phone-camera/PhoneCameraClock.h"
#include <mferror.h>
#include <objbase.h>
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

using namespace Magnolie::PhoneCamera;
namespace
{
    constexpr LONGLONG Remote = 9007199254700000LL;
    constexpr LONGLONG Native = 300000000000LL;
    const GUID Scope = {0x01234567,0x89ab,0xcdef,{0x10,0x32,0x54,0x76,0x98,0xba,0xdc,0xfe}};
    using Record = std::array<BYTE, PresentationClock::AnchorBytes>;
    void Check(bool value) { if (!value) throw std::runtime_error("anchor assertion"); }
    void Ok(HRESULT value) { Check(value == S_OK); }
    struct Owner
    {
        bool current = true, sending = true;
        int checks = 0, denyAt = 0, stopAt = 0, retired = 0;
        LONGLONG now = Native;
        PresentationClock* clock = nullptr;
        static HRESULT Current(void* value) noexcept
        {
            auto& o = *static_cast<Owner*>(value); ++o.checks;
            if (o.stopAt && o.checks == o.stopAt) o.clock->Stop();
            return o.current && o.checks != o.denyAt ? S_OK : E_ACCESSDENIED;
        }
        static HRESULT Sending(void* value) noexcept { return static_cast<Owner*>(value)->sending ? S_OK : E_ACCESSDENIED; }
        static void Retired(void* value, HRESULT) noexcept { ++static_cast<Owner*>(value)->retired; }
        static LONGLONG Now(void* value) noexcept { return static_cast<Owner*>(value)->now; }
        ClockOwner Callbacks() { return {Current, Sending, Retired, this, nullptr, Now}; }
    };
    Record Original()
    {
        Owner owner; PresentationClock clock(owner.Callbacks()); LONGLONG value = 0;
        Ok(clock.Map(Remote, &value)); Check(value == Native);
        Record record{}; Ok(clock.ExportAnchor(Scope, record.data(), record.size())); return record;
    }
    void SharedIntegerEpochNotReceiptTime()
    {
        Record record = Original();
        Check(record.size() == 33 && record[0] == 1 && record[1] == 0x01 && record[2] == 0x23 &&
            record[5] == 0x89 && record[7] == 0xcd && record[9] == 0x10 && record[16] == 0xfe);
        Owner video, audio; video.now = Native + 10000; audio.now = Native + 40000;
        PresentationClock v(video.Callbacks()), a(audio.Callbacks());
        Ok(v.ImportAnchor(Scope, record.data(), record.size())); Ok(a.ImportAnchor(Scope, record.data(), record.size()));
        LONGLONG first = 0, second = 0;
        Ok(v.Map(Remote + 20000, &first)); Ok(a.Map(Remote + 20000, &second));
        Check(first == Native + 20000 && first == second && first != video.now && second != audio.now);
        audio.now += 20000; Ok(a.Map(Remote + 40000, &second)); Check(second == Native + 40000);
        // Long-lived original anchor remains fixed; import doesn't demand that
        // its FIRST coordinate be recent, only that actual mapped data is due.
        Owner origin; PresentationClock original(origin.Callbacks());
        Ok(original.Map(0, &second)); Record longLived{};
        Ok(original.ExportAnchor(Scope, longLived.data(), longLived.size()));
        Owner late; late.now = Native + 10000000; PresentationClock c(late.Callbacks());
        Ok(c.ImportAnchor(Scope, longLived.data(), longLived.size())); Ok(c.Map(10000000, &second)); Check(second == late.now);
    }
    void InvalidAndCrossScopeFailClosed()
    {
        const auto original = Original();
        for (int mode = 0; mode < 9; ++mode)
        {
            auto record = original; Owner owner; PresentationClock clock(owner.Callbacks()); GUID scope = Scope;
            if (mode == 0) record[0] = 2;
            if (mode == 1) record[1] ^= 1;
            if (mode == 2) record[17] = 0x80;
            if (mode == 3) record[25] = 0x80;
            if (mode == 4) scope = GUID_NULL;
            if (mode == 7) owner.now = -1;
            if (mode == 8) owner.now = 9007199254740992LL;
            Check(FAILED(clock.ImportAnchor(scope, mode == 5 ? nullptr : record.data(), mode == 6 ? record.size() - 1 : record.size())));
            LONGLONG result = 99; Check(clock.Map(Remote, &result) == MF_E_SHUTDOWN && result == 0 && owner.retired == 1);
        }
    }
    void NoExportBeforeFrameOrScopeReplacement()
    {
        Record target; target.fill(0xa5); const auto untouched = target;
        Owner early; PresentationClock first(early.Callbacks());
        Check(FAILED(first.ExportAnchor(Scope, target.data(), target.size())) && target == untouched && early.retired == 1);
        Owner owner; PresentationClock clock(owner.Callbacks()); LONGLONG mapped = 0;
        Ok(clock.Map(Remote, &mapped)); Ok(clock.ExportAnchor(Scope, target.data(), target.size()));
        const auto stable = target; owner.now += 20000; Ok(clock.Map(Remote + 20000, &mapped));
        Ok(clock.ExportAnchor(Scope, target.data(), target.size())); Check(target == stable);
        GUID other = Scope; other.Data1 ^= 1; target.fill(0xa5);
        Check(FAILED(clock.ExportAnchor(other, target.data(), target.size())) && target == untouched && owner.retired == 1);
    }
    void NoReimportOrLocalReanchor()
    {
        auto record = Original();
        for (bool priorMap : {false, true})
        {
            Owner owner; PresentationClock clock(owner.Callbacks()); LONGLONG value = 0;
            if (priorMap) Ok(clock.Map(Remote, &value)); else Ok(clock.ImportAnchor(Scope, record.data(), record.size()));
            Check(FAILED(clock.ImportAnchor(Scope, record.data(), record.size())) && owner.retired == 1);
            Check(clock.Map(Remote, &value) == MF_E_SHUTDOWN && value == 0);
        }
        Owner consumer; PresentationClock clock(consumer.Callbacks()); Ok(clock.ImportAnchor(Scope, record.data(), record.size()));
        Record target; target.fill(0xa5); const auto untouched = target;
        Check(FAILED(clock.ExportAnchor(Scope, target.data(), target.size())) && target == untouched && consumer.retired == 1);
    }
    void OriginalAuthorityAndFinalGuards()
    {
        const auto record = Original();
        for (bool exporting : {false, true}) for (int mode = 0; mode < 4; ++mode)
        {
            Owner owner; PresentationClock clock(owner.Callbacks()); owner.clock = &clock;
            if (exporting) { LONGLONG result = 0; Ok(clock.Map(Remote, &result)); }
            owner.checks = 0;
            if (mode == 0) owner.current = false;
            if (mode == 1) owner.sending = false;
            if (mode == 2) owner.denyAt = 2;
            if (mode == 3) owner.stopAt = 2;
            Record target; target.fill(0xa5); const auto untouched = target;
            const HRESULT hr = exporting ? clock.ExportAnchor(Scope, target.data(), target.size()) : clock.ImportAnchor(Scope, record.data(), record.size());
            Check(FAILED(hr) && target == untouched && owner.retired == 1);
            LONGLONG result = 99; Check(clock.Map(Remote, &result) == MF_E_SHUTDOWN && result == 0);
        }
        Owner owner; owner.now = Native + 250001; PresentationClock clock(owner.Callbacks());
        Ok(clock.ImportAnchor(Scope, record.data(), record.size())); LONGLONG result = 99;
        Check(clock.Map(Remote, &result) == MF_E_NET_TIMEOUT && result == 0 && owner.retired == 1);
    }
    struct Handle
    {
        HANDLE value = nullptr;
        ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    };
    int ChildRead(const char* text)
    {
        char* end = nullptr; const auto raw = std::strtoull(text, &end, 10);
        if (!end || *end || !raw) return 10;
        Handle pipe; pipe.value = reinterpret_cast<HANDLE>(static_cast<ULONG_PTR>(raw));
        Record record{}; DWORD got = 0;
        if (!ReadFile(pipe.value, record.data(), static_cast<DWORD>(record.size()), &got, nullptr) || got != record.size()) return 11;
        Owner owner; owner.now = Native + 40000; PresentationClock clock(owner.Callbacks()); LONGLONG result = 0;
        if (clock.ImportAnchor(Scope, record.data(), record.size()) != S_OK || clock.Map(Remote + 20000, &result) != S_OK) return 12;
        return result == Native + 20000 ? 0 : 13;
    }
    void ActualChildUsesSameOriginalAnchor()
    {
        const auto record = Original(); Handle read, write;
        SECURITY_ATTRIBUTES attributes{sizeof(attributes), nullptr, TRUE};
        Check(CreatePipe(&read.value, &write.value, &attributes, 0) != FALSE);
        Check(SetHandleInformation(write.value, HANDLE_FLAG_INHERIT, 0) != FALSE);
        SIZE_T bytes = 0; InitializeProcThreadAttributeList(nullptr, 1, 0, &bytes); Check(bytes > 0);
        std::vector<BYTE> storage(bytes); auto list = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
        Check(InitializeProcThreadAttributeList(list, 1, 0, &bytes) != FALSE);
        struct ReleaseList { LPPROC_THREAD_ATTRIBUTE_LIST value; ~ReleaseList() { DeleteProcThreadAttributeList(value); } } release{list};
        Check(UpdateProcThreadAttribute(list, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, &read.value, sizeof(HANDLE), nullptr, nullptr) != FALSE);
        wchar_t path[32768]{}; Check(GetModuleFileNameW(nullptr, path, 32768));
        std::wstring command = std::wstring(L"\"") + path + L"\" --anchor-child " + std::to_wstring(reinterpret_cast<ULONG_PTR>(read.value));
        STARTUPINFOEXW startup{}; startup.StartupInfo.cb = sizeof(startup); startup.lpAttributeList = list; PROCESS_INFORMATION child{};
        Check(CreateProcessW(path, command.data(), nullptr, nullptr, TRUE, EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW,
            nullptr, nullptr, &startup.StartupInfo, &child) != FALSE);
        Handle process, thread; process.value = child.hProcess; thread.value = child.hThread;
        DWORD written = 0; const bool sent = WriteFile(write.value, record.data(), static_cast<DWORD>(record.size()), &written, nullptr) != FALSE;
        const DWORD wait = WaitForSingleObject(process.value, 3000); DWORD code = ~0UL;
        if (wait == WAIT_OBJECT_0) GetExitCodeProcess(process.value, &code);
        else { TerminateProcess(process.value, 99); WaitForSingleObject(process.value, 3000); } // Only newly created fixed own diagnostic.
        Check(sent && written == record.size() && wait == WAIT_OBJECT_0 && code == 0);
    }
}
int main(int argc, char** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (argc == 3 && !std::strcmp(argv[1], "--anchor-child")) { const int code = ChildRead(argv[2]); CoUninitialize(); return code; }
    if (argc > 2) { CoUninitialize(); return 3; }
    const std::string selected = argc == 2 ? "," + std::string(argv[1]) + "," : "";
    int failed = 0;
    const struct { const char* name; void (*run)(); } tests[] = {
        {"anchor-shared-integer-not-receipt", SharedIntegerEpochNotReceiptTime},
        {"anchor-malformed-cross-scope", InvalidAndCrossScopeFailClosed},
        {"anchor-export-first-frame-fixed-scope", NoExportBeforeFrameOrScopeReplacement},
        {"anchor-no-reimport-reanchor", NoReimportOrLocalReanchor},
        {"anchor-original-authority-final-guard", OriginalAuthorityAndFinalGuards},
        {"anchor-actual-child-same-epoch", ActualChildUsesSameOriginalAnchor}
    };
    for (const auto& test : tests)
    {
        if (!selected.empty() && selected.find("," + std::string(test.name) + ",") == std::string::npos) continue;
        try { test.run(); std::printf("PASS %s\n", test.name); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
    }
    CoUninitialize(); return failed ? 1 : 0;
}
