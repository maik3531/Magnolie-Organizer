#include "../../native/phone-camera/PhoneCameraAudioRender.h"
#include "../../native/phone-camera/PhoneCameraPipe.h"
#include "../../native/phone-camera/PhoneCameraOutputLease.h"
#include <mfapi.h>
#include <mferror.h>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <stdexcept>
#include <thread>
#include <vector>

using namespace Magnolie::PhoneCamera;
using Microsoft::WRL::ComPtr;

namespace
{
    void Check(bool value) { if (!value) throw std::runtime_error("audio render assertion"); }
    void Ok(HRESULT hr) { if (FAILED(hr)) { std::printf("HRESULT %08lx\n", static_cast<unsigned long>(hr)); Check(false); } }
    struct Owner
    {
        bool current = true, sending = true;
        std::atomic_int calls{0}, retired{0};
        int denyAt = 0;
        LONGLONG now = 1000000;
        static HRESULT Current(void* context) noexcept
        { auto& o = *static_cast<Owner*>(context); return o.current && ++o.calls != o.denyAt ? S_OK : E_ACCESSDENIED; }
        static HRESULT Sending(void* context) noexcept
        { return static_cast<Owner*>(context)->sending ? S_OK : E_ACCESSDENIED; }
        static void Retired(void* context, HRESULT) noexcept { ++static_cast<Owner*>(context)->retired; }
        static LONGLONG Now(void* context) noexcept { return static_cast<Owner*>(context)->now; }
        ClockOwner Callbacks() { return {Current, Sending, Retired, this, nullptr, Now}; }
    };

    class FakeClient final : public IAudioClient
    {
        LONG refs_ = 1;
    public:
        std::atomic<UINT32> padding{0};
        int starts = 0, stops = 0, resets = 0;
        HRESULT paddingResult = S_OK, startResult = S_OK;
        DWORD paddingDelayMs = 0, startDelayMs = 0;
        HANDLE paddingSeen = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        ~FakeClient() { if (paddingSeen) CloseHandle(paddingSeen); }
        HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** result) override
        {
            if (!result) return E_POINTER; *result = nullptr;
            if (iid != __uuidof(IUnknown) && iid != __uuidof(IAudioClient)) return E_NOINTERFACE;
            *result = static_cast<IAudioClient*>(this); AddRef(); return S_OK;
        }
        ULONG STDMETHODCALLTYPE AddRef() override { return static_cast<ULONG>(InterlockedIncrement(&refs_)); }
        ULONG STDMETHODCALLTYPE Release() override { const auto left = InterlockedDecrement(&refs_); if (!left) delete this; return static_cast<ULONG>(left); }
        HRESULT STDMETHODCALLTYPE Initialize(AUDCLNT_SHAREMODE, DWORD, REFERENCE_TIME, REFERENCE_TIME, const WAVEFORMATEX*, LPCGUID) override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE GetBufferSize(UINT32*) override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE GetStreamLatency(REFERENCE_TIME*) override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE GetCurrentPadding(UINT32* result) override { SetEvent(paddingSeen); if (paddingDelayMs) Sleep(paddingDelayMs); *result = padding.load(); return paddingResult; }
        HRESULT STDMETHODCALLTYPE IsFormatSupported(AUDCLNT_SHAREMODE, const WAVEFORMATEX*, WAVEFORMATEX**) override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE GetMixFormat(WAVEFORMATEX**) override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE GetDevicePeriod(REFERENCE_TIME*, REFERENCE_TIME*) override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE Start() override { ++starts; if (startDelayMs) Sleep(startDelayMs); return startResult; }
        HRESULT STDMETHODCALLTYPE Stop() override { ++stops; return S_OK; }
        HRESULT STDMETHODCALLTYPE Reset() override { ++resets; return S_OK; }
        HRESULT STDMETHODCALLTYPE SetEventHandle(HANDLE) override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE GetService(REFIID, void**) override { return E_NOTIMPL; }
    };

    class FakeWriter final : public IAudioRenderClient
    {
        LONG refs_ = 1;
    public:
        std::vector<float> bytes = std::vector<float>(1920, 99.0f);
        UINT32 requested = 0, released = 0;
        DWORD flags = ~0UL;
        int gets = 0, commits = 0;
        bool nullBuffer = false;
        HRESULT getResult = S_OK, releaseResult = S_OK;
        DWORD getDelayMs = 0, releaseDelayMs = 0;
        Owner* revokeAtGet = nullptr;
        HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** result) override
        {
            if (!result) return E_POINTER; *result = nullptr;
            if (iid != __uuidof(IUnknown) && iid != __uuidof(IAudioRenderClient)) return E_NOINTERFACE;
            *result = static_cast<IAudioRenderClient*>(this); AddRef(); return S_OK;
        }
        ULONG STDMETHODCALLTYPE AddRef() override { return static_cast<ULONG>(InterlockedIncrement(&refs_)); }
        ULONG STDMETHODCALLTYPE Release() override { const auto left = InterlockedDecrement(&refs_); if (!left) delete this; return static_cast<ULONG>(left); }
        HRESULT STDMETHODCALLTYPE GetBuffer(UINT32 frames, BYTE** data) override
        {
            ++gets; requested = frames; *data = nullBuffer ? nullptr : reinterpret_cast<BYTE*>(bytes.data());
            if (getDelayMs) Sleep(getDelayMs);
            if (revokeAtGet) revokeAtGet->current = false;
            return getResult;
        }
        HRESULT STDMETHODCALLTYPE ReleaseBuffer(UINT32 frames, DWORD actualFlags) override
        { ++commits; released = frames; flags = actualFlags; if (releaseDelayMs) Sleep(releaseDelayMs); return releaseResult; }
    };
}

