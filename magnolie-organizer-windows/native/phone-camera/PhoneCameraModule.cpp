#include "PhoneCameraModule.h"
#include "PhoneCameraFactory.h"
#include "PhoneCameraDormantSource.h"
#include <mferror.h>
#include <wrl.h>
#include <atomic>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        std::atomic_uint contexts{0}, serverLocks{0};
        class ModuleContext final : public Microsoft::WRL::RuntimeClass<
            Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>, IUnknown>
        {
        public:
            ModuleContext() { ++contexts; }
            ~ModuleContext() { --contexts; }
            std::atomic_bool stopped{false};
            std::unique_ptr<DormantSourceControl> control;

            // Registration liveness ONLY, never passed as SourceOwner/ClockOwner
            // and never capture/SEND readiness. The dormant shell refuses media.
            static HRESULT RegistrationCurrent(void* context) noexcept
            { return static_cast<ModuleContext*>(context)->stopped.load() ? MF_E_SHUTDOWN : S_OK; }
            static void RegistrationClosed(void* context) noexcept
            {
                auto& root = *static_cast<ModuleContext*>(context);
                root.stopped.store(true);
                root.control.reset(); // State is retained across the calling Stop/Adopt.
            }
            static HRESULT ConstructDormant(void* context, IMFAttributes* metadata, IMFMediaSourceEx** result) noexcept
            {
                auto& root = *static_cast<ModuleContext*>(context);
                // No caller attributes (including a purported scope/ready flag)
                // manufacture a broker proof or an existing capture owner.
                return CreateDormantSource({RegistrationCurrent, &root, &root, RegistrationClosed}, result, root.control, metadata);
            }
            static HRESULT NewActivation(void*, IMFActivate** result) noexcept
            {
                if (!result) return E_POINTER; *result = nullptr;
                auto context = Microsoft::WRL::Make<ModuleContext>();
                if (!context) return E_OUTOFMEMORY;
                return CreateActivate({RegistrationCurrent, ConstructDormant, context.Get(), context.Get()}, result);
            }
            static HRESULT LockServer(void*, BOOL locked) noexcept
            {
                if (locked) { ++serverLocks; return S_OK; }
                unsigned int count = serverLocks.load();
                do { if (!count) return E_UNEXPECTED; }
                while (!serverLocks.compare_exchange_weak(count, count - 1));
                return S_OK;
            }
        };
    }
    HRESULT ModuleFactory(REFCLSID id, REFIID iid, void** result) noexcept
    {
        if (!result) return E_POINTER; *result = nullptr;
        if (id != SourceClassId) return CLASS_E_CLASSNOTAVAILABLE;
        try
        {
            auto context = Microsoft::WRL::Make<ModuleContext>();
            if (!context) return E_OUTOFMEMORY;
            Microsoft::WRL::ComPtr<IClassFactory> factory;
            HRESULT hr = CreateFactory({ModuleContext::NewActivation, ModuleContext::LockServer,
                context.Get(), context.Get()}, &factory);
            return FAILED(hr) ? hr : factory->QueryInterface(iid, result);
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    HRESULT ModuleCanUnload() noexcept
    { return contexts.load() == 0 && serverLocks.load() == 0 ? S_OK : S_FALSE; }
}

extern "C" HRESULT WINAPI DllGetClassObject(REFCLSID id, REFIID iid, void** result)
{ return Magnolie::PhoneCamera::ModuleFactory(id, iid, result); }
extern "C" HRESULT WINAPI DllCanUnloadNow()
{ return Magnolie::PhoneCamera::ModuleCanUnload(); }
