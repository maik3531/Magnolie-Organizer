#pragma once
#include "PhoneCameraSamples.h"

namespace Magnolie::PhoneCamera
{
    struct SourceOwner
    {
        Samples::Current current;
        Samples::Current sending;
        void (*retired)(void* context, HRESULT reason) noexcept;
        void* context;
        // Optional native COM/DLL lifetime anchor, never an authorization token.
        // Held until the last source/stream state reference is released, including
        // shutdown interfaces retained by a capture client and pending callbacks.
        IUnknown* lifetime = nullptr;
    };

    // Private in-process feed. Not an IPC endpoint, capture consent or SEND grant.
    MIDL_INTERFACE("452f5d78-341b-4cd1-bfb2-4e684d012eab") IFrameFeed : IUnknown
    {
        virtual HRESULT STDMETHODCALLTYPE PublishVideo(const BYTE* i420, DWORD size,
            LONGLONG sequence, LONGLONG ptsUs) = 0;
    };

    // Creates only a Media Foundation object, never a registered system camera.
    // Callbacks must be nonblocking, nonreentrant and remain valid until Shutdown
    // returns. current checks original ownership; sending also checks actual SEND.
    // retired must revoke the original joined AV owner, not a replacement session.
    // The owning controller MUST call Shutdown, including if no client starts it.
    HRESULT CreateSource(const SourceOwner& owner, IMFMediaSourceEx** source, IFrameFeed** feed) noexcept;
}
