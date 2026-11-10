#include "PhoneCameraActivate.h"
#include <mfapi.h>
#include <mferror.h>
#include <wrl.h>

namespace Magnolie::PhoneCamera
{
    using Microsoft::WRL::ComPtr;
    class Activate final : public Microsoft::WRL::RuntimeClass<
        Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>,
        Microsoft::WRL::ChainInterfaces<IMFActivate, IMFAttributes>>
    {
    public:
        explicit Activate(ActivateOwner owner) : owner_(owner), lifetime_(owner.lifetime) {}
        // Releasing activation metadata is not a request to shut down a source
        // independently held by FrameServer. Its original controller still
        // owns explicit Shutdown and the source's live authority checks.
        ~Activate() = default;
        HRESULT Initialize() noexcept { return MFCreateAttributes(&attributes_, 8); }
        STDMETHODIMP ActivateObject(REFIID iid, void** result) override
        {
            if (!result) return E_POINTER;
            *result = nullptr;
            std::lock_guard<std::mutex> lock(gate_);
            if (spent_) return MF_E_SHUTDOWN;
            HRESULT hr = owner_.current(owner_.context);
            if (FAILED(hr)) { RetireLocked(); return hr; }
            if (!source_)
            {
                ComPtr<IMFAttributes> snapshot;
                hr = MFCreateAttributes(&snapshot, 8);
                if (SUCCEEDED(hr)) hr = attributes_->LockStore();
                if (SUCCEEDED(hr))
                {
                    const HRESULT copied = attributes_->CopyAllItems(snapshot.Get());
                    const HRESULT unlocked = attributes_->UnlockStore();
                    hr = FAILED(copied) ? copied : unlocked;
                }
                if (SUCCEEDED(hr)) hr = owner_.current(owner_.context);
                if (SUCCEEDED(hr)) hr = owner_.construct(owner_.context, snapshot.Get(), &source_);
                if (SUCCEEDED(hr) && !source_) hr = E_UNEXPECTED;
                if (SUCCEEDED(hr)) hr = owner_.current(owner_.context);
                if (FAILED(hr)) { RetireLocked(); return hr; }
            }
            hr = source_->QueryInterface(iid, result);
            if (SUCCEEDED(hr))
            {
                const HRESULT current = owner_.current(owner_.context);
                if (FAILED(current))
                {
                    static_cast<IUnknown*>(*result)->Release(); *result = nullptr;
                    RetireLocked(); return current;
                }
            }
            return hr;
        }
        STDMETHODIMP ShutdownObject() override
        {
            std::lock_guard<std::mutex> lock(gate_);
            if (spent_) return MF_E_SHUTDOWN;
            RetireLocked(); return S_OK;
        }
        STDMETHODIMP DetachObject() override
        {
            std::lock_guard<std::mutex> lock(gate_);
            if (spent_) return MF_E_SHUTDOWN;
            // The returned source belongs to its actual native owner now. Do not
            // shut it down here or create a replacement on this old activation.
            spent_ = true; source_.Reset(); return S_OK;
        }

#define ATTRIBUTE(name, signature, arguments) STDMETHODIMP name signature override { return attributes_->name arguments; }
        ATTRIBUTE(GetItem, (REFGUID key, PROPVARIANT* item), (key, item))
        ATTRIBUTE(GetItemType, (REFGUID key, MF_ATTRIBUTE_TYPE* type), (key, type))
        ATTRIBUTE(CompareItem, (REFGUID key, REFPROPVARIANT item, BOOL* result), (key, item, result))
        ATTRIBUTE(Compare, (IMFAttributes* other, MF_ATTRIBUTES_MATCH_TYPE match, BOOL* result), (other, match, result))
        ATTRIBUTE(GetUINT32, (REFGUID key, UINT32* item), (key, item))
        ATTRIBUTE(GetUINT64, (REFGUID key, UINT64* item), (key, item))
        ATTRIBUTE(GetDouble, (REFGUID key, double* item), (key, item))
        ATTRIBUTE(GetGUID, (REFGUID key, GUID* item), (key, item))
        ATTRIBUTE(GetStringLength, (REFGUID key, UINT32* length), (key, length))
        ATTRIBUTE(GetString, (REFGUID key, LPWSTR text, UINT32 size, UINT32* length), (key, text, size, length))
        ATTRIBUTE(GetAllocatedString, (REFGUID key, LPWSTR* text, UINT32* length), (key, text, length))
        ATTRIBUTE(GetBlobSize, (REFGUID key, UINT32* size), (key, size))
        ATTRIBUTE(GetBlob, (REFGUID key, UINT8* blob, UINT32 size, UINT32* used), (key, blob, size, used))
        ATTRIBUTE(GetAllocatedBlob, (REFGUID key, UINT8** blob, UINT32* size), (key, blob, size))
        ATTRIBUTE(GetUnknown, (REFGUID key, REFIID iid, LPVOID* result), (key, iid, result))
        ATTRIBUTE(SetItem, (REFGUID key, REFPROPVARIANT item), (key, item))
        ATTRIBUTE(DeleteItem, (REFGUID key), (key))
        ATTRIBUTE(DeleteAllItems, (), ())
        ATTRIBUTE(SetUINT32, (REFGUID key, UINT32 item), (key, item))
        ATTRIBUTE(SetUINT64, (REFGUID key, UINT64 item), (key, item))
        ATTRIBUTE(SetDouble, (REFGUID key, double item), (key, item))
        ATTRIBUTE(SetGUID, (REFGUID key, REFGUID item), (key, item))
        ATTRIBUTE(SetString, (REFGUID key, LPCWSTR text), (key, text))
        ATTRIBUTE(SetBlob, (REFGUID key, const UINT8* blob, UINT32 size), (key, blob, size))
        ATTRIBUTE(SetUnknown, (REFGUID key, IUnknown* item), (key, item))
        ATTRIBUTE(LockStore, (), ())
        ATTRIBUTE(UnlockStore, (), ())
        ATTRIBUTE(GetCount, (UINT32* count), (count))
        ATTRIBUTE(GetItemByIndex, (UINT32 index, GUID* key, PROPVARIANT* item), (index, key, item))
        ATTRIBUTE(CopyAllItems, (IMFAttributes* target), (target))
#undef ATTRIBUTE
    private:
        void RetireLocked() noexcept
        { spent_ = true; if (source_) source_->Shutdown(); source_.Reset(); }
        ActivateOwner owner_;
        ComPtr<IUnknown> lifetime_;
        ComPtr<IMFAttributes> attributes_;
        ComPtr<IMFMediaSourceEx> source_;
        bool spent_ = false;
        std::mutex gate_;
    };

    HRESULT CreateActivate(const ActivateOwner& owner, IMFActivate** result) noexcept
    {
        if (!result) return E_POINTER;
        *result = nullptr;
        if (!owner.current || !owner.construct) return E_INVALIDARG;
        try
        {
            auto activate = Microsoft::WRL::Make<Activate>(owner);
            if (!activate) return E_OUTOFMEMORY;
            HRESULT hr = activate->Initialize(); return FAILED(hr) ? hr : activate.CopyTo(result);
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
}
