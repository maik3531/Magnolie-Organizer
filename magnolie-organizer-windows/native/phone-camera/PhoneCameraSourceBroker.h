#pragma once
#include "PhoneCameraDormantSource.h"

namespace Magnolie::PhoneCamera
{
    // Private IN-PROCESS lifetime control only, never marshalled or a grant.
    MIDL_INTERFACE("ff129a1d-e5f7-4659-9878-8414b64027ab") ISourceBrokerLifetime : IUnknown
    {
        virtual void STDMETHODCALLTYPE RequestStop() noexcept = 0;
    };
    // Called only by the original module's one-shot property callback. Checks
    // the actual FrameServer host, original held parent, OS property capability,
    // original pipe/event security and live control lease before constructing
    // the private proof for this EXACT retained controller. No metadata fallback.
    HRESULT BindOriginalSourceBroker(RegistrationLifetime originalRegistration,
        const std::shared_ptr<DormantSourceControl>& exactTarget, const BYTE* property, ULONG bytes,
        ISourceBrokerLifetime** lifetime) noexcept;
}
