#pragma once
#include "PhoneCameraSource.h"

namespace Magnolie::PhoneCamera
{
    struct ActivateOwner
    {
        Samples::Current current;
        // Resolve only the original native context. Attributes are metadata, not
        // permission. No capture, consent UI, driver install or general COM route.
        HRESULT (*construct)(void* context, IMFAttributes* snapshot, IMFMediaSourceEx** result) noexcept;
        void* context;
        IUnknown* lifetime = nullptr;
    };

    // Single-use native IMFActivate boundary for the pending COM class factory.
    // Callback context must remain valid through destruction; a factory-owned COM
    // context supplies lifetime. A detached source must hold its OWN lifetime via
    // SourceOwner, independently of this activation object's lifetime anchor.
    HRESULT CreateActivate(const ActivateOwner& owner, IMFActivate** result) noexcept;
}
