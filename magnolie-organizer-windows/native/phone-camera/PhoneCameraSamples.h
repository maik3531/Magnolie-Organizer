#pragma once

#include <mfidl.h>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <mutex>

namespace Magnolie::PhoneCamera
{
    // Converts already admitted binary frames to real Media Foundation samples.
    // This is NOT a device, permission, media source, microphone or SEND owner.
    // The original native owner must remain live again at downstream delivery.
    class Samples final
    {
    public:
        using Current = HRESULT (*)(void*) noexcept;
        static constexpr std::size_t VideoBytes = 640 * 480 * 3 / 2;
        static constexpr std::size_t AudioBytes = 960 * 2;
        static constexpr std::size_t AudioRecordBytes = 18 + AudioBytes;

        // current is mandatory, nonblocking and cannot reenter this object.
        // Its context must outlive this object and every in-progress call.
        Samples(Current current, void* originalContext, bool muted) noexcept;
        HRESULT Video(const std::uint8_t* i420, std::size_t size,
            std::int64_t sequence, std::int64_t ptsUs, IMFSample** result) noexcept;
        HRESULT Audio(const std::uint8_t* pcm, std::size_t size,
            std::int64_t sequence, std::int64_t ptsUs, IMFSample** result) noexcept;
        // Exact private v1/track2 record, not a pipe/device/SEND admission.
        // Caller owns immutable input through return; failure retires both lanes.
        HRESULT AudioRecord(const std::uint8_t* record, std::size_t size,
            IMFSample** result) noexcept;
        void Retire() noexcept;
        bool IsRetired() const noexcept;

        static HRESULT VideoType(IMFMediaType** result) noexcept;
        static HRESULT AudioType(IMFMediaType** result) noexcept;

    private:
        struct Position { bool seen = false; std::int64_t sequence = 0; std::int64_t pts = 0; };
        HRESULT RequireCurrent() noexcept;
        HRESULT Make(bool video, const std::uint8_t* data, std::size_t size,
            std::int64_t sequence, std::int64_t ptsUs, IMFSample** result) noexcept;
        const Current current_;
        void* const context_;
        const bool muted_;
        std::atomic_bool retired_{false};
        std::mutex gate_;
        Position video_, audio_;
    };
}
