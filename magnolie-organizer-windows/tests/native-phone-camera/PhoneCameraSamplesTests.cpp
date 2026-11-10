#include "../../native/phone-camera/PhoneCameraSamples.h"
#include <mfapi.h>
#include <mferror.h>
#include <wrl/client.h>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>

using Magnolie::PhoneCamera::Samples;
using Microsoft::WRL::ComPtr;

namespace
{
    void Check(bool value) { if (!value) throw std::runtime_error("native sample assertion"); }
    void Ok(HRESULT hr) { Check(SUCCEEDED(hr)); }
    struct Owner
    {
        int calls = 0, denyAt = 0;
        bool current = true;
        Samples* retire = nullptr;
        static HRESULT Current(void* context) noexcept
        {
            auto& owner = *static_cast<Owner*>(context);
            ++owner.calls;
            if (owner.retire) owner.retire->Retire();
            return owner.current && owner.calls != owner.denyAt ? S_OK : E_ACCESSDENIED;
        }
    };

    std::vector<std::uint8_t> Picture()
    {
        std::vector<std::uint8_t> data(Samples::VideoBytes);
        for (std::size_t i = 0; i < data.size(); ++i) data[i] = static_cast<std::uint8_t>(i * 31 + i / 640);
        return data;
    }
    std::vector<std::uint8_t> Bytes(IMFSample* sample)
    {
        DWORD count = 0; Ok(sample->GetBufferCount(&count)); Check(count == 1);
        ComPtr<IMFMediaBuffer> buffer; Ok(sample->GetBufferByIndex(0, &buffer));
        BYTE* data = nullptr; DWORD length = 0; Ok(buffer->Lock(&data, nullptr, &length));
        std::vector<std::uint8_t> result(data, data + length); Ok(buffer->Unlock());
        return result;
    }

