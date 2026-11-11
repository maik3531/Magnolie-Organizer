#include "PhoneCameraClock.h"
#include <mfapi.h>
#include <mfidl.h>
#include <mferror.h>
#include <array>
#include <cstring>

namespace Magnolie::PhoneCamera
{
    static_assert(std::atomic_bool::is_always_lock_free, "Clock Stop requires a lock-free retirement signal");
    constexpr LONGLONG MaxPtsUs = 9007199254740991LL;
    namespace
    {
        void ScopeBytes(const GUID& scope, BYTE* bytes) noexcept
        {
            for (unsigned int i = 0; i < 4; ++i) bytes[i] = static_cast<BYTE>(scope.Data1 >> (24 - 8 * i));
            bytes[4] = static_cast<BYTE>(scope.Data2 >> 8); bytes[5] = static_cast<BYTE>(scope.Data2);
            bytes[6] = static_cast<BYTE>(scope.Data3 >> 8); bytes[7] = static_cast<BYTE>(scope.Data3);
            std::memcpy(bytes + 8, scope.Data4, 8);
        }
        void IntegerBytes(LONGLONG value, BYTE* bytes) noexcept
        {
            const auto integer = static_cast<ULONGLONG>(value);
            for (unsigned int i = 0; i < 8; ++i) bytes[i] = static_cast<BYTE>(integer >> (56 - 8 * i));
        }
        bool ReadInteger(const BYTE* bytes, LONGLONG& value) noexcept
        {
            ULONGLONG integer = 0;
            for (unsigned int i = 0; i < 8; ++i) integer = (integer << 8) | bytes[i];
            if (integer > static_cast<ULONGLONG>(MaxPtsUs)) return false;
            value = static_cast<LONGLONG>(integer); return true;
        }
    }
    PresentationClock::PresentationClock(ClockOwner owner) noexcept : owner_(owner), lifetime_(owner.lifetime) {}
    PresentationClock::~PresentationClock() { Stop(); }
    HRESULT PresentationClock::Retire(HRESULT reason) noexcept
    {
        if (retired_.exchange(true)) return MF_E_SHUTDOWN;
        if (owner_.retired) owner_.retired(owner_.context, reason);
        return reason;
    }
    HRESULT PresentationClock::Check() noexcept
    {
        if (retired_.load()) return MF_E_SHUTDOWN;
        if (!owner_.current || !owner_.sending || !owner_.retired) return Retire(E_INVALIDARG);
        HRESULT hr = owner_.current(owner_.context);
        if (SUCCEEDED(hr)) hr = owner_.sending(owner_.context);
        if (FAILED(hr)) return Retire(hr);
        return retired_.load() ? MF_E_SHUTDOWN : S_OK;
    }
    HRESULT PresentationClock::Map(LONGLONG pts, LONGLONG* result) noexcept
    {
        if (!result) return E_POINTER;
        *result = 0;
        std::lock_guard<std::mutex> lock(gate_);
        HRESULT hr = Check(); if (FAILED(hr)) return hr;
        if (pts < 0 || pts > MaxPtsUs) return Retire(E_INVALIDARG);
        const LONGLONG now = owner_.nowUs ? owner_.nowUs(owner_.context) : MFGetSystemTime() / 10;
        if (now < 0 || now > MaxPtsUs || (anchored_ && now < lastNow_)) return Retire(E_UNEXPECTED);
        // Subtract integers BEFORE adding the native epoch. All operands are
        // bounded to 2^53-1, so even their signed intermediate sum fits int64.
        const LONGLONG mapped = anchored_ ? nativeAnchor_ + (pts - remoteAnchor_) : now;
        if (mapped < 0 || mapped > MaxPtsUs) return Retire(E_INVALIDARG);
        if (mapped - now > 250000 || now - mapped > 250000) return Retire(MF_E_NET_TIMEOUT);
        hr = Check(); if (FAILED(hr)) return hr;
        if (!anchored_) { remoteAnchor_ = pts; nativeAnchor_ = now; anchored_ = true; }
        lastNow_ = now; *result = mapped;
        return S_OK;
    }
    HRESULT PresentationClock::ExportAnchor(const GUID& scope, BYTE* record, std::size_t size) noexcept
    {
        std::lock_guard<std::mutex> lock(gate_);
        HRESULT hr = Check(); if (FAILED(hr)) return hr;
        if (!record || size != AnchorBytes || scope == GUID_NULL || !anchored_ || imported_ ||
            (anchorScope_ != GUID_NULL && anchorScope_ != scope)) return Retire(E_INVALIDARG);
        std::array<BYTE, AnchorBytes> snapshot{};
        snapshot[0] = 1; ScopeBytes(scope, snapshot.data() + 1);
        IntegerBytes(remoteAnchor_, snapshot.data() + 17); IntegerBytes(nativeAnchor_, snapshot.data() + 25);
        hr = Check(); if (FAILED(hr)) return hr;
        anchorScope_ = scope;
        std::memcpy(record, snapshot.data(), snapshot.size());
        return S_OK;
    }
    HRESULT PresentationClock::ImportAnchor(const GUID& scope, const BYTE* record, std::size_t size) noexcept
    {
        std::lock_guard<std::mutex> lock(gate_);
        HRESULT hr = Check(); if (FAILED(hr)) return hr;
        if (!record || size != AnchorBytes || scope == GUID_NULL || anchored_) return Retire(E_INVALIDARG);
        std::array<BYTE, AnchorBytes> snapshot{};
        std::memcpy(snapshot.data(), record, snapshot.size());
        std::array<BYTE, 16> expected{}; ScopeBytes(scope, expected.data());
        LONGLONG remote = -1, native = -1;
        if (snapshot[0] != 1 || std::memcmp(expected.data(), snapshot.data() + 1, expected.size()) ||
            !ReadInteger(snapshot.data() + 17, remote) || !ReadInteger(snapshot.data() + 25, native)) return Retire(E_INVALIDARG);
        const LONGLONG now = owner_.nowUs ? owner_.nowUs(owner_.context) : MFGetSystemTime() / 10;
        if (now < 0 || now > MaxPtsUs) return Retire(E_UNEXPECTED);
        hr = Check(); if (FAILED(hr)) return hr;
        // The producer's coordinates are immutable. Never substitute now or the
        // first consumer PTS; both processes must preserve this exact equation.
        remoteAnchor_ = remote; nativeAnchor_ = native; lastNow_ = now;
        anchored_ = true; imported_ = true; anchorScope_ = scope;
        return S_OK;
    }
    void PresentationClock::Stop() noexcept
    {
        Stop(S_OK);
    }
    void PresentationClock::Stop(HRESULT originalReason) noexcept { Retire(originalReason); }
    bool PresentationClock::MatchesOwner(const ClockOwner& original) const noexcept
    {
        return owner_.current == original.current && owner_.sending == original.sending &&
            owner_.retired == original.retired && owner_.context == original.context;
    }
    HRESULT PresentationClock::RequireImportedAnchor(const GUID& scope) noexcept
    {
        std::lock_guard<std::mutex> lock(gate_);
        HRESULT hr = Check(); if (FAILED(hr)) return hr;
        return scope != GUID_NULL && imported_ && anchored_ && anchorScope_ == scope ? S_OK : Retire(E_ACCESSDENIED);
    }
}
