#include "PhoneCameraOutputLease.h"
#include <mferror.h>
#include <array>
#include <limits>

namespace Magnolie::PhoneCamera
{
    HRESULT OutputLease::Create(std::unique_ptr<PipeReader>& reader,
        OutputLeaseOwner owner, std::unique_ptr<OutputLease>& result) noexcept
    {
        if (result || !reader || reader->IsRetired() || !owner.retired) return E_INVALIDARG;
        try
        {
            std::unique_ptr<OutputLease> lease(new OutputLease(owner));
            lease->reader_ = std::move(reader);
            result = std::move(lease); return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    ULONGLONG OutputLease::Now() const noexcept
    { return owner_.nowMs ? owner_.nowMs(owner_.context) : GetTickCount64(); }
    bool OutputLease::IsRetired() const noexcept
    { return retired_.load() || (reader_ && reader_->IsRetired()); }
    HRESULT OutputLease::Fail(HRESULT reason) noexcept
    {
        if (!retired_.exchange(true))
        {
            phase_.store(3); until_.store(0);
            if (reader_) reader_->Stop();
            owner_.retired(owner_.context, reason);
        }
        return reason;
    }
    void OutputLease::Stop() noexcept { Fail(MF_E_SHUTDOWN); }
    ClockOwner OutputLease::Callbacks() noexcept
    {
        return {
            [](void* context) noexcept { return static_cast<OutputLease*>(context)->RequireCurrent(); },
            [](void* context) noexcept { return static_cast<OutputLease*>(context)->RequireSending(); },
            [](void* context, HRESULT reason) noexcept { static_cast<OutputLease*>(context)->Fail(reason); },
            this, owner_.lifetime, nullptr
        };
    }

    HRESULT OutputLease::RequireCurrent() noexcept
    {
        if (IsRetired()) return Fail(MF_E_SHUTDOWN);
        HRESULT hr = reader_->RequireCurrent(); if (FAILED(hr)) return Fail(hr);
        const auto phase = phase_.load();
        const ULONGLONG until = until_.load(), received = receivedAt_.load();
        const ULONGLONG now = Now(); // Sample AFTER atomics, no stale-before-update clock value.
        if (phase != 1 && phase != 2) return Fail(E_ACCESSDENIED);
        if (now < received) return Fail(E_INVALIDARG);
        if (!until || now >= until) return Fail(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
        return IsRetired() ? Fail(MF_E_SHUTDOWN) : S_OK;
    }
    HRESULT OutputLease::RequireSending() noexcept
    {
        const HRESULT hr = RequireCurrent(); if (FAILED(hr)) return hr;
        if (phase_.load() != 2) return E_ACCESSDENIED; // Prepare is not actual SEND; no invented grant.
        return IsRetired() ? Fail(MF_E_SHUTDOWN) : S_OK;
    }

    HRESULT OutputLease::ReceiveOne() noexcept
    {
        try
        {
            std::unique_lock<std::mutex> lock(receive_, std::try_to_lock);
            if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
            std::array<BYTE, RecordBytes> record{};
            struct Clear { BYTE* data; std::size_t size; ~Clear() { SecureZeroMemory(data, size); } } clear{record.data(), record.size()};
            if (IsRetired()) return Fail(MF_E_SHUTDOWN);
            HRESULT hr = reader_->ReadExact(record.data(), record.size());
            if (FAILED(hr)) return Fail(hr);
            std::uint64_t sequence = 0, until = 0;
            for (unsigned int i = 0; i < 8; ++i)
            { sequence = (sequence << 8) | record[2 + i]; until = (until << 8) | record[10 + i]; }
            const unsigned int phase = record[1];
            if (record[0] != 1 || phase < 1 || phase > 3 || sequence != sequence_ ||
                sequence_ >= static_cast<std::uint64_t>((std::numeric_limits<LONGLONG>::max)()) ||
                (phase == 1 && phase_.load() == 2) || (!sequence_ && phase == 2)) return Fail(E_INVALIDARG);
            if (phase == 3) return until ? Fail(E_INVALIDARG) : Fail(MF_E_SHUTDOWN);
            const ULONGLONG now = Now();
            if (now < receivedAt_.load()) return Fail(E_INVALIDARG);
            // A fresh-looking record may NOT renew an already expired lease,
            // even if no output happened to query it during the silent gap.
            if (sequence_ && now >= until_.load()) return Fail(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
            if (until <= now || until - now > 250) return Fail(E_INVALIDARG);
            hr = reader_->RequireCurrent(); if (FAILED(hr)) return Fail(hr);
            receivedAt_.store(now); until_.store(until); phase_.store(phase); ++sequence_;
            return IsRetired() ? Fail(MF_E_SHUTDOWN) : S_OK;
        }
        catch (...) { return Fail(E_FAIL); }
    }
    OutputLease::~OutputLease()
    {
        Stop();
        // Original owner signals and joins its control read task first; contexts
        // and the borrowed Control() remain valid through dependent destruction.
        std::lock_guard<std::mutex> lock(receive_);
    }
}