    void MediaTypes()
    {
        ComPtr<IMFMediaType> video, audio;
        Ok(Samples::VideoType(&video)); Ok(Samples::AudioType(&audio));
        GUID value{}; Ok(video->GetGUID(MF_MT_SUBTYPE, &value)); Check(value == MFVideoFormat_NV12);
        UINT32 a = 0, b = 0;
        Ok(MFGetAttributeSize(video.Get(), MF_MT_FRAME_SIZE, &a, &b)); Check(a == 640 && b == 480);
        Ok(MFGetAttributeRatio(video.Get(), MF_MT_FRAME_RATE, &a, &b)); Check(a == 15 && b == 1);
        Ok(video->GetUINT32(MF_MT_SAMPLE_SIZE, &a)); Check(a == Samples::VideoBytes);
        Ok(video->GetUINT32(MF_MT_DEFAULT_STRIDE, &a)); Check(a == 640);
        Ok(video->GetUINT32(MF_MT_INTERLACE_MODE, &a)); Check(a == MFVideoInterlace_Progressive);
        Ok(audio->GetGUID(MF_MT_SUBTYPE, &value)); Check(value == MFAudioFormat_PCM);
        Ok(audio->GetUINT32(MF_MT_AUDIO_NUM_CHANNELS, &a)); Check(a == 1);
        Ok(audio->GetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, &a)); Check(a == 48000);
        Ok(audio->GetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, &a)); Check(a == 16);
        Ok(audio->GetUINT32(MF_MT_AUDIO_BLOCK_ALIGNMENT, &a)); Check(a == 2);
        Ok(audio->GetUINT32(MF_MT_AUDIO_AVG_BYTES_PER_SECOND, &a)); Check(a == 96000);
        Check(Samples::VideoType(nullptr) == E_POINTER && Samples::AudioType(nullptr) == E_POINTER);
    }

    void VideoConversion()
    {
        Owner owner; Samples lane(Owner::Current, &owner, false);
        const auto data = Picture(); auto original = data;
        ComPtr<IMFSample> sample; Ok(lane.Video(data.data(), data.size(), 0, 1234567890123LL, &sample));
        auto output = Bytes(sample.Get()); Check(output.size() == data.size());
        constexpr std::size_t y = 640 * 480, chroma = y / 4;
        Check(std::memcmp(output.data(), data.data(), y) == 0);
        for (std::size_t i = 0; i < chroma; ++i)
            Check(output[y + 2 * i] == data[y + i] && output[y + 2 * i + 1] == data[y + chroma + i]);
        Check(data == original);
        LONGLONG value = 0; Ok(sample->GetSampleTime(&value)); Check(value == 12345678901230LL);
        Ok(sample->GetSampleDuration(&value)); Check(value == 666667);
        Check(owner.calls == 4 && !lane.IsRetired());
    }

    void AudioAndCommonEpoch()
    {
        Owner owner; Samples lane(Owner::Current, &owner, false);
        std::vector<std::uint8_t> pcm(Samples::AudioBytes);
        for (std::size_t i = 0; i < pcm.size(); ++i) pcm[i] = static_cast<std::uint8_t>(i);
        const auto data = Picture(); ComPtr<IMFSample> audio, video;
        Ok(lane.Audio(pcm.data(), pcm.size(), 0, 9007199254700000LL, &audio));
        Ok(lane.Video(data.data(), data.size(), 0, 9007199254740991LL, &video));
        Check(Bytes(audio.Get()) == pcm);
        LONGLONG a = 0, v = 0; Ok(audio->GetSampleTime(&a)); Ok(video->GetSampleTime(&v));
        Check(a == 90071992547000000LL && v == 90071992547409910LL && v - a == 409910);
        Ok(audio->GetSampleDuration(&a)); Check(a == 200000);
    }

    void OriginalGuardEveryBoundary()
    {
        const auto data = Picture();
        for (int boundary = 1; boundary <= 4; ++boundary)
        {
            Owner owner; owner.denyAt = boundary; Samples lane(Owner::Current, &owner, false);
            IMFSample* sample = reinterpret_cast<IMFSample*>(1);
            Check(FAILED(lane.Video(data.data(), data.size(), 0, 0, &sample)));
            Check(sample == nullptr && lane.IsRetired());
            owner.denyAt = 0;
            Check(lane.Video(data.data(), data.size(), 0, 0, &sample) == MF_E_SHUTDOWN && sample == nullptr);
        }
    }

    void InvalidSizes()
    {
        const auto data = Picture(); std::vector<std::uint8_t> audio(Samples::AudioBytes);
        for (auto bytes : {std::size_t(0), Samples::VideoBytes - 1, Samples::VideoBytes + 1})
        {
            Owner owner; Samples lane(Owner::Current, &owner, false); ComPtr<IMFSample> sample;
            Check(FAILED(lane.Video(data.data(), bytes, 0, 0, &sample)) && lane.IsRetired() && !sample);
        }
        for (auto bytes : {std::size_t(0), Samples::AudioBytes - 1, Samples::AudioBytes + 1})
        {
            Owner owner; Samples lane(Owner::Current, &owner, false); ComPtr<IMFSample> sample;
            Check(FAILED(lane.Audio(audio.data(), bytes, 0, 0, &sample)) && lane.IsRetired() && !sample);
        }
    }

    void SequenceAndPts()
    {
        const auto data = Picture();
        for (const auto sequence : {-1LL, 1LL, 9223372036854775807LL})
        {
            Owner owner; Samples lane(Owner::Current, &owner, false); ComPtr<IMFSample> sample;
            Check(FAILED(lane.Video(data.data(), data.size(), sequence, 0, &sample)) && lane.IsRetired());
        }
        for (const auto pts : {-1LL, 9007199254740992LL})
        {
            Owner owner; Samples lane(Owner::Current, &owner, false); ComPtr<IMFSample> sample;
            Check(FAILED(lane.Video(data.data(), data.size(), 0, pts, &sample)) && lane.IsRetired());
        }
        for (int invalid = 0; invalid < 3; ++invalid)
        {
            Owner owner; Samples lane(Owner::Current, &owner, false); ComPtr<IMFSample> sample;
            Ok(lane.Video(data.data(), data.size(), 0, 100, &sample)); sample.Reset();
            Check(FAILED(lane.Video(data.data(), data.size(), invalid == 0 ? 0 : invalid == 1 ? 2 : 1,
                invalid == 2 ? 100 : 200, &sample)) && lane.IsRetired() && !sample);
        }
    }

    void AvSkewAndSharedRetirement()
    {
        const auto data = Picture(); std::vector<std::uint8_t> audio(Samples::AudioBytes);
        Owner owner; Samples lane(Owner::Current, &owner, false); ComPtr<IMFSample> sample;
        Ok(lane.Video(data.data(), data.size(), 0, 0, &sample)); sample.Reset();
        Ok(lane.Audio(audio.data(), audio.size(), 0, 250000, &sample)); sample.Reset();
        Check(FAILED(lane.Audio(audio.data(), audio.size(), 1, 250001, &sample)) && lane.IsRetired() && !sample);
        Check(lane.Video(data.data(), data.size(), 1, 66667, &sample) == MF_E_SHUTDOWN && !sample);
    }

    void ExplicitMute()
    {
        const auto data = Picture(); std::vector<std::uint8_t> audio(Samples::AudioBytes);
        Owner owner; Samples lane(Owner::Current, &owner, true); ComPtr<IMFSample> sample;
        Ok(lane.Video(data.data(), data.size(), 0, 0, &sample)); sample.Reset();
        Check(FAILED(lane.Audio(audio.data(), audio.size(), 0, 0, &sample)) && lane.IsRetired() && !sample);
    }

    void NullsAndMissingOwner()
    {
        const auto data = Picture(); ComPtr<IMFSample> sample;
        Samples missing(nullptr, nullptr, false); Check(missing.IsRetired());
        Check(missing.Video(data.data(), data.size(), 0, 0, &sample) == MF_E_SHUTDOWN);
        Owner owner; Samples lane(Owner::Current, &owner, false);
        Check(lane.Video(nullptr, data.size(), 0, 0, &sample) == E_INVALIDARG && lane.IsRetired());
        Samples output(Owner::Current, &owner, false);
        Check(output.Video(data.data(), data.size(), 0, 0, nullptr) == E_POINTER && output.IsRetired());
    }

    void StopAndSequenceProgress()
    {
        const auto data = Picture(); Owner owner; Samples lane(Owner::Current, &owner, false);
        ComPtr<IMFSample> first, second;
        Ok(lane.Video(data.data(), data.size(), 0, 0, &first));
        Ok(lane.Video(data.data(), data.size(), 1, 66667, &second));
        Check(first.Get() != second.Get());
        lane.Retire(); lane.Retire(); second.Reset();
        Check(lane.Video(data.data(), data.size(), 2, 133334, &second) == MF_E_SHUTDOWN && !second);
        Owner race; Samples raced(Owner::Current, &race, false); race.retire = &raced;
        Check(raced.Video(data.data(), data.size(), 0, 0, &second) == MF_E_SHUTDOWN && !second);
    }
}

int main()
{
    const HRESULT com = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(com)) return 2;
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET))) { CoUninitialize(); return 3; }
    int failed = 0;
    const struct { const char* name; void (*run)(); } cases[] = {
        {"media-types", MediaTypes}, {"video-i420-nv12", VideoConversion},
        {"audio-common-epoch", AudioAndCommonEpoch}, {"original-guard-four-boundaries", OriginalGuardEveryBoundary},
        {"exact-payload-sizes", InvalidSizes}, {"sequence-and-pts", SequenceAndPts},
        {"av-skew-shared-retirement", AvSkewAndSharedRetirement}, {"explicit-mute", ExplicitMute},
        {"nulls-missing-owner", NullsAndMissingOwner}, {"stop-sequence-progress", StopAndSequenceProgress}
    };
    for (const auto& test : cases)
    {
        try { test.run(); std::printf("PASS %s\n", test.name); }
        catch (...) { ++failed; std::printf("FAIL %s\n", test.name); }
    }
    MFShutdown(); CoUninitialize();
    return failed ? 1 : 0;
}
