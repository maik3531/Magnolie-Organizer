#include "PhoneCameraPipe.h"
#include <objbase.h>
#include <chrono>

namespace Magnolie::PhoneCamera
{
    std::wstring PipeReader::Name(const GUID& session)
    {
        wchar_t text[40]{};
        if (session == GUID_NULL || !StringFromGUID2(session, text, 40)) return {};
        return std::wstring(L"\\\\.\\pipe\\Magnolie.PhoneCamera.") + text;
    }

    HRESULT PipeReader::Connect(const GUID& session, HANDLE originalServer,
        Current current, void* context, std::unique_ptr<PipeReader>& result) noexcept
    {
        // Do not silently destroy or replace another live reader supplied by a caller.
        if (result) return E_INVALIDARG;
        if (!current || !originalServer || originalServer == INVALID_HANDLE_VALUE || session == GUID_NULL) return E_INVALIDARG;
        try
        {
            std::unique_ptr<PipeReader> reader(new PipeReader(current, context));
            reader->stop_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            reader->completed_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            if (!reader->stop_ || !reader->completed_) return HRESULT_FROM_WIN32(GetLastError());
            if (!DuplicateHandle(GetCurrentProcess(), originalServer, GetCurrentProcess(), &reader->server_,
                0, FALSE, DUPLICATE_SAME_ACCESS)) return HRESULT_FROM_WIN32(GetLastError());
            HRESULT hr = reader->RequireCurrent(); if (FAILED(hr)) return hr;
            // Fixed LOCAL pipe namespace; no path, URL, executable or remote server
            // can be supplied. Overlapped mode is established here, never assumed.
            reader->pipe_ = CreateFileW(Name(session).c_str(), GENERIC_READ, 0, nullptr, OPEN_EXISTING,
                FILE_FLAG_OVERLAPPED | SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, nullptr);
            if (reader->pipe_ == INVALID_HANDLE_VALUE) return HRESULT_FROM_WIN32(GetLastError());
            ULONG actual = 0; DWORD flags = 0;
            if (!GetNamedPipeServerProcessId(reader->pipe_, &actual) || !GetNamedPipeInfo(reader->pipe_, &flags, nullptr, nullptr, nullptr))
                return HRESULT_FROM_WIN32(GetLastError());
            const DWORD expected = GetProcessId(reader->server_);
            if (!expected || actual != expected || (flags & PIPE_TYPE_MESSAGE)) return E_ACCESSDENIED;
            hr = reader->RequireCurrent(); if (FAILED(hr)) return hr;
            result = std::move(reader);
            return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }

    bool PipeReader::IsRetired() const noexcept { return retired_.load(); }
    void PipeReader::Stop() noexcept
    {
        retired_.store(true);
        if (stop_) SetEvent(stop_); // No reader lock: wake even a blocked read.
    }

    HRESULT PipeReader::RequireCurrent() noexcept
    {
        if (IsRetired()) return HRESULT_FROM_WIN32(ERROR_OPERATION_ABORTED);
        const HRESULT hr = current_(context_);
        if (hr != S_OK) { Stop(); return FAILED(hr) ? hr : E_ACCESSDENIED; }
        if (IsRetired()) return HRESULT_FROM_WIN32(ERROR_OPERATION_ABORTED);
        // Hold the actual original process object; never look a peer up again by PID.
        if (server_ && WaitForSingleObject(server_, 0) != WAIT_TIMEOUT)
        { Stop(); return HRESULT_FROM_WIN32(ERROR_BROKEN_PIPE); }
        return S_OK;
    }

    HRESULT PipeReader::ReadExact(BYTE* target, std::size_t bytes) noexcept
    {
        if (!target || !bytes || bytes > MaxRead) { Stop(); return E_INVALIDARG; }
        HRESULT hr = S_OK;
        try
        {
            std::unique_lock<std::mutex> lock(reader_, std::try_to_lock);
            if (!lock.owns_lock())
            { Stop(); SecureZeroMemory(target, bytes); return HRESULT_FROM_WIN32(ERROR_BUSY); }
            const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
            std::size_t at = 0;
            while (at < bytes)
            {
                hr = RequireCurrent(); if (FAILED(hr)) break;
                if (std::chrono::steady_clock::now() >= deadline) { hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT); break; }
                ResetEvent(completed_);
                OVERLAPPED operation{}; operation.hEvent = completed_;
                DWORD count = 0;
                if (ReadFile(pipe_, target + at, static_cast<DWORD>(bytes - at), &count, &operation))
                {
                    if (!count) { hr = HRESULT_FROM_WIN32(ERROR_BROKEN_PIPE); break; }
                    at += count; continue;
                }
                DWORD error = GetLastError();
                if (error != ERROR_IO_PENDING) { hr = HRESULT_FROM_WIN32(error); break; }
                const HANDLE waits[] = {stop_, server_, completed_};
                bool pending = true;
                while (pending)
                {
                    hr = RequireCurrent(); if (FAILED(hr)) break;
                    const auto now = std::chrono::steady_clock::now();
                    if (now >= deadline) { hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT); break; }
                    const DWORD elapsed = WaitForMultipleObjects(3, waits, FALSE, 10);
                    if (elapsed == WAIT_OBJECT_0 || elapsed == WAIT_OBJECT_0 + 1)
                    { hr = HRESULT_FROM_WIN32(ERROR_OPERATION_ABORTED); break; }
                    if (elapsed == WAIT_FAILED) { hr = HRESULT_FROM_WIN32(GetLastError()); break; }
                    if (elapsed == WAIT_OBJECT_0 + 2)
                    {
                        if (!GetOverlappedResult(pipe_, &operation, &count, FALSE)) hr = HRESULT_FROM_WIN32(GetLastError());
                        else if (!count) hr = HRESULT_FROM_WIN32(ERROR_BROKEN_PIPE);
                        pending = false;
                    }
                }
                if (pending)
                {
                    // Drain ONLY this read before its OVERLAPPED/event can die.
                    // No cancel-all, foreign handle close or process termination.
                    CancelIoEx(pipe_, &operation);
                    DWORD ignored = 0; GetOverlappedResult(pipe_, &operation, &ignored, TRUE);
                }
                if (FAILED(hr)) break;
                at += count;
            }
            if (SUCCEEDED(hr)) hr = RequireCurrent();
        }
        catch (...) { hr = E_FAIL; }
        if (FAILED(hr)) { Stop(); SecureZeroMemory(target, bytes); }
        return hr;
    }

    PipeReader::~PipeReader()
    {
        Stop();
        // Native owner must keep the context alive and join its read task before
        // destroying the reader. This lock also prevents releasing pending IO.
        std::lock_guard<std::mutex> lock(reader_);
        if (pipe_ != INVALID_HANDLE_VALUE) CloseHandle(pipe_);
        if (server_) CloseHandle(server_);
        if (completed_) CloseHandle(completed_);
        if (stop_) CloseHandle(stop_);
    }
}
