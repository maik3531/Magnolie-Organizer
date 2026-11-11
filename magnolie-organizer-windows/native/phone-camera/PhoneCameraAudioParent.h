#pragma once
#include <windows.h>

// Versioned trusted-native boundary, never renderer/JSON permission input.
// Callbacks are nonblocking/nonthrowing and valid until confirmed Close. They
// must originate ONLY from the exact original managed OutputAuthority (#550).
struct MagnoliePhoneAudioOwnerV1
{
    DWORD size, version;
    HRESULT (__cdecl* current)(void*) noexcept;
    HRESULT (__cdecl* sending)(void*) noexcept;
    void (__cdecl* failed)(void*, HRESULT) noexcept;
    void* context;
};
#ifdef MAGNOLIE_PHONE_AUDIO_PARENT_EXPORTS
#define MAGNOLIE_PHONE_AUDIO_API extern "C" __declspec(dllexport)
#else
#define MAGNOLIE_PHONE_AUDIO_API extern "C"
#endif
MAGNOLIE_PHONE_AUDIO_API DWORD __cdecl MagnoliePhoneAudioVersion() noexcept;
MAGNOLIE_PHONE_AUDIO_API HRESULT __cdecl MagnoliePhoneAudioCreate(const GUID* originalScope, const BYTE* immutableWorkerSha256,
    DWORD digestBytes, const MagnoliePhoneAudioOwnerV1* originalOwner, ULONGLONG* ownHandle) noexcept;
MAGNOLIE_PHONE_AUDIO_API HRESULT __cdecl MagnoliePhoneAudioPrepare(ULONGLONG ownHandle) noexcept;
MAGNOLIE_PHONE_AUDIO_API HRESULT __cdecl MagnoliePhoneAudioRequireReady(ULONGLONG ownHandle) noexcept;
// Call for EVERY actually admitted video frame before native video delivery.
MAGNOLIE_PHONE_AUDIO_API HRESULT __cdecl MagnoliePhoneAudioObserveVideo(ULONGLONG ownHandle, LONGLONG originalPtsUs, LONGLONG* nativePtsUs) noexcept;
MAGNOLIE_PHONE_AUDIO_API HRESULT __cdecl MagnoliePhoneAudioWrite(ULONGLONG ownHandle, const BYTE* exactRecord, DWORD bytes) noexcept;
// Same original anchor for the trusted FrameServer broker, not a new epoch.
MAGNOLIE_PHONE_AUDIO_API HRESULT __cdecl MagnoliePhoneAudioExportAnchor(ULONGLONG ownHandle, BYTE* exactRecord, DWORD bytes) noexcept;
MAGNOLIE_PHONE_AUDIO_API HRESULT __cdecl MagnoliePhoneAudioStop(ULONGLONG ownHandle) noexcept;
// Removes the handle ONLY after own worker exit and publisher drain confirmed.
// Failure is terminal/unconfirmed; retain callback/module lifetime, never retry launch.
MAGNOLIE_PHONE_AUDIO_API HRESULT __cdecl MagnoliePhoneAudioClose(ULONGLONG ownHandle) noexcept;
#ifdef MAGNOLIE_NATIVE_AUDIO_PARENT_TESTS
#include "PhoneCameraRuntimeProcess.h"
namespace Magnolie::PhoneCamera
{
    HRESULT AudioParentCreateTestImage(const GUID&, const std::shared_ptr<RuntimeImage>&,
        const MagnoliePhoneAudioOwnerV1&, ULONGLONG*) noexcept; // Absent in production DLL.
}
#endif
