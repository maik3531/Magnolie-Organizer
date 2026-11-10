#include "../../native/phone-camera/PhoneCameraPipe.h"
#include <objbase.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <stdexcept>
#include <thread>
#include <vector>

using Magnolie::PhoneCamera::PipeReader;

namespace
{
    void Check(bool value) { if (!value) throw std::runtime_error("pipe assertion"); }
    void Ok(HRESULT status) { if (FAILED(status)) { std::printf("HRESULT %08lx\n", static_cast<unsigned long>(status)); Check(false); } }
    std::wstring EventName(const GUID& id, const wchar_t* suffix)
    { wchar_t text[40]{}; StringFromGUID2(id, text, 40); return std::wstring(L"Local\\Magnolie.PhoneCamera.Test.") + text + suffix; }
    bool Write(HANDLE pipe, const BYTE* data, DWORD bytes)
    {
        OVERLAPPED operation{}; operation.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!operation.hEvent) return false;
        DWORD count = 0; bool complete = WriteFile(pipe, data, bytes, &count, &operation) != FALSE;
        if (!complete && GetLastError() == ERROR_IO_PENDING)
        {
            if (WaitForSingleObject(operation.hEvent, 3000) == WAIT_OBJECT_0)
                complete = GetOverlappedResult(pipe, &operation, &count, FALSE) != FALSE;
            else { CancelIoEx(pipe, &operation); DWORD ignored = 0; GetOverlappedResult(pipe, &operation, &ignored, TRUE); }
        }
        CloseHandle(operation.hEvent); return complete && count == bytes;
    }
    int Server(const GUID& id, const wchar_t* mode)
    {
        HANDLE ready = OpenEventW(EVENT_MODIFY_STATE, FALSE, EventName(id, L".Ready").c_str());
        HANDLE stop = OpenEventW(SYNCHRONIZE, FALSE, EventName(id, L".Stop").c_str());
        HANDLE pipe = CreateNamedPipeW(PipeReader::Name(id).c_str(), PIPE_ACCESS_OUTBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE | FILE_FLAG_OVERLAPPED,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT, 1, 8192, 8192, 0, nullptr);
        if (!ready || !stop || pipe == INVALID_HANDLE_VALUE) return 20;
        SetEvent(ready); CloseHandle(ready);
        OVERLAPPED connection{}; connection.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!connection.hEvent) { CloseHandle(pipe); CloseHandle(stop); return 22; }
        bool connected = ConnectNamedPipe(pipe, &connection) != FALSE;
        const DWORD error = connected ? ERROR_SUCCESS : GetLastError();
        if (error == ERROR_PIPE_CONNECTED) connected = true;
        if (error == ERROR_IO_PENDING)
        {
            const HANDLE events[] = {stop, connection.hEvent};
            if (WaitForMultipleObjects(2, events, FALSE, 5000) == WAIT_OBJECT_0 + 1)
            { DWORD ignored = 0; connected = GetOverlappedResult(pipe, &connection, &ignored, FALSE) != FALSE; }
            else { CancelIoEx(pipe, &connection); DWORD ignored = 0; GetOverlappedResult(pipe, &connection, &ignored, TRUE); }
        }
        CloseHandle(connection.hEvent);
        if (!connected) { CloseHandle(pipe); CloseHandle(stop); return 21; }
        std::vector<BYTE> data(4096); for (std::size_t i = 0; i < data.size(); ++i) data[i] = static_cast<BYTE>(i % 251);
        if (std::wcscmp(mode, L"empty") != 0)
        {
            if (!Write(pipe, data.data(), 31)) { CloseHandle(pipe); CloseHandle(stop); return 0; }
            if (std::wcscmp(mode, L"chunks") == 0)
            {
                if (!Write(pipe, data.data() + 31, static_cast<DWORD>(data.size() - 31)))
                { CloseHandle(pipe); CloseHandle(stop); return 0; }
            }
        }
        const DWORD result = WaitForSingleObject(stop, 15000);
        CloseHandle(pipe); CloseHandle(stop); return result == WAIT_OBJECT_0 ? 0 : 22;
    }
    struct Peer
    {
        GUID id{};
        HANDLE process = nullptr, ready = nullptr, stop = nullptr;
        explicit Peer(const wchar_t* mode)
        {
            try
            {
            Ok(CoCreateGuid(&id));
            ready = CreateEventW(nullptr, TRUE, FALSE, EventName(id, L".Ready").c_str());
            stop = CreateEventW(nullptr, TRUE, FALSE, EventName(id, L".Stop").c_str()); Check(ready && stop);
            wchar_t path[32768]{}, guid[40]{};
            Check(GetModuleFileNameW(nullptr, path, 32768) != 0); StringFromGUID2(id, guid, 40);
            std::wstring command = std::wstring(L"\"") + path + L"\" --server " + guid + L" " + mode;
            STARTUPINFOW startup{}; startup.cb = sizeof(startup); PROCESS_INFORMATION child{};
            Check(CreateProcessW(path, command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr, nullptr, &startup, &child) != FALSE);
            process = child.hProcess; CloseHandle(child.hThread);
            Check(WaitForSingleObject(ready, 3000) == WAIT_OBJECT_0);
            }
            catch (...) { Close(); throw; }
        }
        ~Peer() { Close(); }
        void Close() noexcept
        {
            if (stop) SetEvent(stop);
            // Unblock ONLY our own test server's pre-client synchronous Connect.
            try
            {
                HANDLE client = CreateFileW(PipeReader::Name(id).c_str(), GENERIC_READ, 0, nullptr, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
                if (client != INVALID_HANDLE_VALUE) CloseHandle(client);
            }
            catch (...) { }
            if (process)
            {
                if (WaitForSingleObject(process, 3000) != WAIT_OBJECT_0)
                { TerminateProcess(process, 99); WaitForSingleObject(process, 3000); }
                CloseHandle(process);
                process = nullptr;
            }
            if (ready) CloseHandle(ready); if (stop) CloseHandle(stop);
            ready = nullptr; stop = nullptr;
        }
    };
    struct Owner
    {
        std::atomic_bool current{true};
        std::atomic_int calls{0}, signalAt{0};
        HANDLE pending = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        ~Owner() { if (pending) CloseHandle(pending); }
        static HRESULT Current(void* value) noexcept
        {
            auto& owner = *static_cast<Owner*>(value);
            if (++owner.calls == owner.signalAt) SetEvent(owner.pending);
            return owner.current ? S_OK : E_ACCESSDENIED;
        }
    };
    bool Zero(const std::vector<BYTE>& data)
    { return std::all_of(data.begin(), data.end(), [](BYTE value) { return value == 0; }); }
    struct OwnProcess
    {
        HANDLE handle = nullptr;
        OwnProcess()
        { Check(DuplicateHandle(GetCurrentProcess(), GetCurrentProcess(), GetCurrentProcess(), &handle, 0, FALSE, DUPLICATE_SAME_ACCESS) != FALSE); }
        ~OwnProcess() { if (handle) CloseHandle(handle); }
    };

    void ActualPeerAndPartialReads()
    {
        Owner owner; Peer peer(L"chunks"); std::unique_ptr<PipeReader> reader;
        Ok(PipeReader::Connect(peer.id, peer.process, Owner::Current, &owner, reader));
        std::vector<BYTE> data(4096); Ok(reader->ReadExact(data.data(), data.size()));
        for (std::size_t i = 0; i < data.size(); ++i) Check(data[i] == i % 251);
        Check(!reader->IsRetired());
        auto* original = reader.get();
        Check(PipeReader::Connect(peer.id, peer.process, Owner::Current, &owner, reader) == E_INVALIDARG && reader.get() == original);
    }

    void WrongActualServerProcess()
    {
        Owner owner; OwnProcess wrong; Peer peer(L"chunks"); std::unique_ptr<PipeReader> reader;
        Check(PipeReader::Connect(peer.id, wrong.handle, Owner::Current, &owner, reader) == E_ACCESSDENIED && !reader);
    }

    void StopInterruptsActualPendingRead()
    {
        Owner owner; Peer peer(L"empty"); std::unique_ptr<PipeReader> reader;
        Ok(PipeReader::Connect(peer.id, peer.process, Owner::Current, &owner, reader));
        owner.signalAt = owner.calls + 2;
        std::vector<BYTE> data(4096, 99); std::atomic<HRESULT> status{S_OK};
        std::thread reading([&] { status = reader->ReadExact(data.data(), data.size()); });
        const DWORD pending = WaitForSingleObject(owner.pending, 1500);
        reader->Stop(); reading.join();
        Check(pending == WAIT_OBJECT_0 && FAILED(status) && reader->IsRetired() && Zero(data));
    }

    void OriginalGuardRevocationIsSticky()
    {
        Owner owner; Peer peer(L"empty"); std::unique_ptr<PipeReader> reader;
        Ok(PipeReader::Connect(peer.id, peer.process, Owner::Current, &owner, reader));
        owner.signalAt = owner.calls + 2;
        std::vector<BYTE> data(4096, 99); std::atomic<HRESULT> status{S_OK};
        std::thread reading([&] { status = reader->ReadExact(data.data(), data.size()); });
        const DWORD pending = WaitForSingleObject(owner.pending, 1500);
        owner.current = false; reading.join();
        Check(pending == WAIT_OBJECT_0 && FAILED(status) && reader->IsRetired() && Zero(data));
        owner.current = true; data[0] = 99;
        Check(FAILED(reader->ReadExact(data.data(), data.size())) && Zero(data));
    }

    void SingleDeadlineAcrossPartialData()
    {
        Owner owner; Peer peer(L"partial"); std::unique_ptr<PipeReader> reader;
        Ok(PipeReader::Connect(peer.id, peer.process, Owner::Current, &owner, reader));
        std::vector<BYTE> data(4096, 99); const auto start = std::chrono::steady_clock::now();
        const HRESULT status = reader->ReadExact(data.data(), data.size());
        const auto elapsed = std::chrono::steady_clock::now() - start;
        Check(status == HRESULT_FROM_WIN32(ERROR_TIMEOUT) && reader->IsRetired() && Zero(data));
        Check(elapsed >= std::chrono::milliseconds(1800) && elapsed < std::chrono::milliseconds(4500));
    }

    void OriginalProcessExitRetiresReader()
    {
        Owner owner; Peer peer(L"empty"); std::unique_ptr<PipeReader> reader;
        Ok(PipeReader::Connect(peer.id, peer.process, Owner::Current, &owner, reader));
        SetEvent(peer.stop); Check(WaitForSingleObject(peer.process, 1500) == WAIT_OBJECT_0);
        std::vector<BYTE> data(64, 99);
        Check(FAILED(reader->ReadExact(data.data(), data.size())) && reader->IsRetired() && Zero(data));
    }

    void ConcurrentReadersAreRefused()
    {
        Owner owner; Peer peer(L"empty"); std::unique_ptr<PipeReader> reader;
        Ok(PipeReader::Connect(peer.id, peer.process, Owner::Current, &owner, reader));
        owner.signalAt = owner.calls + 2;
        std::vector<BYTE> first(64, 99), second(64, 99); std::atomic<HRESULT> status{S_OK};
        std::thread reading([&] { status = reader->ReadExact(first.data(), first.size()); });
        const DWORD pending = WaitForSingleObject(owner.pending, 1500);
        const HRESULT extra = reader->ReadExact(second.data(), second.size()); reading.join();
        Check(pending == WAIT_OBJECT_0 && extra == HRESULT_FROM_WIN32(ERROR_BUSY) && FAILED(status) && Zero(first) && Zero(second));
    }

    void MissingOwnerAndInvalidInput()
    {
        Owner owner; OwnProcess original; GUID id{}; Ok(CoCreateGuid(&id)); std::unique_ptr<PipeReader> reader;
        Check(PipeReader::Connect(id, GetCurrentProcess(), nullptr, &owner, reader) == E_INVALIDARG && !reader);
        Check(PipeReader::Connect(GUID_NULL, GetCurrentProcess(), Owner::Current, &owner, reader) == E_INVALIDARG && !reader);
        owner.current = false;
        Check(PipeReader::Connect(id, original.handle, Owner::Current, &owner, reader) == E_ACCESSDENIED && !reader);
        owner.current = true; Peer peer(L"empty");
        Ok(PipeReader::Connect(peer.id, peer.process, Owner::Current, &owner, reader));
        BYTE byte = 0; Check(reader->ReadExact(&byte, PipeReader::MaxRead + 1) == E_INVALIDARG && reader->IsRetired());
    }
}