namespace Magnolie::PhoneCamera
{
    struct AudioRenderTestAccess
    {
        static HRESULT Parent(PipeReader* reader) { return AudioRender::AdmitParent(reader); }
        static HRESULT PrepareCurrent(AudioRender& renderer) { return renderer.Check(false); }
        static std::unique_ptr<AudioRender> Prepared(ClockOwner owner, IAudioClient* client, IAudioRenderClient* writer)
        {
            std::unique_ptr<AudioRender> result(new AudioRender(owner));
            result->client_ = client; result->writer_ = writer; result->capacity_ = 1920;
            result->stop_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            result->ready_ = CreateEventW(nullptr, FALSE, FALSE, nullptr);
            Check(result->stop_ && result->ready_); return result;
        }
    };
}

namespace
{
    struct Fixture
    {
        Owner owner;
        ComPtr<FakeClient> client;
        ComPtr<FakeWriter> writer;
        std::unique_ptr<AudioRender> output;
        Fixture()
        {
            client.Attach(new FakeClient); writer.Attach(new FakeWriter);
            output = AudioRenderTestAccess::Prepared(owner.Callbacks(), client.Get(), writer.Get());
        }
    };
    ComPtr<IMFSample> Packet()
    {
        ComPtr<IMFSample> sample; ComPtr<IMFMediaBuffer> buffer;
        Ok(MFCreateSample(&sample)); Ok(MFCreateMemoryBuffer(1920, &buffer));
        BYTE* bytes = nullptr; Ok(buffer->Lock(&bytes, nullptr, nullptr));
        const BYTE pattern[] = {0, 0x80, 0xff, 0x7f, 0xff, 0xff, 0, 0, 0x34, 0x12};
        for (std::size_t i = 0; i < 1920; ++i) bytes[i] = pattern[i % sizeof(pattern)];
        Ok(buffer->Unlock()); Ok(buffer->SetCurrentLength(1920)); Ok(sample->AddBuffer(buffer.Get()));
        Ok(sample->SetSampleTime(1234567890)); Ok(sample->SetSampleDuration(200000)); return sample;
    }

