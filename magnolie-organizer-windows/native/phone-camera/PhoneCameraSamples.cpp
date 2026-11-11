#include "PhoneCameraSamples.h"
#include <mfapi.h>
#include <mferror.h>
#include <wrl/client.h>
#include <cstring>
#include <limits>

namespace Magnolie::PhoneCamera
{
    using Microsoft::WRL::ComPtr;

    Samples::Samples(Current current, void* originalContext, bool muted) noexcept
        : current_(current), context_(originalContext), muted_(muted)
    {
        if (!current_) Retire();
    }

    void Samples::Retire() noexcept { retired_.store(true); }
    bool Samples::IsRetired() const noexcept { return retired_.load(); }

    HRESULT Samples::RequireCurrent() noexcept
    {
        if (IsRetired()) return MF_E_SHUTDOWN;
        const HRESULT status = current_(context_);
        if (FAILED(status)) { Retire(); return status; }
        return IsRetired() ? MF_E_SHUTDOWN : S_OK;
    }

    HRESULT Samples::VideoType(IMFMediaType** result) noexcept
    {
        if (!result) return E_POINTER;
        *result = nullptr;
        ComPtr<IMFMediaType> type;
        HRESULT hr = MFCreateMediaType(&type);
        if (SUCCEEDED(hr)) hr = type->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
        if (SUCCEEDED(hr)) hr = type->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_NV12);
        if (SUCCEEDED(hr)) hr = MFSetAttributeSize(type.Get(), MF_MT_FRAME_SIZE, 640, 480);
        if (SUCCEEDED(hr)) hr = MFSetAttributeRatio(type.Get(), MF_MT_FRAME_RATE, 15, 1);
        if (SUCCEEDED(hr)) hr = MFSetAttributeRatio(type.Get(), MF_MT_PIXEL_ASPECT_RATIO, 1, 1);
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive);
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_DEFAULT_STRIDE, 640);
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_SAMPLE_SIZE, static_cast<UINT32>(VideoBytes));
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_FIXED_SIZE_SAMPLES, TRUE);
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_ALL_SAMPLES_INDEPENDENT, TRUE);
        if (SUCCEEDED(hr)) *result = type.Detach();
        return hr;
    }

    HRESULT Samples::AudioType(IMFMediaType** result) noexcept
    {
        if (!result) return E_POINTER;
        *result = nullptr;
        ComPtr<IMFMediaType> type;
        HRESULT hr = MFCreateMediaType(&type);
        if (SUCCEEDED(hr)) hr = type->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio);
        if (SUCCEEDED(hr)) hr = type->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_PCM);
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_AUDIO_NUM_CHANNELS, 1);
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, 48000);
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, 16);
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_AUDIO_BLOCK_ALIGNMENT, 2);
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_AUDIO_AVG_BYTES_PER_SECOND, 96000);
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_FIXED_SIZE_SAMPLES, TRUE);
        if (SUCCEEDED(hr)) hr = type->SetUINT32(MF_MT_ALL_SAMPLES_INDEPENDENT, TRUE);
        if (SUCCEEDED(hr)) *result = type.Detach();
        return hr;
    }

    HRESULT Samples::Video(const std::uint8_t* data, std::size_t size,
        std::int64_t sequence, std::int64_t ptsUs, IMFSample** result) noexcept
    { return Make(true, data, size, sequence, ptsUs, result); }

    HRESULT Samples::Audio(const std::uint8_t* data, std::size_t size,
        std::int64_t sequence, std::int64_t ptsUs, IMFSample** result) noexcept
    { return Make(false, data, size, sequence, ptsUs, result); }

    HRESULT Samples::AudioRecord(const std::uint8_t* record, std::size_t size,
        IMFSample** result) noexcept
    {
        if (!result) { Retire(); return E_POINTER; }
        *result = nullptr;
        if (!record || size != AudioRecordBytes || record[0] != 1 || record[1] != 2)
        { Retire(); return E_INVALIDARG; }
        std::uint64_t sequence = 0, pts = 0;
        for (unsigned int i = 0; i < 8; ++i)
        {
            sequence = (sequence << 8) | record[2 + i];
            pts = (pts << 8) | record[10 + i];
        }
        if (sequence > static_cast<std::uint64_t>((std::numeric_limits<std::int64_t>::max)()) ||
            pts > 9007199254740991ULL)
        { Retire(); return E_INVALIDARG; }
        // Keep the existing original-owner checks, mute, per-track continuity,
        // shared AV epoch/skew and fail-closed retirement in ONE sample path.
        return Audio(record + 18, AudioBytes, static_cast<std::int64_t>(sequence),
            static_cast<std::int64_t>(pts), result);
    }

    HRESULT Samples::Make(bool video, const std::uint8_t* data, std::size_t size,
        std::int64_t sequence, std::int64_t ptsUs, IMFSample** result) noexcept
    {
        // No partial/previous sample may escape any failure, including bad output.
        if (!result) { Retire(); return E_POINTER; }
        *result = nullptr;
        try
        {
            std::lock_guard<std::mutex> lock(gate_);
            HRESULT hr = RequireCurrent();
            if (FAILED(hr)) return hr;
            auto fail = [this](HRESULT error) noexcept { Retire(); return error; };
            Position& position = video ? video_ : audio_;
            const Position& other = video ? audio_ : video_;
            if (!data || size != (video ? VideoBytes : AudioBytes) || (!video && muted_) ||
                sequence < 0 || ptsUs < 0 || ptsUs > 9007199254740991LL ||
                (position.seen && (position.sequence == (std::numeric_limits<std::int64_t>::max)() ||
                    sequence != position.sequence + 1 || ptsUs <= position.pts)) ||
                (!position.seen && sequence != 0) ||
                (other.seen && (ptsUs > other.pts ? ptsUs - other.pts : other.pts - ptsUs) > 250000))
                return fail(E_INVALIDARG);

            ComPtr<IMFMediaBuffer> buffer;
            ComPtr<IMFSample> sample;
            hr = MFCreateMemoryBuffer(static_cast<DWORD>(size), &buffer);
            if (FAILED(hr)) return fail(hr);
            BYTE* bytes = nullptr;
            DWORD capacity = 0;
            hr = buffer->Lock(&bytes, &capacity, nullptr);
            if (FAILED(hr)) return fail(hr);
            hr = RequireCurrent();
            if (SUCCEEDED(hr) && capacity < size) hr = E_UNEXPECTED;
            if (SUCCEEDED(hr))
            {
                if (video)
                {
                    constexpr std::size_t y = 640 * 480, chroma = y / 4;
                    std::memcpy(bytes, data, y);
                    for (std::size_t i = 0; i < chroma; ++i)
                    {
                        bytes[y + 2 * i] = data[y + i];
                        bytes[y + 2 * i + 1] = data[y + chroma + i];
                    }
                }
                else std::memcpy(bytes, data, size);
                hr = RequireCurrent();
            }
            // A revoked sample is erased while the private buffer is still locked.
            if (FAILED(hr)) SecureZeroMemory(bytes, capacity);
            const HRESULT unlocked = buffer->Unlock();
            if (FAILED(hr)) return fail(hr);
            if (FAILED(unlocked)) return fail(unlocked);
            hr = buffer->SetCurrentLength(static_cast<DWORD>(size));
            if (SUCCEEDED(hr)) hr = MFCreateSample(&sample);
            if (SUCCEEDED(hr)) hr = sample->AddBuffer(buffer.Get());
            // Preserve the phone's common epoch. Convert microseconds to 100ns
            // without float, receipt-time rebasing or separate AV origins.
            if (SUCCEEDED(hr)) hr = sample->SetSampleTime(ptsUs * 10);
            if (SUCCEEDED(hr)) hr = sample->SetSampleDuration(video ? 666667 : 200000);
            if (SUCCEEDED(hr)) hr = RequireCurrent();
            if (FAILED(hr)) return fail(hr);
            position = {true, sequence, ptsUs};
            *result = sample.Detach();
            return S_OK;
        }
        catch (...) { Retire(); return E_FAIL; }
    }
}
