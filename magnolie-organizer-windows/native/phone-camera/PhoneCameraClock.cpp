#include "PhoneCameraClock.h"
#include <mfapi.h>
#include <mfidl.h>
#include <mferror.h>

namespace Magnolie::PhoneCamera
{
    constexpr LONGLONG MaxPtsUs = 9007199254740991LL;
    PresentationClock::PresentationClock(ClockOwner owner) noexcept : owner_(owner), lifetime_(owner.lifetime) {}
    PresentationClock::~PresentationClock() { Stop(); }
    HRESULT PresentationClock::Retire(HRESULT reason) noexcept
    {
        if (retired_) return MF_E_SHUTDOWN;
        retired_ = true;
        if (owner_.retired) owner_.retired(owner_.context, reason);
        return reason;
    }
    HRESULT PresentationClock::Check() noexcept
    {
        if (retired_) return MF_E_SHUTDOWN;
        if (!owner_.current || !owner_.sending || !owner_.retired) return Retire(E_INVALIDARG);
        HRESULT hr = owner_.current(owner_.context);
        if (SUCCEEDED(hr)) hr = owner_.sending(owner_.context);
        return FAILED(hr) ? Retire(hr) : S_OK;
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
    void PresentationClock::Stop() noexcept
    {
        std::lock_guard<std::mutex> lock(gate_);
        Retire(S_OK);
    }
}