    void ExactPcmAndSessionStart()
    {
        Fixture f; auto sample = Packet(); Ok(f.output->Write(sample.Get(), f.owner.now));
        const float pattern[] = {-1.0f, 32767.0f / 32768.0f, -1.0f / 32768.0f, 0.0f, 4660.0f / 32768.0f};
        for (std::size_t i = 0; i < 960; ++i)
            Check(f.writer->bytes[2 * i] == pattern[i % 5] && f.writer->bytes[2 * i + 1] == pattern[i % 5]);
        Check(f.writer->requested == 960 && f.writer->released == 960 && f.writer->flags == 0 && f.client->starts == 1);
        Ok(f.output->Write(sample.Get(), f.owner.now)); Check(f.client->starts == 1);
        f.output.reset(); Check(f.client->stops == 1 && f.client->resets == 1 && f.owner.retired == 1);
    }

    void InvalidSamplesNeverAcquireBuffer()
    {
        for (int invalid = 0; invalid < 6; ++invalid)
        {
            Fixture f; auto sample = Packet();
            if (invalid == 1) Ok(sample->SetSampleDuration(200001));
            if (invalid == 2) Ok(sample->SetSampleTime(-1));
            if (invalid == 3) Ok(sample->SetSampleTime(90071992547409911LL));
            if (invalid == 4) Ok(sample->RemoveAllBuffers());
            if (invalid == 5) { ComPtr<IMFMediaBuffer> buffer; Ok(sample->GetBufferByIndex(0, &buffer)); Ok(buffer->SetCurrentLength(1919)); }
            Check(FAILED(f.output->Write(invalid == 0 ? nullptr : sample.Get(), f.owner.now)));
            Check(f.output->IsRetired() && f.owner.retired == 1 && f.writer->gets == 0 && f.client->starts == 0);
        }
    }

    void OriginalGuardsAndCommitSilence()
    {
        for (int boundary = 1; boundary <= 8; ++boundary)
        {
            Fixture f; f.owner.denyAt = boundary; auto sample = Packet();
            Check(FAILED(f.output->Write(sample.Get(), f.owner.now)) && f.output->IsRetired() && f.owner.retired == 1);
            if (f.writer->gets && !f.client->starts && boundary <= 6)
                Check(f.writer->flags == AUDCLNT_BUFFERFLAGS_SILENT && std::all_of(f.writer->bytes.begin(), f.writer->bytes.end(), [](float v) { return v == 0.0f; }));
        }
        Fixture f; auto sample = Packet(); f.writer->revokeAtGet = &f.owner;
        Check(FAILED(f.output->Write(sample.Get(), f.owner.now)) && f.writer->flags == AUDCLNT_BUFFERFLAGS_SILENT && f.client->starts == 0);
        Check(std::all_of(f.writer->bytes.begin(), f.writer->bytes.end(), [](float v) { return v == 0.0f; }));
        f.owner.current = true; Check(FAILED(f.output->Write(sample.Get(), f.owner.now)) && f.owner.retired == 1);
    }

    void ClientFailuresAndBounds()
    {
        for (int failure = 0; failure < 6; ++failure)
        {
            Fixture f; auto sample = Packet();
            if (failure == 0) f.client->paddingResult = E_FAIL;
            if (failure == 1) f.client->padding = 1921;
            if (failure == 2) f.writer->getResult = E_FAIL;
            if (failure == 3) f.writer->releaseResult = E_FAIL;
            if (failure == 4) f.client->startResult = E_FAIL;
            if (failure == 5) f.writer->nullBuffer = true;
            Check(FAILED(f.output->Write(sample.Get(), f.owner.now)) && f.output->IsRetired() && f.owner.retired == 1);
            if (failure == 5) Check(f.writer->flags == AUDCLNT_BUFFERFLAGS_SILENT);
        }
    }

    void StopAndConcurrentPendingWrite()
    {
        for (bool concurrent : {false, true})
        {
            Fixture f; f.client->padding = 1920; auto sample = Packet(); std::atomic<HRESULT> status{S_OK};
            std::thread worker([&] { status = f.output->Write(sample.Get(), f.owner.now); });
            const DWORD pending = WaitForSingleObject(f.client->paddingSeen, 1500);
            HRESULT second = S_OK;
            if (concurrent) second = f.output->Write(sample.Get(), f.owner.now); else f.output->Stop();
            worker.join();
            Check(pending == WAIT_OBJECT_0 && FAILED(status) && (!concurrent || FAILED(second)) && f.writer->gets == 0 && f.owner.retired == 1);
        }
    }

