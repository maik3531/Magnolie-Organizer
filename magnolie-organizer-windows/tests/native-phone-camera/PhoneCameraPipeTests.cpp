#include "../../native/phone-camera/PhoneCameraPipe.h"
#ifdef MAGNOLIE_NATIVE_OUTPUT_LEASE_TESTS
#include "../../native/phone-camera/PhoneCameraOutputLease.h"
#include <mferror.h>
using Magnolie::PhoneCamera::OutputLease;
using Magnolie::PhoneCamera::OutputLeaseOwner;
#endif
#ifdef MAGNOLIE_NATIVE_RELAY_TESTS
#include "../../native/phone-camera/PhoneCameraRelay.h"
#endif
#include <objbase.h>
#ifdef MAGNOLIE_NATIVE_RELAY_TESTS
#include <mfapi.h>
#include <mferror.h>
#include <mfreadwrite.h>
#endif
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <stdexcept>
#include <thread>
#include <vector>

using Magnolie::PhoneCamera::PipeReader;
#ifdef MAGNOLIE_NATIVE_RELAY_TESTS
using Magnolie::PhoneCamera::VideoRelay;
using Magnolie::PhoneCamera::AudioRelay;
using Magnolie::PhoneCamera::Samples;
using Magnolie::PhoneCamera::SourceOwner;
using Magnolie::PhoneCamera::IFrameFeed;
using Microsoft::WRL::ComPtr;
#endif

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
#ifdef MAGNOLIE_NATIVE_OUTPUT_LEASE_TESTS
        if (std::wcsncmp(mode, L"lease", 5) == 0)
        {
            const bool phases = std::wcscmp(mode, L"lease-phases") == 0;
            const bool rollback = std::wcscmp(mode, L"lease-rollback") == 0;
            const bool replay = std::wcscmp(mode, L"lease-replay") == 0;
            const bool gap = std::wcscmp(mode, L"lease-gap") == 0;
            const bool late = std::wcscmp(mode, L"lease-late-refresh") == 0;
            const int records = phases || rollback ? 3 : replay || gap || late ? 2 : 1;
            for (int i = 0; i < records; ++i)
            {
                std::vector<BYTE> record(OutputLease::RecordBytes);
                record[0] = std::wcscmp(mode, L"lease-version") == 0 ? 2 : 1;
                record[1] = phases && i == 2 ? 3 : rollback && i == 2 ? 1 : i ? 2 : 1;
                if (std::wcscmp(mode, L"lease-phase") == 0) record[1] = 4;
                if (std::wcscmp(mode, L"lease-send-first") == 0) record[1] = 2;
                if (std::wcscmp(mode, L"lease-stop-expiry") == 0) record[1] = 3;
                std::uint64_t sequence = static_cast<std::uint64_t>(i);
                if (replay && i == 1) sequence = 0;
                if (gap && i == 1) sequence = 2;
                if (std::wcscmp(mode, L"lease-integer") == 0) sequence = 0x8000000000000000ULL;
                std::uint64_t until = phases && i == 2 ? 0 : late && i == 1 ? 1400 : 1200;
                if (std::wcscmp(mode, L"lease-expired") == 0) until = 1000;
                if (std::wcscmp(mode, L"lease-future") == 0) until = 1251;
                if (std::wcscmp(mode, L"lease-boundary") == 0) until = 1250;
                for (unsigned int n = 0; n < 8; ++n)
                {
                    record[2 + n] = static_cast<BYTE>(sequence >> (56 - 8 * n));
                    record[10 + n] = static_cast<BYTE>(until >> (56 - 8 * n));
                }
                if (!Write(pipe, record.data(), 7) || std::wcscmp(mode, L"lease-short") == 0) break;
                if (!Write(pipe, record.data() + 7, static_cast<DWORD>(record.size() - 7))) break;
            }
            WaitForSingleObject(stop, 15000); CloseHandle(pipe); CloseHandle(stop); return 0;
        }
