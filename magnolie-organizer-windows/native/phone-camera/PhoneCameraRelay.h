#pragma once
#include "PhoneCameraPipe.h"
#include "PhoneCameraSource.h"
#include <wrl/client.h>
#include <array>

namespace Magnolie::PhoneCamera
{
    // One already admitted AUDIO channel -> original guarded sample owner.
    // This does not open a WASAPI endpoint or authorize physical capture/SEND.
    // The downstream output owner must recheck original authority at delivery.
    class AudioRelay final
    {
    public:
        static HRESULT Create(std::unique_ptr<PipeReader>& reader,
            const std::shared_ptr<Samples>& originalSamples, std::unique_ptr<AudioRelay>& result) noexcept;
        ~AudioRelay();
        HRESULT ReceiveOne(IMFSample** result) noexcept;
        void Stop() noexcept;
        bool IsRetired() const noexcept;
    private:
        explicit AudioRelay(const std::shared_ptr<Samples>& samples) noexcept : samples_(samples) {}
        HRESULT Fail(HRESULT reason) noexcept;
        std::unique_ptr<PipeReader> reader_;
        const std::shared_ptr<Samples> samples_;
        std::array<BYTE, Samples::AudioRecordBytes> packet_{};
        std::atomic_bool retired_{false};
        std::mutex receive_;
    };

    // Receiver half of the private local video bridge. It neither registers a
    // device nor grants phone/SEND authority. The original controller supplies
    // an admitted PipeReader and the exact original source/feed identity.
    class VideoRelay final
    {
    public:
        static HRESULT Create(std::unique_ptr<PipeReader>& reader, IMFMediaSourceEx* source,
            IFrameFeed* feed, std::unique_ptr<VideoRelay>& result) noexcept;
        ~VideoRelay();
        HRESULT ReceiveOne() noexcept;
        void Stop() noexcept; // Nonblocking; suitable for the owner's retirement signal.
        bool IsRetired() const noexcept;
    private:
        VideoRelay(IMFMediaSourceEx* source, IFrameFeed* feed) noexcept : source_(source), feed_(feed) {}
        HRESULT Fail(HRESULT reason) noexcept;
        std::unique_ptr<PipeReader> reader_;
        Microsoft::WRL::ComPtr<IMFMediaSourceEx> source_;
        Microsoft::WRL::ComPtr<IFrameFeed> feed_;
        // The existing canonical plaintext media packet body: version/track,
        // u64be track sequence, u64be PTS microseconds, exact I420 payload.
        std::array<BYTE, 18 + Samples::VideoBytes> packet_{};
        std::atomic_bool retired_{false};
        std::mutex receive_;
    };
}