    void PresentationAndBufferDeadline()
    {
        for (LONGLONG offset : {-250001LL, 250001LL})
        {
            Fixture f; auto sample = Packet();
            Check(FAILED(f.output->Write(sample.Get(), f.owner.now + offset)) && f.writer->gets == 0 && f.output->IsRetired());
        }
        Fixture f; f.client->padding = 1920; auto sample = Packet(); const ULONGLONG begin = GetTickCount64();
        Check(f.output->Write(sample.Get(), f.owner.now) == HRESULT_FROM_WIN32(ERROR_TIMEOUT));
        Check(GetTickCount64() - begin >= 200 && GetTickCount64() - begin < 1500 && f.writer->gets == 0);
        Fixture rollback; Ok(rollback.output->Write(sample.Get(), rollback.owner.now)); --rollback.owner.now;
        Check(FAILED(rollback.output->Write(sample.Get(), rollback.owner.now)) && rollback.output->IsRetired());
    }

    void MissingOwnerParentAndSendBeforeWrite()
    {
        std::unique_ptr<AudioRender> result;
        Check(AudioRender::Open(nullptr, result) == E_INVALIDARG && !result);
        // No productive raw-callback factory: the real lease is mandatory.
        Fixture revoked; revoked.owner.current = false; auto refused = Packet();
        Check(FAILED(revoked.output->Write(refused.Get(), revoked.owner.now)) && revoked.writer->gets == 0);
        Fixture prepared; prepared.owner.sending = false; auto sample = Packet();
        Ok(AudioRenderTestAccess::PrepareCurrent(*prepared.output));
        Check(!prepared.output->IsRetired() && prepared.writer->gets == 0 && prepared.client->starts == 0);
        Check(FAILED(prepared.output->Write(sample.Get(), prepared.owner.now)) && prepared.writer->gets == 0 && prepared.client->starts == 0);
    }

    void LateReturningComNeverReportsSuccess()
    {
        for (int stage = 0; stage < 4; ++stage)
        {
            Fixture f; auto sample = Packet();
            if (stage == 0) f.client->paddingDelayMs = 300;
            if (stage == 1) f.writer->getDelayMs = 300;
            if (stage == 2) f.writer->releaseDelayMs = 300;
            if (stage == 3) f.client->startDelayMs = 300;
            Check(f.output->Write(sample.Get(), f.owner.now) == HRESULT_FROM_WIN32(ERROR_TIMEOUT));
            Check(f.output->IsRetired() && f.owner.retired == 1);
            if (stage == 0) Check(f.writer->gets == 0);
            if (stage == 1) Check(f.writer->flags == AUDCLNT_BUFFERFLAGS_SILENT && f.client->starts == 0 &&
                std::all_of(f.writer->bytes.begin(), f.writer->bytes.end(), [](float v) { return v == 0.0f; }));
            if (stage == 2) Check(f.client->starts == 0);
            // An already committed/started COM call cannot be undone by a timer.
            // Failure signals the original joined owner; its isolated worker exits.
        }
    }

