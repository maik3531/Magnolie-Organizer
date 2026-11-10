#include "PhoneCameraFactory.h"
#include <wrl.h>

namespace Magnolie::PhoneCamera
{
    class Factory final : public Microsoft::WRL::RuntimeClass<
        Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, IClassFactory>
    {
    public:
        explicit Factory(FactoryOwner owner) : owner_(owner), lifetime_(owner.lifetime) {}
        STDMETHODIMP CreateInstance(IUnknown* outer, REFIID iid, void** result) override
        {
            if (!result) return E_POINTER;
            *result = nullptr;
            if (outer) return CLASS_E_NOAGGREGATION;
            if (iid != IID_IUnknown && iid != __uuidof(IMFActivate) && iid != __uuidof(IMFAttributes)) return E_NOINTERFACE;
            Microsoft::WRL::ComPtr<IMFActivate> activate;
            HRESULT hr = owner_.activate(owner_.context, &activate);
            if (SUCCEEDED(hr) && !activate) hr = E_UNEXPECTED;
            if (SUCCEEDED(hr)) hr = activate->QueryInterface(iid, result);
            if (FAILED(hr) && activate) activate->ShutdownObject();
            return hr;
        }
        STDMETHODIMP LockServer(BOOL locked) override { return owner_.lockServer(owner_.context, locked); }
    private:
        FactoryOwner owner_;
        Microsoft::WRL::ComPtr<IUnknown> lifetime_;
    };

    HRESULT CreateFactory(const FactoryOwner& owner, IClassFactory** result) noexcept
    {
        if (!result) return E_POINTER;
        *result = nullptr;
        if (!owner.activate || !owner.lockServer) return E_INVALIDARG;
        try
        {
            auto factory = Microsoft::WRL::Make<Factory>(owner);
            return factory ? factory.CopyTo(result) : E_OUTOFMEMORY;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
}
