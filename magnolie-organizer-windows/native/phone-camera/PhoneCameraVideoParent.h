#pragma once
#include <windows.h>

// Trusted original managed composition ONLY; callbacks stay rooted until
// confirmed Close. Registration lifetime is separate from capture/SEND.
struct MagnoliePhoneVideoOwnerV1
{
    DWORD size, version, flags, reserved; // flags: 1 = explicitly muted
    HRESULT (__cdecl* current)(void*) noexcept;
    HRESULT (__cdecl* sending)(void*) noexcept;
    void (__cdecl* failed)(void*, HRESULT) noexcept;
    HRESULT (__cdecl* registration)(void*) noexcept;
    HRESULT (__cdecl* observeVideo)(void*, LONGLONG, LONGLONG*) noexcept;
    HRESULT (__cdecl* exportAnchor)(void*, BYTE*, DWORD) noexcept;
    void* context;
};
#ifdef MAGNOLIE_PHONE_AUDIO_PARENT_EXPORTS
#define MAGNOLIE_PHONE_VIDEO_API extern "C" __declspec(dllexport)
#else
#define MAGNOLIE_PHONE_VIDEO_API extern "C"
#endif
MAGNOLIE_PHONE_VIDEO_API DWORD __cdecl MagnoliePhoneVideoVersion() noexcept;
MAGNOLIE_PHONE_VIDEO_API HRESULT __cdecl MagnoliePhoneVideoCreate(const GUID* originalScope,
    const MagnoliePhoneVideoOwnerV1* originalOwner, ULONGLONG* ownHandle) noexcept;
MAGNOLIE_PHONE_VIDEO_API HRESULT __cdecl MagnoliePhoneVideoPrepare(ULONGLONG ownHandle) noexcept;
MAGNOLIE_PHONE_VIDEO_API HRESULT __cdecl MagnoliePhoneVideoRequireReady(ULONGLONG ownHandle) noexcept;
MAGNOLIE_PHONE_VIDEO_API HRESULT __cdecl MagnoliePhoneVideoWrite(ULONGLONG ownHandle, const BYTE* originalRecord, DWORD bytes) noexcept;
MAGNOLIE_PHONE_VIDEO_API HRESULT __cdecl MagnoliePhoneVideoStop(ULONGLONG ownHandle) noexcept;
// Original Source cleanup ACK BEFORE manager shutdown; failure retains the exact
// native root, MF/MTA and managed callbacks/module, without a retry/replacement.
MAGNOLIE_PHONE_VIDEO_API HRESULT __cdecl MagnoliePhoneVideoClose(ULONGLONG ownHandle) noexcept;