#endif
#ifdef MAGNOLIE_NATIVE_RELAY_TESTS
        if (std::wcsncmp(mode, L"audio", 5) == 0)
        {
            std::vector<BYTE> packet(Samples::AudioRecordBytes);
            for (std::size_t at = 18; at < packet.size(); ++at) packet[at] = static_cast<BYTE>((at - 18) * 31);
            auto integer = [&](std::size_t offset, std::uint64_t value) {
                for (unsigned int i = 0; i < 8; ++i) packet[offset + i] = static_cast<BYTE>(value >> (56 - 8 * i));
            };
            for (int i = 0; i < (std::wcscmp(mode, L"audio-fragments") == 0 ? 2 : 1); ++i)
            {
                packet[0] = std::wcscmp(mode, L"audio-version") == 0 ? 2 : 1;
                packet[1] = std::wcscmp(mode, L"audio-track") == 0 ? 1 : 2;
                integer(2, std::wcscmp(mode, L"audio-sequence") == 0 ? 0x8000000000000000ULL : static_cast<std::uint64_t>(i));
                integer(10, std::wcscmp(mode, L"audio-pts") == 0 ? 9007199254740992ULL : static_cast<std::uint64_t>(i) * 20000);
                if (!Write(pipe, packet.data(), 7)) break;
                if (std::wcscmp(mode, L"audio-short") == 0) break;
                if (!Write(pipe, packet.data() + 7, static_cast<DWORD>(packet.size() - 7))) break;
            }
            WaitForSingleObject(stop, 15000); CloseHandle(pipe); CloseHandle(stop); return 0;
        }
        if (std::wcsncmp(mode, L"video", 5) == 0)
        {
            std::vector<BYTE> packet(18 + 640 * 480 * 3 / 2, 128);
            std::fill(packet.begin() + 18, packet.begin() + 18 + 640 * 480, static_cast<BYTE>(90));
            auto integer = [&](std::size_t offset, std::uint64_t value) {
                for (unsigned int i = 0; i < 8; ++i) packet[offset + i] = static_cast<BYTE>(value >> (56 - 8 * i));
            };
            for (int i = 0; i < (std::wcscmp(mode, L"video") == 0 ? 30 : 1); ++i)
            {
                packet[0] = 1; packet[1] = std::wcscmp(mode, L"video-track") == 0 ? 2 : 1;
                integer(2, std::wcscmp(mode, L"video-sequence") == 0 ? 0x8000000000000000ULL : static_cast<std::uint64_t>(i));
                integer(10, std::wcscmp(mode, L"video-pts") == 0 ? 9007199254740992ULL : static_cast<std::uint64_t>(i) * 66667);
                if (!Write(pipe, packet.data(), static_cast<DWORD>(packet.size()))) break;
                if (WaitForSingleObject(stop, 67) == WAIT_OBJECT_0) break;
            }
            WaitForSingleObject(stop, 15000); CloseHandle(pipe); CloseHandle(stop); return 0;
        }
#endif
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

