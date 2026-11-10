#include "../../native/phone-camera/PhoneCameraClock.h"
#include <mfapi.h>
#include <mfidl.h>
#include <mferror.h>
#include <cstdio>
#include <stdexcept>
#include <initializer_list>

using namespace Magnolie::PhoneCamera;
namespace
{
    void Check(bool value) { if (!value) throw std::runtime_error("clock assertion"); }
    void Ok(HRESULT hr) { Check(SUCCEEDED(hr)); }
    struct Owner
    {
        bool current = true, sending = true, revokeOnSecond = false;
        int checks = 0, retired = 0;
        HRESULT reason = S_OK;
        LONGLONG now = 300000000000LL;
        static HRESULT Current(void* context) noexcept
        { auto& o = *static_cast<Owner*>(context); ++o.checks; if(o.revokeOnSecond && o.checks == 2) o.current = false; return o.current ? S_OK : E_ACCESSDENIED; }
        static HRESULT Sending(void* context) noexcept { return static_cast<Owner*>(context)->sending ? S_OK : E_ACCESSDENIED; }
        static void Retired(void* context, HRESULT reason) noexcept { auto& o = *static_cast<Owner*>(context); ++o.retired; o.reason = reason; }
        static LONGLONG Now(void* context) noexcept { return static_cast<Owner*>(context)->now; }
        ClockOwner Callbacks() { return {Current, Sending, Retired, this, nullptr, Now}; }
    };
    void JoinedTracksKeepOffsets()
    {
        Owner o; PresentationClock clock(o.Callbacks()); LONGLONG first=0, audio=0, video=0;
        Ok(clock.Map(0,&first)); o.now+=20000; Ok(clock.Map(20000,&audio)); o.now+=46667; Ok(clock.Map(66667,&video));
        Check(audio-first==20000 && video-first==66667 && video-audio==46667);
    }
    void LargePtsRetainMicroseconds()
    {
        Owner o; PresentationClock clock(o.Callbacks()); LONGLONG first=0, later=0;
        Ok(clock.Map(9007199254740000LL,&first)); ++o.now; Ok(clock.Map(9007199254740001LL,&later)); Check(later-first==1);
    }
    void NoPerTrackReanchor()
    {
        Owner o; PresentationClock clock(o.Callbacks()); LONGLONG video=0,audio=0;
        Ok(clock.Map(100000,&video)); o.now+=10000; Ok(clock.Map(80000,&audio)); Check(video-audio==20000);
    }
    void ForwardAndLateBoundaries()
    {
        for (int sign : {-1,1})
        {
            Owner o; PresentationClock clock(o.Callbacks()); LONGLONG value=0;
            Ok(clock.Map(1000000,&value)); Ok(clock.Map(1000000+sign*250000,&value));
            Check(clock.Map(1000000+sign*250001,&value)==MF_E_NET_TIMEOUT && value==0 && o.retired==1);
            Check(clock.Map(1000000,&value)==MF_E_SHUTDOWN);
        }
    }
    void BackwardsNativeClockRetires()
    {
        Owner o; PresentationClock clock(o.Callbacks()); LONGLONG value=0; Ok(clock.Map(0,&value)); --o.now;
        Check(FAILED(clock.Map(1,&value)) && !value && o.retired==1); ++o.now; Check(clock.Map(1,&value)==MF_E_SHUTDOWN);
    }
    void OriginalGuardsAndPostMappingRevocation()
    {
        for(int mode=0;mode<3;++mode)
        {
            Owner o; o.current=mode!=0; o.sending=mode!=1; o.revokeOnSecond=mode==2;
            PresentationClock clock(o.Callbacks()); LONGLONG value=99;
            Check(clock.Map(0,&value)==E_ACCESSDENIED && !value && o.retired==1);
            o.current=true; o.sending=true; Check(clock.Map(0,&value)==MF_E_SHUTDOWN && !value);
        }
    }
    void InvalidRangeAndNativeOverflow()
    {
        for(LONGLONG bad : {-1LL,9007199254740992LL})
        { Owner o; PresentationClock clock(o.Callbacks()); LONGLONG v=9; Check(FAILED(clock.Map(bad,&v)) && !v && o.retired==1); }
        Owner o; o.now=9007199254740991LL; PresentationClock clock(o.Callbacks()); LONGLONG value=0;
        Ok(clock.Map(0,&value)); Check(FAILED(clock.Map(1,&value)) && !value && o.retired==1);
    }
    void ExplicitStopAndMissingAuthority()
    {
        Owner o;
        { PresentationClock clock(o.Callbacks()); clock.Stop(); clock.Stop(); LONGLONG v=9; Check(clock.Map(0,&v)==MF_E_SHUTDOWN && !v && o.retired==1); }
        Check(o.retired==1);
        Owner bad; auto callbacks=bad.Callbacks(); callbacks.sending=nullptr; PresentationClock clock(callbacks); LONGLONG v=9;
        Check(clock.Map(0,&v)==E_INVALIDARG && !v && bad.retired==1);
    }
    void NativeSystemClockDomain()
    {
        Owner o; auto callbacks=o.Callbacks(); callbacks.nowUs=nullptr; PresentationClock clock(callbacks);
        const LONGLONG before=MFGetSystemTime()/10; LONGLONG mapped=0; Ok(clock.Map(0,&mapped));
        const LONGLONG after=MFGetSystemTime()/10; Check(mapped>=before && mapped<=after);
        Check(clock.Map(0,nullptr)==E_POINTER);
    }
}
int main()
{
    if(FAILED(CoInitializeEx(nullptr,COINIT_MULTITHREADED))) return 2;
    if(FAILED(MFStartup(MF_VERSION,MFSTARTUP_NOSOCKET))) {CoUninitialize();return 3;}
    int failed=0;
    const struct { const char* name; void (*run)(); } cases[]={
        {"clock-joined-av-offsets",JoinedTracksKeepOffsets},{"clock-large-integer-pts",LargePtsRetainMicroseconds},
        {"clock-no-track-reanchor",NoPerTrackReanchor},{"clock-bounded-ahead-late",ForwardAndLateBoundaries},
        {"clock-backwards-native-time",BackwardsNativeClockRetires},{"clock-original-authority",OriginalGuardsAndPostMappingRevocation},
        {"clock-range-overflow",InvalidRangeAndNativeOverflow},{"clock-stop-missing-authority",ExplicitStopAndMissingAuthority},
        {"clock-real-mf-system-domain",NativeSystemClockDomain}
    };
    for(const auto& test:cases) {try{test.run();std::printf("PASS %s\n",test.name);}catch(...){++failed;std::printf("FAIL %s\n",test.name);}std::fflush(stdout);}
    MFShutdown();CoUninitialize();return failed?1:0;
}