int wmain(int argc, wchar_t** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (argc == 4 && std::wcscmp(argv[1], L"--server") == 0)
    { GUID id{}; if (FAILED(CLSIDFromString(argv[2], &id))) return 3; const int result = Server(id, argv[3]); CoUninitialize(); return result; }
    int failed = 0;
    const struct { const char* name; void (*run)(); } cases[] = {
        {"pipe-actual-peer-partial-reads", ActualPeerAndPartialReads}, {"pipe-wrong-kernel-server", WrongActualServerProcess},
        {"pipe-stop-pending-read", StopInterruptsActualPendingRead}, {"pipe-original-guard-sticky", OriginalGuardRevocationIsSticky},
        {"pipe-original-partial-read-deadline", SingleDeadlineAcrossPartialData}, {"pipe-original-process-exit", OriginalProcessExitRetiresReader},
        {"pipe-concurrent-reader-refused", ConcurrentReadersAreRefused}, {"pipe-missing-owner-invalid-input", MissingOwnerAndInvalidInput}
    };
    for (const auto& test : cases)
    {
        if (argc == 2)
        {
            const std::wstring wanted = std::wstring(L",") + argv[1] + L",";
            const std::wstring name(test.name, test.name + std::strlen(test.name));
            if (wanted.find(std::wstring(L",") + name + L",") == std::wstring::npos) continue;
        }
        try { test.run(); std::printf("PASS %s\n", test.name); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
        std::fflush(stdout);
    }
    CoUninitialize(); return failed ? 1 : 0;
}