#ifdef MAGNOLIE_NATIVE_RELAY_TESTS
    struct MediaRuntime
    {
        MediaRuntime() { Ok(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET)); }
        ~MediaRuntime() { MFShutdown(); }
    };
    struct RelayOwner
    {
        Owner original;
        HANDLE process = nullptr;
        std::atomic<PipeReader*> pipe{nullptr};
        std::atomic<VideoRelay*> relay{nullptr};
        std::atomic_bool sending{true};
        std::atomic_int retired{0};
        static HRESULT Current(void* context) noexcept
        {
            auto& owner = *static_cast<RelayOwner*>(context);
            auto* pipe = owner.pipe.load();
            return owner.original.current && pipe && !pipe->IsRetired() &&
                WaitForSingleObject(owner.process, 0) == WAIT_TIMEOUT ? S_OK : E_ACCESSDENIED;
        }
        static HRESULT Sending(void* context) noexcept
        { auto& owner = *static_cast<RelayOwner*>(context); return owner.sending ? Current(context) : E_ACCESSDENIED; }
        static void Retired(void* context, HRESULT) noexcept
        {
            auto& owner = *static_cast<RelayOwner*>(context); ++owner.retired;
            auto* relay = owner.relay.load(); auto* pipe = owner.pipe.load();
            if (relay) relay->Stop(); else if (pipe) pipe->Stop();
        }
        SourceOwner Callbacks() { return {Current, Sending, Retired, this}; }
    };
    struct RelayFixture
    {
        MediaRuntime runtime;
        RelayOwner owner;
        Peer peer;
        std::unique_ptr<PipeReader> reader;
        ComPtr<IMFMediaSourceEx> source;
        ComPtr<IFrameFeed> feed;
        std::unique_ptr<VideoRelay> relay;
        explicit RelayFixture(const wchar_t* mode) : peer(mode)
        {
            Ok(PipeReader::Connect(peer.id, peer.process, Owner::Current, &owner.original, reader));
            owner.process = peer.process; owner.pipe = reader.get();
            Ok(Magnolie::PhoneCamera::CreateSource(owner.Callbacks(), &source, &feed));
        }
        void Attach()
        { Ok(VideoRelay::Create(reader, source.Get(), feed.Get(), relay)); owner.relay = relay.get(); }
        ~RelayFixture()
        {
            if (source) source->Shutdown();
            // Keep the owner and held pipe pointer alive until source shutdown.
            relay.reset(); owner.relay = nullptr;
        }
    };

    void RelayCrossProcessSourceReader()
    {
        RelayFixture f(L"video"); f.Attach();
        ComPtr<IMFAttributes> attrs; Ok(MFCreateAttributes(&attrs, 1)); Ok(attrs->SetUINT32(MF_READWRITE_DISABLE_CONVERTERS, TRUE));
        ComPtr<IMFSourceReader> reader; Ok(MFCreateSourceReaderFromMediaSource(f.source.Get(), attrs.Get(), &reader));
        std::atomic_bool finished{false}; std::atomic<HRESULT> status{S_OK};
        std::thread receive([&] {
            while (!finished)
            {
                const HRESULT hr = f.relay->ReceiveOne();
                if (FAILED(hr)) { if (!finished) status = hr; break; }
            }
        });
        bool valid = true; LONGLONG previous = -1;
        for (int i = 0; i < 3; ++i)
        {
            DWORD stream = 99, flags = 0; LONGLONG pts = -1; ComPtr<IMFSample> sample;
            HRESULT hr = reader->ReadSample(static_cast<DWORD>(MF_SOURCE_READER_FIRST_VIDEO_STREAM), 0, &stream, &flags, &pts, &sample);
            if (FAILED(hr) || !sample || stream != 0 || pts <= previous ||
                (flags & (MF_SOURCE_READERF_ERROR | MF_SOURCE_READERF_ENDOFSTREAM | MF_SOURCE_READERF_STREAMTICK)))
            { valid = false; break; }
            previous = pts;
            ComPtr<IMFMediaBuffer> buffer; hr = sample->ConvertToContiguousBuffer(&buffer);
            if (FAILED(hr)) { valid = false; break; }
            BYTE* bytes = nullptr; DWORD size = 0; hr = buffer->Lock(&bytes, nullptr, &size);
            if (FAILED(hr)) { valid = false; break; }
            if (size != Magnolie::PhoneCamera::Samples::VideoBytes) valid = false;
            else for (DWORD at = 0; at < size; ++at) if (bytes[at] != (at < 640 * 480 ? 90 : 128)) { valid = false; break; }
            buffer->Unlock(); if (!valid) break;
        }
        finished = true; f.relay->Stop(); receive.join(); reader.Reset();
        Check(valid && SUCCEEDED(status));
    }

    void RelayRejectsMalformedRecord()
    {
        for (const wchar_t* mode : {L"video-track", L"video-sequence", L"video-pts"})
        {
            RelayFixture f(mode); f.Attach();
            Check(FAILED(f.relay->ReceiveOne()) && f.relay->IsRetired() && f.owner.retired == 1);
            DWORD flags = 0; Check(f.source->GetCharacteristics(&flags) == MF_E_SHUTDOWN);
            f.owner.original.current = true; Check(FAILED(f.relay->ReceiveOne()));
        }
    }

    void RelayRefusesReplacementSource()
    {
        RelayFixture original(L"empty"), replacement(L"empty");
        auto* held = original.reader.get();
        Check(VideoRelay::Create(original.reader, original.source.Get(), replacement.feed.Get(), original.relay) == E_ACCESSDENIED);
        Check(original.reader.get() == held && !original.relay && !held->IsRetired());
    }

    void RelayOriginalShutdownInterruptsInput()
    {
        RelayFixture f(L"empty"); f.Attach();
        f.owner.original.signalAt = f.owner.original.calls + 2;
        std::atomic<HRESULT> status{S_OK}; std::thread reading([&] { status = f.relay->ReceiveOne(); });
        const DWORD pending = WaitForSingleObject(f.owner.original.pending, 1500);
        const HRESULT shutdown = f.source->Shutdown(); reading.join();
        Check(pending == WAIT_OBJECT_0 && SUCCEEDED(shutdown) && FAILED(status) && f.relay->IsRetired() && f.owner.retired == 1);
    }

    void RelayRequiresActualSend()
    {
        RelayFixture f(L"video"); f.owner.sending = false; f.Attach();
        Check(FAILED(f.relay->ReceiveOne()) && f.relay->IsRetired() && f.owner.retired == 1);
        f.owner.sending = true; Check(FAILED(f.relay->ReceiveOne()));
    }

    struct AudioFixture
    {
        MediaRuntime runtime;
        RelayOwner owner;
        Peer peer;
        std::unique_ptr<PipeReader> reader;
        std::shared_ptr<Samples> samples;
        std::unique_ptr<AudioRelay> relay;
        explicit AudioFixture(const wchar_t* mode, bool muted = false) : peer(mode)
        {
            Ok(PipeReader::Connect(peer.id, peer.process, Owner::Current, &owner.original, reader));
            owner.process = peer.process; owner.pipe = reader.get();
            samples = std::make_shared<Samples>(RelayOwner::Sending, &owner, muted);
        }
        void Attach() { Ok(AudioRelay::Create(reader, samples, relay)); }
    };

    void AudioRelayCrossProcessFragments()
    {
        AudioFixture f(L"audio-fragments"); f.Attach();
        for (int i = 0; i < 2; ++i)
        {
            ComPtr<IMFSample> sample; Ok(f.relay->ReceiveOne(&sample)); Check(sample && !f.relay->IsRetired());
            LONGLONG pts = -1; Ok(sample->GetSampleTime(&pts)); Check(pts == i * 200000LL);
            ComPtr<IMFMediaBuffer> buffer; Ok(sample->ConvertToContiguousBuffer(&buffer));
            BYTE* bytes = nullptr; DWORD size = 0; Ok(buffer->Lock(&bytes, nullptr, &size));
            bool valid = size == Samples::AudioBytes;
            if (valid) for (DWORD at = 0; at < size; ++at) if (bytes[at] != static_cast<BYTE>(at * 31)) { valid = false; break; }
            Ok(buffer->Unlock()); Check(valid);
        }
    }

    void AudioRelayMalformedRetiresBoth()
    {
        for (const wchar_t* mode : {L"audio-version", L"audio-track", L"audio-sequence", L"audio-pts"})
        {
            AudioFixture f(mode); f.Attach(); IMFSample* sample = reinterpret_cast<IMFSample*>(1);
            Check(FAILED(f.relay->ReceiveOne(&sample)) && sample == nullptr && f.relay->IsRetired() && f.samples->IsRetired());
            std::vector<BYTE> picture(Samples::VideoBytes); ComPtr<IMFSample> video;
            Check(f.samples->Video(picture.data(), picture.size(), 0, 0, &video) == MF_E_SHUTDOWN && !video);
            f.owner.original.current = true; Check(FAILED(f.relay->ReceiveOne(&sample)) && sample == nullptr);
        }
    }

    void AudioRelayStopAndRevokePending()
    {
        for (bool stop : {true, false})
        {
            AudioFixture f(L"empty"); f.Attach();
            f.owner.original.signalAt = f.owner.original.calls + 2;
            std::atomic<HRESULT> status{S_OK}; IMFSample* sample = reinterpret_cast<IMFSample*>(1);
            std::thread receive([&] { status = f.relay->ReceiveOne(&sample); });
            const DWORD pending = WaitForSingleObject(f.owner.original.pending, 1500);
            if (stop) f.relay->Stop(); else f.owner.original.current = false;
            receive.join();
            Check(pending == WAIT_OBJECT_0 && FAILED(status) && sample == nullptr && f.relay->IsRetired() && f.samples->IsRetired());
        }
    }

    void AudioRelayOneRecordDeadline()
    {
        AudioFixture f(L"audio-short"); f.Attach();
        const auto begin = std::chrono::steady_clock::now(); ComPtr<IMFSample> sample;
        const HRESULT status = f.relay->ReceiveOne(&sample);
        const auto elapsed = std::chrono::steady_clock::now() - begin;
        Check(status == HRESULT_FROM_WIN32(ERROR_TIMEOUT) && !sample && f.relay->IsRetired() && f.samples->IsRetired());
        Check(elapsed >= std::chrono::milliseconds(1800) && elapsed < std::chrono::milliseconds(4500));
    }

    void AudioRelayMuteAndActualSend()
    {
        for (bool muted : {true, false})
        {
            AudioFixture f(L"audio", muted); f.owner.sending = muted; f.Attach();
            ComPtr<IMFSample> sample;
            Check(FAILED(f.relay->ReceiveOne(&sample)) && !sample && f.relay->IsRetired() && f.samples->IsRetired());
        }
    }

    void AudioRelayCreationAndNullOutput()
    {
        AudioFixture f(L"empty"); auto* held = f.reader.get();
        std::shared_ptr<Samples> missing;
        Check(AudioRelay::Create(f.reader, missing, f.relay) == E_INVALIDARG && f.reader.get() == held && !f.relay);
        auto retired = std::make_shared<Samples>(RelayOwner::Sending, &f.owner, false); retired->Retire();
        Check(AudioRelay::Create(f.reader, retired, f.relay) == E_INVALIDARG && f.reader.get() == held && !f.samples->IsRetired());
        f.Attach(); Check(!f.reader && !f.relay->IsRetired());
        AudioFixture replacement(L"empty"); auto* replacementPipe = replacement.reader.get();
        Check(AudioRelay::Create(replacement.reader, replacement.samples, f.relay) == E_INVALIDARG && replacement.reader.get() == replacementPipe);
        Check(f.relay->ReceiveOne(nullptr) == E_POINTER && f.relay->IsRetired() && f.samples->IsRetired());
    }

    void AudioRelayOriginalProcessExit()
    {
        AudioFixture f(L"empty"); f.Attach();
        SetEvent(f.peer.stop); Check(WaitForSingleObject(f.peer.process, 1500) == WAIT_OBJECT_0);
        ComPtr<IMFSample> sample;
        Check(FAILED(f.relay->ReceiveOne(&sample)) && !sample && f.relay->IsRetired() && f.samples->IsRetired());
    }