    struct Handle
    {
        HANDLE value = INVALID_HANDLE_VALUE;
        ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    };
    struct Child : Handle
    {
        ~Child()
        {
            if (value && value != INVALID_HANDLE_VALUE && WaitForSingleObject(value, 3000) != WAIT_OBJECT_0)
            { TerminateProcess(value, 99); WaitForSingleObject(value, 3000); }
        }
    };
    int ParentChild(const char* id, const char* pid)
    {
        wchar_t guid[40]{}; GUID session{}; char* end = nullptr;
        const unsigned long long number = std::strtoull(pid, &end, 10);
        if (!end || *end || !number || number > 0xffffffffULL ||
            !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, id, -1, guid, 40) || FAILED(CLSIDFromString(guid, &session))) return 10;
        Handle parent; parent.value = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, static_cast<DWORD>(number));
        if (!parent.value) return 11;
        Owner owner; std::unique_ptr<PipeReader> reader;
        HRESULT hr = PipeReader::Connect(session, parent.value, Owner::Current, &owner, reader);
        if (SUCCEEDED(hr)) hr = AudioRenderTestAccess::Parent(reader.get());
        return SUCCEEDED(hr) ? 0 : 12; // Never call Open/Initialize or an actual audio client.
    }

    void ActualParentAdmissionAndNoUiFallback()
    {
        GUID session{}; Ok(CoCreateGuid(&session));
        Handle server; server.value = CreateNamedPipeW(PipeReader::Name(session).c_str(),
            PIPE_ACCESS_OUTBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE | FILE_FLAG_OVERLAPPED,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, 1, 1024, 1024, 0, nullptr);
        Check(server.value != INVALID_HANDLE_VALUE);
        Handle self; Check(DuplicateHandle(GetCurrentProcess(), GetCurrentProcess(), GetCurrentProcess(), &self.value, 0, FALSE, DUPLICATE_SAME_ACCESS) != FALSE);
        Owner owner; std::unique_ptr<PipeReader> reader;
        Ok(PipeReader::Connect(session, self.value, Owner::Current, &owner, reader));
        Check(AudioRenderTestAccess::Parent(reader.get()) == E_ACCESSDENIED);
        OutputLeaseOwner leaseOwner{Owner::Retired, &owner, nullptr, nullptr};
        std::unique_ptr<OutputLease> lease; Ok(OutputLease::Create(reader, leaseOwner, lease));
        std::unique_ptr<AudioRender> output;
        // A real pipe alone does not grant prepare: no accepted lease yet.
        Check(AudioRender::Open(lease.get(), output) == E_ACCESSDENIED && !output && lease->IsRetired());
        lease.reset(); DisconnectNamedPipe(server.value);

        // A failed lease is never reopened in place. Use a NEW original test
        // context/namespace; a disconnected instance is not yet listening again.
        CloseHandle(server.value); server.value = INVALID_HANDLE_VALUE;
        Ok(CoCreateGuid(&session));
        server.value = CreateNamedPipeW(PipeReader::Name(session).c_str(),
            PIPE_ACCESS_OUTBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE | FILE_FLAG_OVERLAPPED,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, 1, 1024, 1024, 0, nullptr);
        Check(server.value != INVALID_HANDLE_VALUE);
        Owner preparedOwner;
        Ok(PipeReader::Connect(session, self.value, Owner::Current, &preparedOwner, reader));
        OutputLeaseOwner preparedLeaseOwner{Owner::Retired, &preparedOwner, nullptr,
            [](void* context) noexcept { return static_cast<ULONGLONG>(static_cast<Owner*>(context)->now / 1000); }};
        Ok(OutputLease::Create(reader, preparedLeaseOwner, lease));
        std::array<BYTE, OutputLease::RecordBytes> record{}; record[0] = 1; record[1] = 1;
        const ULONGLONG until = static_cast<ULONGLONG>(preparedOwner.now / 1000) + 250;
        for (unsigned int i = 0; i < 8; ++i) record[10 + i] = static_cast<BYTE>(until >> (56 - 8 * i));
        Handle sent; sent.value = CreateEventW(nullptr, TRUE, FALSE, nullptr); Check(sent.value);
        OVERLAPPED written{}; written.hEvent = sent.value; DWORD bytes = 0;
        bool complete = WriteFile(server.value, record.data(), static_cast<DWORD>(record.size()), &bytes, &written) != FALSE;
        if (!complete && GetLastError() == ERROR_IO_PENDING)
        {
            if (WaitForSingleObject(sent.value, 1500) == WAIT_OBJECT_0)
                complete = GetOverlappedResult(server.value, &written, &bytes, FALSE) != FALSE;
            else { CancelIoEx(server.value, &written); DWORD ignored = 0; GetOverlappedResult(server.value, &written, &ignored, TRUE); }
        }
        Check(complete && bytes == record.size());
        Ok(lease->ReceiveOne()); Ok(lease->RequireCurrent());
        Check(lease->RequireSending() == E_ACCESSDENIED && !lease->IsRetired());
        // Even a valid PREPARE cannot admit the UI process as its own child.
        Check(AudioRender::Open(lease.get(), output) == E_ACCESSDENIED && !output && lease->IsRetired());
        lease.reset(); DisconnectNamedPipe(server.value);

        wchar_t path[32768]{}, text[40]{};
        Check(GetModuleFileNameW(nullptr, path, 32768) != 0 && StringFromGUID2(session, text, 40));
        std::wstring command = std::wstring(L"\"") + path + L"\" --parent-check " + text + L" " + std::to_wstring(GetCurrentProcessId());
        STARTUPINFOW startup{}; startup.cb = sizeof(startup); PROCESS_INFORMATION process{};
        Child child; Handle thread, event; event.value = CreateEventW(nullptr, TRUE, FALSE, nullptr); Check(event.value);
        OVERLAPPED operation{}; operation.hEvent = event.value;
        const bool connected = ConnectNamedPipe(server.value, &operation) != FALSE;
        const DWORD error = connected ? ERROR_SUCCESS : GetLastError();
        Check(connected || error == ERROR_IO_PENDING || error == ERROR_PIPE_CONNECTED);
        bool pending = error == ERROR_IO_PENDING;
        bool launched = false, completed = false;
        try
        {
            launched = CreateProcessW(path, command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                nullptr, nullptr, &startup, &process) != FALSE;
            if (launched) { child.value = process.hProcess; thread.value = process.hThread; }
            if (launched && pending)
            {
                if (WaitForSingleObject(event.value, 3000) == WAIT_OBJECT_0)
                { DWORD ignored = 0; GetOverlappedResult(server.value, &operation, &ignored, FALSE); pending = false; }
            }
            completed = launched && WaitForSingleObject(child.value, 3000) == WAIT_OBJECT_0;
        }
        catch (...) { if (pending) { CancelIoEx(server.value, &operation); DWORD ignored = 0; GetOverlappedResult(server.value, &operation, &ignored, TRUE); } throw; }
        if (pending) { CancelIoEx(server.value, &operation); DWORD ignored = 0; GetOverlappedResult(server.value, &operation, &ignored, TRUE); }
        DWORD code = ~0UL; if (completed) Check(GetExitCodeProcess(child.value, &code) != FALSE);
        Check(launched && completed && code == 0);
    }
}

