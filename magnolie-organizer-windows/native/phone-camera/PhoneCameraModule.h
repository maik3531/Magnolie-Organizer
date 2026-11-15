#pragma once
#include <windows.h>

namespace Magnolie::PhoneCamera
{
    // Fixed custom-source class, not a registration, scope or capture capability.
    inline constexpr GUID SourceClassId = {0xdab1e726, 0x131a, 0x4a3a,
        {0xab, 0xea, 0x6a, 0x8c, 0xa1, 0xb4, 0xf5, 0x71}};
}
