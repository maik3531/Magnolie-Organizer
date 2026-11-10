#include "PhoneCameraFactoryProbe.h"
#include "../../native/phone-camera/PhoneCameraFactory.h"
#include <mferror.h>
#include <wrl.h>
#include <atomic>

using namespace Magnolie::PhoneCamera;
using Microsoft::WRL::ComPtr;
namespace
{
    std::atomic_uint contexts{0}, locks{0};
    class Context final : public Microsoft::WRL::RuntimeClass<Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, IUnknown>
    {
    public:
        Context() { ++contexts; }
        ~Context() { --contexts; }
        std::atomic_bool stopped{false};
        static HRESULT Current(void* context) noexcept
        { return static_cast<Context*>(context)->stopped ? MF_E_SHUTDOWN : S_OK; }
        // This DLL is a METADATA/LIFETIME probe. It has no phone permit, pipe
        // bootstrap, generator or microphone. No caller can obtain SEND here.
        static HRESULT Sending(void*) noexcept { return E_ACCESSDENIED; }
        static void Retired(void* context, HRESULT) noexcept { static_cast<Context*>(context)->stopped = true; }
        static HRESULT Construct(void* context, IMFAttributes*, IMFMediaSourceEx** source) noexcept
        {
            auto* owner = static_cast<Context*>(context); ComPtr<IFrameFeed> feed;
            return CreateSource({Current, Sending, Retired, owner, owner}, source, &feed);
        }
        static HRESULT NewActivation(void*, IMFActivate** result) noexcept
        {
            auto context = Microsoft::WRL::Make<Context>();
            return context ? CreateActivate({Current, Construct, context.Get(), context.Get()}, result) : E_OUTOFMEMORY;
        }
        static HRESULT Lock(void*, BOOL locked) noexcept
        {
            if (locked) { ++locks; return S_OK; }
            unsigned int count = locks.load();
            do { if (!count) return E_UNEXPECTED; } while (!locks.compare_exchange_weak(count, count - 1));
            return S_OK;
        }
    };
}

extern "C" HRESULT WINAPI DllGetClassObject(REFCLSID id, REFIID iid, void** result)
{
    if (!result) return E_POINTER;
    *result = nullptr;
    if (id != FactoryProbeId) return CLASS_E_CLASSNOTAVAILABLE;
    auto context = Microsoft::WRL::Make<Context>(); if (!context) return E_OUTOFMEMORY;
    ComPtr<IClassFactory> factory;
    HRESULT hr = CreateFactory({Context::NewActivation, Context::Lock, context.Get(), context.Get()}, &factory);
    return FAILED(hr) ? hr : factory->QueryInterface(iid, result);
}
extern "C" HRESULT WINAPI DllCanUnloadNow()
{ return contexts.load() == 0 && locks.load() == 0 ? S_OK : S_FALSE; }