#endif

#ifdef MAGNOLIE_NATIVE_OUTPUT_LEASE_TESTS
    struct LeaseState
    {
        std::atomic<ULONGLONG> now{1000};
        std::atomic_int retired{0};
        std::atomic<HRESULT> reason{S_OK};
        static ULONGLONG Now(void* context) noexcept { return static_cast<LeaseState*>(context)->now.load(); }
        static void Retired(void* context, HRESULT reason) noexcept
        { auto& state = *static_cast<LeaseState*>(context); state.reason = reason; ++state.retired; }
        OutputLeaseOwner Callbacks() { return {Retired, this, nullptr, Now}; }
    };
    struct LeaseFixture
    {
        Owner original;
        LeaseState state;
        Peer peer;
        std::unique_ptr<PipeReader> reader;
        std::unique_ptr<OutputLease> lease;
        explicit LeaseFixture(const wchar_t* mode) : peer(mode)
        { Ok(PipeReader::Connect(peer.id, peer.process, Owner::Current, &original, reader)); }
        void Attach() { Ok(OutputLease::Create(reader, state.Callbacks(), lease)); }
    };
    void LeasePrepareSendStop()
    {
        Check(OutputLease::RecordBytes == 18);
        LeaseFixture f(L"lease-phases"); f.Attach();
        const auto callbacks = f.lease->Callbacks();
        Ok(f.lease->ReceiveOne()); Ok(callbacks.current(callbacks.context));
        Check(callbacks.sending(callbacks.context) == E_ACCESSDENIED && !f.lease->IsRetired());
        Ok(f.lease->ReceiveOne()); Ok(callbacks.current(callbacks.context)); Ok(callbacks.sending(callbacks.context));
        Check(f.lease->ReceiveOne() == MF_E_SHUTDOWN && f.lease->IsRetired() && f.state.retired == 1);
        Check(FAILED(f.lease->RequireSending()) && FAILED(f.lease->ReceiveOne()) && f.state.retired == 1);
        LeaseFixture fail(L"lease-one"); fail.Attach(); Ok(fail.lease->ReceiveOne());
        const auto original = fail.lease->Callbacks(); original.retired(original.context, E_ACCESSDENIED);
        Check(fail.lease->IsRetired() && fail.state.reason == E_ACCESSDENIED && fail.state.retired == 1);
        original.retired(original.context, E_FAIL); Check(fail.state.reason == E_ACCESSDENIED && fail.state.retired == 1);
    }
    void LeaseMalformedControl()
    {
        for (const wchar_t* mode : {L"lease-version", L"lease-phase", L"lease-send-first", L"lease-stop-expiry", L"lease-expired", L"lease-future", L"lease-integer"})
        {
            LeaseFixture f(mode); f.Attach();
            Check(FAILED(f.lease->ReceiveOne()) && f.lease->IsRetired() && f.state.retired == 1);
            Check(FAILED(f.lease->RequireCurrent()) && f.state.retired == 1);
        }
    }
    void LeaseSequenceAndPhaseCannotRollback()
    {
        for (const wchar_t* mode : {L"lease-replay", L"lease-gap", L"lease-rollback"})
        {
            LeaseFixture f(mode); f.Attach(); Ok(f.lease->ReceiveOne());
            if (std::wcscmp(mode, L"lease-rollback") == 0) { Ok(f.lease->ReceiveOne()); Ok(f.lease->RequireSending()); }
            Check(FAILED(f.lease->ReceiveOne()) && f.lease->IsRetired() && f.state.retired == 1);
        }
    }
    void LeaseExpiryCannotResurrect()
    {
        LeaseFixture late(L"lease-late-refresh"); late.Attach(); Ok(late.lease->ReceiveOne());
        late.state.now = 1200;
        Check(late.lease->ReceiveOne() == HRESULT_FROM_WIN32(ERROR_TIMEOUT) && late.state.retired == 1);
        late.state.now = 1000; Check(FAILED(late.lease->RequireCurrent()) && FAILED(late.lease->RequireSending()));
        LeaseFixture boundary(L"lease-boundary"); boundary.Attach(); Ok(boundary.lease->ReceiveOne());
        boundary.state.now = 1249; Ok(boundary.lease->RequireCurrent()); boundary.state.now = 1250;
        Check(boundary.lease->RequireCurrent() == HRESULT_FROM_WIN32(ERROR_TIMEOUT) && boundary.state.retired == 1);
        LeaseFixture clock(L"lease-one"); clock.Attach(); Ok(clock.lease->ReceiveOne()); clock.state.now = 999;
        Check(clock.lease->RequireCurrent() == E_INVALIDARG && clock.state.retired == 1);
    }
    void LeaseStopExpiryInterruptPending()
    {
        for (bool stop : {true, false})
        {
            LeaseFixture f(L"lease-one"); f.Attach(); Ok(f.lease->ReceiveOne());
            f.original.signalAt = f.original.calls + 2;
            std::atomic<HRESULT> status{S_OK}; std::thread receive([&] { status = f.lease->ReceiveOne(); });
            const DWORD pending = WaitForSingleObject(f.original.pending, 1500);
            if (stop) f.lease->Stop(); else { f.state.now = 1200; f.lease->RequireCurrent(); }
            receive.join();
            Check(pending == WAIT_OBJECT_0 && FAILED(status) && f.lease->IsRetired() && f.state.retired == 1);
        }
    }
    void LeaseOriginalProcessExit()
    {
        LeaseFixture f(L"lease-one"); f.Attach(); Ok(f.lease->ReceiveOne());
        SetEvent(f.peer.stop); Check(WaitForSingleObject(f.peer.process, 1500) == WAIT_OBJECT_0);
        Check(FAILED(f.lease->RequireCurrent()) && f.lease->IsRetired() && f.state.retired == 1);
    }
    void LeaseCreationHasNoGrant()
    {
        LeaseFixture f(L"empty"); auto* original = f.reader.get(); OutputLeaseOwner missing{};
        Check(OutputLease::Create(f.reader, missing, f.lease) == E_INVALIDARG && f.reader.get() == original && !f.lease);
        f.Attach(); Check(!f.reader && f.lease->Control() == original);
        LeaseFixture replacement(L"empty"); auto* replacementReader = replacement.reader.get();
        Check(OutputLease::Create(replacement.reader, replacement.state.Callbacks(), f.lease) == E_INVALIDARG && replacement.reader.get() == replacementReader);
        Check(f.lease->RequireCurrent() == E_ACCESSDENIED && f.state.retired == 1);
        Check(FAILED(f.lease->ReceiveOne()) && f.state.retired == 1);
        replacement.reader->Stop();
        Check(OutputLease::Create(replacement.reader, replacement.state.Callbacks(), replacement.lease) == E_INVALIDARG && replacement.reader.get() == replacementReader);
    }
    void LeaseConcurrentAndPartialDeadline()
    {
        LeaseFixture f(L"empty"); f.Attach(); f.original.signalAt = f.original.calls + 2;
        std::atomic<HRESULT> status{S_OK}; std::thread receive([&] { status = f.lease->ReceiveOne(); });
        const DWORD pending = WaitForSingleObject(f.original.pending, 1500);
        const HRESULT concurrent = f.lease->ReceiveOne(); receive.join();
        Check(pending == WAIT_OBJECT_0 && concurrent == HRESULT_FROM_WIN32(ERROR_BUSY) && FAILED(status) && f.state.retired == 1);
        LeaseFixture partial(L"lease-short"); partial.Attach(); const auto begin = std::chrono::steady_clock::now();
        Check(partial.lease->ReceiveOne() == HRESULT_FROM_WIN32(ERROR_TIMEOUT) && partial.state.retired == 1);
        const auto elapsed = std::chrono::steady_clock::now() - begin;
        Check(elapsed >= std::chrono::milliseconds(1800) && elapsed < std::chrono::milliseconds(4500));
    }
