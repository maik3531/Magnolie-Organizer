#include "PhoneCameraSourceBrokerParent.h"
#include "PhoneCameraBrokerChannel.h"
#include "PhoneCameraBrokerProtocol.h"
#include "PhoneCameraFrameServerPeer.h"
#include <mferror.h>
#include <array>
#include <cstring>
#include <limits>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        std::atomic_bool uncertainBroker{false};
        HRESULT Exact(HRESULT hr) noexcept { return hr == S_OK ? S_OK : FAILED(hr) ? hr : E_ACCESSDENIED; }
        struct Clear { BYTE* bytes; std::size_t size; ~Clear() { SecureZeroMemory(bytes, size); } };
    }
    struct SourceBrokerParent::Hold
    {
        Hold(std::shared_ptr<VirtualCamera> originalCamera, SourceBrokerOwner originalOwner)
            : camera(std::move(originalCamera)), owner(originalOwner), lifetime(originalOwner.output.lifetime) {}
        ~Hold() { if (stop) CloseHandle(stop); if (bound) CloseHandle(bound); }
        std::shared_ptr<VirtualCamera> camera;
        SourceBrokerOwner owner;
        Microsoft::WRL::ComPtr<IUnknown> lifetime;
        BrokerProperty property;
        std::unique_ptr<BrokerChannel> channel;
        std::shared_ptr<FrameServerPeer> peer;
        HANDLE stop = nullptr, bound = nullptr;
    };
    SourceBrokerParent::SourceBrokerParent(std::unique_ptr<Hold> hold) noexcept : hold_(std::move(hold)) {}
    SourceBrokerParent::~SourceBrokerParent()
    {
        if (FAILED(Close()))
        {
            // Preallocated capsule retains the exact unconfirmed original
            // COM/module/manager/pipe/stop references without a retry/allocation.
            // Worker is already joined; no future callback can use this wrapper.
            hold_->property.ClearKey(); hold_.release();
        }
        else { hold_->peer.reset(); hold_->channel.reset(); }
    }
    HRESULT SourceBrokerParent::TransportCurrent(void* context) noexcept
    {
        auto& self = *static_cast<SourceBrokerParent*>(context);
        // Registration peer/terminal accounting remains readable after SEND
        // revocation. Every control/media write separately requires capture.
        return self.hold_->camera->RequireCurrent();
    }
    HRESULT SourceBrokerParent::CaptureCurrent() noexcept
    {
        if (stopped_.load()) return MF_E_SHUTDOWN;
        HRESULT hr = Exact(hold_->owner.output.current(hold_->owner.output.context));
        if (SUCCEEDED(hr)) hr = TransportCurrent(this);
        if (SUCCEEDED(hr) && hold_->peer) hr = hold_->peer->RequireCurrent();
        if (FAILED(hr)) return Fail(hr);
        return stopped_.load() ? MF_E_SHUTDOWN : S_OK;
    }
    void SourceBrokerParent::PeerRetired(void* context, HRESULT reason) noexcept
    { static_cast<SourceBrokerParent*>(context)->Fail(reason); }
    HRESULT SourceBrokerParent::Fail(HRESULT reason) noexcept
    {
        if (!stopped_.exchange(true))
        {
            if (hold_->stop) SetEvent(hold_->stop);
            hold_->owner.output.retired(hold_->owner.output.context, reason);
        }
        return reason;
    }
    void SourceBrokerParent::Stop() noexcept
    { stopped_.store(true); if (hold_->stop) SetEvent(hold_->stop); }
    HRESULT SourceBrokerParent::Prepare(const GUID& scope, std::shared_ptr<VirtualCamera> camera, SourceBrokerOwner owner,
        std::unique_ptr<SourceBrokerParent>& result) noexcept
    {
        if (result || !camera || scope == GUID_NULL || !owner.output.current || !owner.output.sending || !owner.output.retired ||
            !owner.output.context || !owner.output.lifetime || owner.output.nowMs || !owner.exportAnchor) return E_INVALIDARG;
        if (uncertainBroker.load()) return HRESULT_FROM_WIN32(ERROR_BUSY);
        std::unique_ptr<SourceBrokerParent> parent;
        try
        {
            parent.reset(new SourceBrokerParent(std::make_unique<Hold>(std::move(camera), owner)));
            HRESULT hr = parent->CaptureCurrent(); if (FAILED(hr)) return hr;
            hr = BrokerProperty::CreateOriginal(scope, parent->hold_->property); if (FAILED(hr)) return hr;
            hr = BrokerChannel::CreateServer(parent->hold_->property.Pipe(), {TransportCurrent, parent.get(), owner.output.lifetime}, parent->hold_->channel);
            if (FAILED(hr)) return hr;
            hr = BrokerChannel::CreateStopEvent(parent->hold_->property.Pipe(), parent->hold_->stop); if (FAILED(hr)) return hr;
            parent->hold_->bound = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            if (!parent->hold_->bound) return HRESULT_FROM_WIN32(GetLastError());
            std::array<BYTE, BrokerProperty::Bytes> property{}; parent->hold_->property.CopyForProperty(property);
            Clear clear{property.data(), property.size()};
            parent->worker_ = std::thread([raw = parent.get()] { raw->Run(); });
            // ONE original manager/property call; always awaited, even on stop.
            hr = parent->hold_->camera->SendSourceBinding(property.data(), static_cast<ULONG>(property.size()));
            SecureZeroMemory(property.data(), property.size());
            if (SUCCEEDED(hr))
            {
                const HANDLE wait[] = {parent->hold_->stop, parent->hold_->bound};
                if (WaitForMultipleObjects(2, wait, FALSE, 2000) != WAIT_OBJECT_0 + 1) hr = MF_E_SHUTDOWN;
            }
            if (SUCCEEDED(hr)) hr = parent->RequireBound();
            if (FAILED(hr))
            {
                parent->Stop();
                if (FAILED(parent->Close())) result = std::move(parent); // Cleanup-only retained original, never Ready.
                return hr;
            }
            result = std::move(parent); return S_OK;
        }
        catch (...)
        {
            if (parent) { parent->Stop(); if (FAILED(parent->Close())) result = std::move(parent); }
            return E_OUTOFMEMORY;
        }
    }
    HRESULT SourceBrokerParent::PublishLease() noexcept
    {
        HRESULT hr = CaptureCurrent(); if (FAILED(hr)) return hr;
        if (sequence_ >= static_cast<std::uint64_t>((std::numeric_limits<LONGLONG>::max)())) return Fail(E_INVALIDARG);
        HRESULT sending = hold_->owner.output.sending(hold_->owner.output.context);
        BYTE phase = 0;
        if (sending == S_OK && phase_) phase = 2;
        else if (sending == E_ACCESSDENIED && phase_ != 2) phase = 1;
        else return Fail(FAILED(sending) ? sending : E_ACCESSDENIED);
        const auto now = GetTickCount64();
        if (now < lastTick_ || now > (std::numeric_limits<ULONGLONG>::max)() - 250) return Fail(E_INVALIDARG);
        const auto until = now + 250;
        std::array<BYTE, 19> record{}; record[0] = 1; record[1] = 1; record[2] = phase;
        for (unsigned int i = 0; i < 8; ++i)
        { record[3 + i] = static_cast<BYTE>(sequence_ >> (56 - 8 * i)); record[11 + i] = static_cast<BYTE>(until >> (56 - 8 * i)); }
        leaseAttempted_.store(true); // BEFORE any potentially delivered control write.
        hr = hold_->channel->Write(record.data(), static_cast<DWORD>(record.size()));
        if (SUCCEEDED(hr)) hr = CaptureCurrent();
        const auto after = GetTickCount64();
        if (SUCCEEDED(hr) && (after < now || after >= until)) hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT);
        if (SUCCEEDED(hr) && phase == 2) hr = Exact(hold_->owner.output.sending(hold_->owner.output.context));
        if (FAILED(hr)) return Fail(hr);
        phase_ = phase; lastTick_ = after; ++sequence_; return S_OK;
    }
    HRESULT SourceBrokerParent::PollReceipt() noexcept
    {
        DWORD available = 0;
        if (!PeekNamedPipe(hold_->channel->Pipe(), nullptr, 0, nullptr, &available, nullptr)) return HRESULT_FROM_WIN32(GetLastError());
        if (available < 32) return S_FALSE;
        std::array<BYTE, 32> receipt{}; HRESULT hr = hold_->channel->Read(receipt.data(), static_cast<DWORD>(receipt.size()));
        if (FAILED(hr)) return hr;
        GUID scope{}; HRESULT status{}; DWORD reserved = 0;
        std::memcpy(&scope, receipt.data() + 8, 16); std::memcpy(&status, receipt.data() + 24, 4); std::memcpy(&reserved, receipt.data() + 28, 4);
        if (scope != hold_->property.Scope()) return E_ACCESSDENIED;
        if (!std::memcmp(receipt.data(), "MGFSACT1", 8))
        {
            // Already queued telemetry must drain ahead of the terminal cleanup
            // receipt. It can never revive CaptureCurrent/RequireActive after Stop.
            hr = activity_.Observe(static_cast<DWORD>(status), reserved, bound_.load(), stopped_.load());
            return hr == MF_E_SHUTDOWN ? Fail(hr) : hr;
        }
        if (status != S_OK || reserved) return E_ACCESSDENIED;
        if (!std::memcmp(receipt.data(), "MGFSBND1", 8) && !bound_.load())
        { bound_.store(true); SetEvent(hold_->bound); return S_OK; }
        if (!std::memcmp(receipt.data(), "MGFSEND1", 8))
        {
            std::memcpy(receipt.data(), "MGFSDON1", 8);
            hr = hold_->channel->Write(receipt.data(), static_cast<DWORD>(receipt.size()));
            if (SUCCEEDED(hr)) sourceClosed_.store(true);
            if (!stopped_.load()) Fail(MF_E_SHUTDOWN); // Unsolicited Source close retires joined audio too.
            else Stop();
            return hr;
        }
        return E_ACCESSDENIED;
    }
    void SourceBrokerParent::Run() noexcept
    {
        HRESULT hr = hold_->channel->Accept();
        if (SUCCEEDED(hr)) hr = FrameServerPeer::Accept(hold_->channel->Pipe(),
            {TransportCurrent, PeerRetired, this, hold_->owner.output.lifetime}, hold_->peer);
        std::array<BYTE, 32> nonce{}, expected{}, responseMac{}; std::array<BYTE, 64> response{};
        Clear a{nonce.data(), nonce.size()}, b{expected.data(), expected.size()}, c{responseMac.data(), responseMac.size()}, d{response.data(), response.size()};
        if (SUCCEEDED(hr)) hr = CaptureCurrent();
        if (SUCCEEDED(hr)) hr = BrokerProperty::Random(nonce.data());
        if (SUCCEEDED(hr)) hr = hold_->channel->Write(nonce.data(), 32);
        if (SUCCEEDED(hr)) hr = hold_->channel->Read(response.data(), 64);
        if (SUCCEEDED(hr)) hr = hold_->property.Mac(true, nonce.data(), response.data(), expected.data());
        if (SUCCEEDED(hr) && !BrokerProperty::EqualMac(expected.data(), response.data() + 32)) hr = E_ACCESSDENIED;
        if (SUCCEEDED(hr)) hr = CaptureCurrent();
        if (SUCCEEDED(hr)) hr = hold_->property.Mac(false, nonce.data(), response.data(), responseMac.data());
        if (SUCCEEDED(hr)) hr = hold_->channel->Write(responseMac.data(), 32);
        hold_->property.ClearKey();
        if (FAILED(hr)) { Fail(hr); return; }
        while (!stopped_.load())
        {
            hr = PollReceipt();
            if (FAILED(hr)) { Fail(hr); break; }
            if (stopped_.load()) break;
            { std::lock_guard<std::mutex> lock(transmit_); hr = PublishLease(); }
            if (FAILED(hr)) break;
            if (WaitForSingleObject(hold_->stop, 50) != WAIT_TIMEOUT) break;
        }
        Stop();
        // Retirement receipts do not renew authority. They are read only from
        // the original authenticated pipe; no reconnect, process kill or retry.
        const auto until = GetTickCount64() + 2000;
        while (leaseAttempted_.load() && !sourceClosed_.load() && GetTickCount64() < until)
        {
            hr = PollReceipt(); if (FAILED(hr)) break;
            if (!sourceClosed_.load() && WaitForSingleObject(hold_->channel->Peer(), 10) != WAIT_TIMEOUT) break;
        }
    }
    HRESULT SourceBrokerParent::RequireBound() noexcept
    {
        if (!bound_.load()) return MF_E_NOT_INITIALIZED; // Acquire publication before touching peer state.
        return CaptureCurrent();
    }
    HRESULT SourceBrokerParent::RequireActive() noexcept
    {
        HRESULT hr = RequireBound(); if (FAILED(hr)) return hr;
        return activity_.Active() ? S_OK : MF_E_NOT_INITIALIZED;
    }
    HRESULT SourceBrokerParent::WriteVideo(const BYTE* record, DWORD bytes) noexcept
    {
        if (!record || bytes != 18 + 640 * 480 * 3 / 2 || record[0] != 1 || record[1] != 1) return Fail(E_INVALIDARG);
        std::lock_guard<std::mutex> lock(transmit_);
        HRESULT hr = RequireActive();
        if (SUCCEEDED(hr)) hr = Exact(hold_->owner.output.sending(hold_->owner.output.context));
        if (SUCCEEDED(hr)) hr = PublishLease();
        if (SUCCEEDED(hr) && !anchorSent_)
        {
            std::array<BYTE, 34> anchor{}; Clear wipe{anchor.data(), anchor.size()}; anchor[0] = 2;
            hr = Exact(hold_->owner.exportAnchor(hold_->owner.output.context, anchor.data() + 1, 33));
            if (SUCCEEDED(hr)) hr = hold_->channel->Write(anchor.data(), static_cast<DWORD>(anchor.size()));
            if (SUCCEEDED(hr)) anchorSent_ = true;
        }
        if (SUCCEEDED(hr))
        {
            BYTE type = 3; hr = hold_->channel->Write(&type, 1);
            if (SUCCEEDED(hr)) hr = hold_->channel->Write(record, bytes);
            if (SUCCEEDED(hr)) hr = CaptureCurrent();
            if (SUCCEEDED(hr)) hr = Exact(hold_->owner.output.sending(hold_->owner.output.context));
        }
        return FAILED(hr) ? Fail(hr) : hr;
    }
    HRESULT SourceBrokerParent::Close() noexcept
    {
        std::lock_guard<std::mutex> close(close_);
        if (closeAttempted_) return closeResult_;
        closeAttempted_ = true; Stop();
        if (worker_.joinable()) worker_.join();
        std::lock_guard<std::mutex> transmit(transmit_);
        hold_->property.ClearKey();
        closeResult_ = !leaseAttempted_.load() || sourceClosed_.load() ? S_OK : HRESULT_FROM_WIN32(ERROR_IO_INCOMPLETE);
        if (FAILED(closeResult_)) uncertainBroker.store(true);
        return closeResult_;
    }
}
