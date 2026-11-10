#pragma once
#include "PhoneCameraActivate.h"

namespace Magnolie::PhoneCamera
{
    struct FactoryOwner
    {
        // Creates a fresh activation context, never starts capture or setup.
        HRESULT (*activate)(void* context, IMFActivate** result) noexcept;
        // The hosting DLL supplies its native module-lock accounting.
        HRESULT (*lockServer)(void* context, BOOL locked) noexcept;
        void* context;
        IUnknown* lifetime = nullptr;
    };
    HRESULT CreateFactory(const FactoryOwner& owner, IClassFactory** result) noexcept;
}