#endif
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
        {"pipe-concurrent-reader-refused", ConcurrentReadersAreRefused}, {"pipe-missing-owner-invalid-input", MissingOwnerAndInvalidInput},
#ifdef MAGNOLIE_NATIVE_RELAY_TESTS
        {"relay-real-cross-process-source-reader", RelayCrossProcessSourceReader}, {"relay-malformed-record", RelayRejectsMalformedRecord},
        {"relay-replacement-source-refused", RelayRefusesReplacementSource}, {"relay-original-shutdown-input", RelayOriginalShutdownInterruptsInput},
        {"relay-needs-actual-send", RelayRequiresActualSend},
        {"audio-relay-fragmented-pcm", AudioRelayCrossProcessFragments},
        {"audio-relay-malformed-retirement", AudioRelayMalformedRetiresBoth},
        {"audio-relay-stop-revoke", AudioRelayStopAndRevokePending},
        {"audio-relay-record-deadline", AudioRelayOneRecordDeadline},
        {"audio-relay-mute-send", AudioRelayMuteAndActualSend},
        {"audio-relay-create-null", AudioRelayCreationAndNullOutput},
        {"audio-relay-process-exit", AudioRelayOriginalProcessExit},
#endif
#ifdef MAGNOLIE_NATIVE_OUTPUT_LEASE_TESTS
        {"lease-prepare-send-stop", LeasePrepareSendStop}, {"lease-malformed-control", LeaseMalformedControl},
        {"lease-sequence-phase-rollback", LeaseSequenceAndPhaseCannotRollback}, {"lease-expiry-no-resurrection", LeaseExpiryCannotResurrect},
        {"lease-stop-expiry-pending", LeaseStopExpiryInterruptPending}, {"lease-original-process-exit", LeaseOriginalProcessExit},
        {"lease-create-no-grant", LeaseCreationHasNoGrant}, {"lease-concurrent-record-deadline", LeaseConcurrentAndPartialDeadline},
#endif
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
