#include "PhoneCameraModule.h"
#include "PhoneCameraFactory.h"
#include "PhoneCameraDormantSource.h"
#include "PhoneCameraSourceBroker.h"
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
            std::mutex gate;
            std::shared_ptr<DormantSourceControl> control;
            Microsoft::WRL::ComPtr<ISourceBrokerLifetime> broker;
            bool bindingAttempted = false;

            // Registration liveness ONLY, never passed as SourceOwner/ClockOwner
            // and never capture/SEND readiness. The dormant shell refuses media.
            static HRESULT RegistrationCurrent(void* context) noexcept
            { return static_cast<ModuleContext*>(context)->stopped.load() ? MF_E_SHUTDOWN : S_OK; }
            static void RegistrationClosed(void* context) noexcept
            {
                auto& root = *static_cast<ModuleContext*>(context);
                root.stopped.store(true);
                std::shared_ptr<DormantSourceControl> held;
                Microsoft::WRL::ComPtr<ISourceBrokerLifetime> activeBroker;
                { std::lock_guard<std::mutex> lock(root.gate); held = std::move(root.control); activeBroker = std::move(root.broker); }
                if (activeBroker) activeBroker->RequestStop(); // Never wait/join on an MF/registration callback.
                if (held) held->Stop(); // A receiver retains the exact controller until its own drain.
            }
            static HRESULT ConstructDormant(void* context, IMFAttributes* metadata, IMFMediaSourceEx** result) noexcept
            {
                auto& root = *static_cast<ModuleContext*>(context);
                // No caller attributes (including a purported scope/ready flag)
                // manufacture a broker proof or an existing capture owner.
                if (!result) return E_POINTER; *result = nullptr;
                try
                {
                    std::unique_ptr<DormantSourceControl> controller;
                    Microsoft::WRL::ComPtr<IMFMediaSourceEx> source;
                    HRESULT hr = CreateDormantSource({RegistrationCurrent, &root, &root, RegistrationClosed, BindProperty}, &source, controller, metadata);
                    if (FAILED(hr)) return hr;
                    auto held = std::shared_ptr<DormantSourceControl>(std::move(controller));
                    {
                        std::lock_guard<std::mutex> lock(root.gate);
                        if (root.stopped.load() || root.control) hr = MF_E_SHUTDOWN;
                        else root.control = held;
                    }
                    if (FAILED(hr)) { source->Shutdown(); return hr; }
                    return source.CopyTo(result);
                }
                catch (...) { return E_OUTOFMEMORY; }
            }
            static HRESULT BindProperty(void* context, const BYTE* property, ULONG bytes) noexcept
            {
                auto& root = *static_cast<ModuleContext*>(context);
                std::shared_ptr<DormantSourceControl> held;
                {
                    std::lock_guard<std::mutex> lock(root.gate);
                    if (root.stopped.load() || root.bindingAttempted || !root.control) return MF_E_SHUTDOWN;
                    root.bindingAttempted = true; held = root.control;
                }
                Microsoft::WRL::ComPtr<ISourceBrokerLifetime> activeBroker;
                HRESULT hr = BindOriginalSourceBroker({RegistrationCurrent, &root, &root, RegistrationClosed, BindProperty},
                    held, property, bytes, &activeBroker);
                if (FAILED(hr)) return hr;
                {
                    std::lock_guard<std::mutex> lock(root.gate);
                    if (root.stopped.load()) hr = MF_E_SHUTDOWN;
                    else root.broker = activeBroker;
                }
                if (FAILED(hr)) activeBroker->RequestStop();
                return hr;
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
