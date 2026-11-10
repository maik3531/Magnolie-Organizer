#include "PhoneCameraRelay.h"
#include <mferror.h>
#include <limits>

namespace Magnolie::PhoneCamera
{
    using Microsoft::WRL::ComPtr;
    static std::uint64_t BigEndian64(const BYTE* bytes) noexcept
    {
        std::uint64_t value = 0;
        for (unsigned int i = 0; i < 8; ++i) value = (value << 8) | bytes[i];
        return value;
    }

    HRESULT VideoRelay::Create(std::unique_ptr<PipeReader>& reader, IMFMediaSourceEx* source,
        IFrameFeed* feed, std::unique_ptr<VideoRelay>& result) noexcept
    {
        if (result || !reader || reader->IsRetired() || !source || !feed) return E_INVALIDARG;
        ComPtr<IUnknown> sourceIdentity, feedIdentity;
        HRESULT hr = source->QueryInterface(IID_PPV_ARGS(&sourceIdentity));
        if (SUCCEEDED(hr)) hr = feed->QueryInterface(IID_PPV_ARGS(&feedIdentity));
        if (FAILED(hr)) return hr;
        if (sourceIdentity.Get() != feedIdentity.Get()) return E_ACCESSDENIED;
        DWORD flags = 0; hr = source->GetCharacteristics(&flags);
        if (FAILED(hr)) return hr;
        if (!(flags & MFMEDIASOURCE_IS_LIVE)) return E_INVALIDARG;
        try
        {
            std::unique_ptr<VideoRelay> relay(new VideoRelay(source, feed));
            relay->reader_ = std::move(reader);
            result = std::move(relay);
            return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }

    bool VideoRelay::IsRetired() const noexcept
    { return retired_.load() || (reader_ && reader_->IsRetired()); }

    void VideoRelay::Stop() noexcept
    { retired_.store(true); if (reader_) reader_->Stop(); }

    HRESULT VideoRelay::Fail(HRESULT reason) noexcept
    {
        Stop(); source_->Shutdown();
        return reason;
    }

    HRESULT VideoRelay::ReceiveOne() noexcept
    {
        try
        {
            std::unique_lock<std::mutex> lock(receive_, std::try_to_lock);
            if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
            struct ClearPacket
            {
                BYTE* data; std::size_t size;
                ~ClearPacket() { SecureZeroMemory(data, size); }
            } clear{packet_.data(), packet_.size()};
            if (IsRetired()) return Fail(MF_E_SHUTDOWN);
            // One fixed-size read gives the WHOLE record one deadline; no
            // untrusted length, header/body deadline reset or dynamic allocation.
            HRESULT hr = reader_->ReadExact(packet_.data(), packet_.size());
            if (SUCCEEDED(hr))
            {
                const auto sequence = BigEndian64(packet_.data() + 2);
                const auto pts = BigEndian64(packet_.data() + 10);
                if (packet_[0] != 1 || packet_[1] != 1 ||
                    sequence > static_cast<std::uint64_t>((std::numeric_limits<LONGLONG>::max)()) || pts > 9007199254740991ULL)
                    hr = E_INVALIDARG;
                else
                    hr = feed_->PublishVideo(packet_.data() + 18, static_cast<DWORD>(Samples::VideoBytes),
                        static_cast<LONGLONG>(sequence), static_cast<LONGLONG>(pts));
            }
            return FAILED(hr) ? Fail(hr) : S_OK;
        }
        catch (...) { return Fail(E_FAIL); }
    }

    VideoRelay::~VideoRelay()
    {
        Stop();
        // As for PipeReader, the owning controller first signals and joins its
        // receive task. Its callback context remains valid through this shutdown.
        std::lock_guard<std::mutex> lock(receive_);
        source_->Shutdown(); SecureZeroMemory(packet_.data(), packet_.size());
    }
}
