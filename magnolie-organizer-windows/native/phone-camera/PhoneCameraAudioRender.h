#pragma once
#include "PhoneCameraClock.h"
#include "PhoneCameraSamples.h"
#include <audioclient.h>
#include <array>
#include <atomic>
#include <memory>

namespace Magnolie::PhoneCamera
{
    class PipeReader;
    // Worker half of the isolated audio output process, NEVER an in-process UI
    // fallback. The ORIGINAL controller must impose a process-wide deadline:
    // Endpoint COM calls (including activation/Initialize/buffer/Stop/Release)
    // are not cancellable contracts; an elapsed local timer cannot interrupt them.
    // No default device, capture, volume, driver or installation operation.
    class AudioRender final
    {
    public:
        static HRESULT Open(ClockOwner originalOwner, PipeReader* originalControl,
            std::unique_ptr<AudioRender>& result) noexcept;
        ~AudioRender();
        // Sample contains original phone PTS; nativePtsUs comes from the ONE
        // original joined PresentationClock, not an independent audio epoch.
        HRESULT Write(IMFSample* originalSample, LONGLONG nativePtsUs) noexcept;
        void Stop() noexcept; // Signals only; does not call a potentially hung COM service.
        bool IsRetired() const noexcept { return retired_.load(); }
    private:
        explicit AudioRender(ClockOwner owner) noexcept : owner_(owner), lifetime_(owner.lifetime) {}
        HRESULT Check(bool requireSend = true) noexcept;
        HRESULT Fail(HRESULT reason) noexcept;
        HRESULT Initialize() noexcept;
        static HRESULT AdmitParent(PipeReader* originalControl) noexcept;
        LONGLONG Now() const noexcept;
        const ClockOwner owner_;
        // Original control reader/context outlives this isolated renderer and its worker.
        PipeReader* control_ = nullptr;
        Microsoft::WRL::ComPtr<IUnknown> lifetime_;
        Microsoft::WRL::ComPtr<IAudioClient> client_;
        Microsoft::WRL::ComPtr<IAudioRenderClient> writer_;
        HANDLE stop_ = nullptr, ready_ = nullptr;
        UINT32 capacity_ = 0;
        bool started_ = false;
        LONGLONG lastNow_ = -1;
        std::atomic_bool retired_{false};
        std::mutex gate_;
#ifdef MAGNOLIE_NATIVE_AUDIO_RENDER_TESTS
        // Only the device-free native test build supplies controlled COM clients.
        // No productive test factory, renderer callback or endpoint bypass exists.
        friend struct AudioRenderTestAccess;
#endif
    };
}