int main(int argc, char** argv)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    if (argc == 4 && std::strcmp(argv[1], "--parent-check") == 0)
    { const int result = ParentChild(argv[2], argv[3]); CoUninitialize(); return result; }
    if (argc > 2) { CoUninitialize(); return 4; }
    const std::string selection = argc == 2 ? "," + std::string(argv[1]) + "," : "";
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET))) { CoUninitialize(); return 3; }
    int failed = 0;
    const struct { const char* name; void (*run)(); } tests[] = {
        {"render-exact-pcm-start-cleanup", ExactPcmAndSessionStart},
        {"render-invalid-sample-no-buffer", InvalidSamplesNeverAcquireBuffer},
        {"render-original-guards-silence", OriginalGuardsAndCommitSilence},
        {"render-client-failures-bounds", ClientFailuresAndBounds},
        {"render-stop-concurrent-pending", StopAndConcurrentPendingWrite},
        {"render-presentation-whole-deadline", PresentationAndBufferDeadline},
        {"render-no-owner-parent-send-write", MissingOwnerParentAndSendBeforeWrite},
        {"render-actual-parent-no-ui-fallback", ActualParentAdmissionAndNoUiFallback},
        {"render-late-com-no-success", LateReturningComNeverReportsSuccess}
    };
    for (const auto& test : tests)
    {
        if (!selection.empty() && selection.find("," + std::string(test.name) + ",") == std::string::npos) continue;
        try { test.run(); std::printf("PASS %s\n", test.name); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
    }
    MFShutdown(); CoUninitialize(); return failed ? 1 : 0;
}
