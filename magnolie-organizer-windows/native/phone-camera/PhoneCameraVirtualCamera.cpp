#include "PhoneCameraVirtualCamera.h"
#include "PhoneCameraModule.h"
#include "PhoneCameraBrokerProtocol.h"
#include <ks.h>
#include <mfvirtualcamera.h>
#include <mferror.h>
#include <string>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        std::atomic_bool uncertainRegistration{false};
        std::mutex registrationCalls;
        HRESULT Exact(HRESULT hr) noexcept { return hr == S_OK ? S_OK : FAILED(hr) ? hr : E_ACCESSDENIED; }
        HRESULT OrdinaryUser() noexcept
        {
            APTTYPE apartment{}; APTTYPEQUALIFIER qualifier{};
            HRESULT hr = CoGetApartmentType(&apartment, &qualifier);
            if (FAILED(hr)) return hr;
            if (apartment != APTTYPE_MTA) return E_ACCESSDENIED; // Never block a consent/UI apartment.
            // MF uses the effective caller. An ordinary process must not create
            // another user's/system camera through an impersonating thread.
            HANDLE impersonation = nullptr;
            if (OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, TRUE, &impersonation))
            { CloseHandle(impersonation); return E_ACCESSDENIED; }
            DWORD threadError = GetLastError();
            if (threadError != ERROR_NO_TOKEN) return HRESULT_FROM_WIN32(threadError);
            HANDLE token = nullptr;
            if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return HRESULT_FROM_WIN32(GetLastError());
            TOKEN_ELEVATION elevation{}; DWORD bytes = 0;
            BOOL found = GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &bytes);
            DWORD error = found ? ERROR_SUCCESS : GetLastError(); CloseHandle(token);
            if (!found) return HRESULT_FROM_WIN32(error);
            DWORD session = 0;
            if (!ProcessIdToSessionId(GetCurrentProcessId(), &session)) return HRESULT_FROM_WIN32(GetLastError());
            return elevation.TokenIsElevated || !session ? E_ACCESSDENIED : S_OK;
        }
    }

    struct VirtualCamera::OsSession final : Session
    {
        HMODULE module = nullptr;
        Microsoft::WRL::ComPtr<IMFVirtualCamera> camera;
        ~OsSession() override
        {
            camera.Reset(); // Release COM before unloading its original module.
            if (module) FreeLibrary(module);
        }
        HRESULT Start() noexcept override
        { HRESULT hr = OrdinaryUser(); return FAILED(hr) ? hr : camera->Start(nullptr); }
        HRESULT Shutdown() noexcept override
        { HRESULT hr = OrdinaryUser(); return FAILED(hr) ? hr : camera->Shutdown(); }
        HRESULT SendBinding(BYTE* property, ULONG bytes) noexcept override
        {
            HRESULT hr = OrdinaryUser(); if (FAILED(hr)) return hr;
            ULONG written = 0;
            hr = Exact(camera->SendCameraProperty(BrokerProperty::PropertySet, BrokerProperty::PropertyId,
                KSPROPERTY_TYPE_SET, property, bytes, nullptr, 0, &written));
            return hr == S_OK && written ? E_ACCESSDENIED : hr;
        }
    };

    VirtualCamera::VirtualCamera(VirtualCameraOwner original, std::unique_ptr<Session> session) noexcept
        : owner_(original), lifetime_(original.lifetime), session_(std::move(session)) {}
    VirtualCamera::~VirtualCamera()
    {
        if (FAILED(Close()))
        {
            // Deliberately retain the exact unknown COM/module/owner references
            // until process exit, without allocating, retrying or callbacks into
            // freed context. The process latch prevents a replacement Create.
            // A normal caller retains this wrapper on failed Close for review.
            session_.release(); lifetime_.Detach();
        }
    }

    HRESULT VirtualCamera::Create(VirtualCameraOwner original, std::unique_ptr<VirtualCamera>& result) noexcept
    {
        if (result) return E_INVALIDARG; // Never destroy/replace another original manager.
        if (!original.current || !original.lifetime) return E_INVALIDARG;
        // Retain the actual owner throughout OS calls, not just after publication.
        Microsoft::WRL::ComPtr<IUnknown> lifetime(original.lifetime);
        HRESULT hr = Exact(original.current(original.context)); if (FAILED(hr)) return hr;
        if (uncertainRegistration.load()) return HRESULT_FROM_WIN32(ERROR_BUSY);
        hr = OrdinaryUser(); if (FAILED(hr)) return hr;
        try
        {
            auto session = std::make_unique<OsSession>();
            // Windows 10 can load the ordinary application without this API.
            // No search-path/adjacent-DLL or elevated compatibility fallback.
            session->module = LoadLibraryExW(L"mfsensorgroup.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
            if (!session->module) return HRESULT_FROM_WIN32(GetLastError());
            auto create = reinterpret_cast<decltype(&MFCreateVirtualCamera)>(GetProcAddress(session->module, "MFCreateVirtualCamera"));
            if (!create) return HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED);
            GUID fresh{}; hr = CoCreateGuid(&fresh); if (FAILED(hr)) return hr;
            wchar_t suffix[40]{}, source[40]{};
            if (!StringFromGUID2(fresh, suffix, 40) || !StringFromGUID2(SourceClassId, source, 40)) return E_UNEXPECTED;
            // MF keys registrations by the supplied tuple. A fresh per-owner
            // name prevents reopening/stopping someone else's matching camera.
            // This public GUID is collision avoidance, NEVER a secret/capability.
            std::wstring name = std::wstring(L"Magnolie Phone Camera ") + suffix;
            {
                std::lock_guard<std::mutex> lock(registrationCalls);
                if (uncertainRegistration.load()) return HRESULT_FROM_WIN32(ERROR_BUSY);
                hr = Exact(create(MFVirtualCameraType_SoftwareCameraSource, MFVirtualCameraLifetime_Session,
                    MFVirtualCameraAccess_CurrentUser, name.c_str(), source, nullptr, 0, &session->camera));
            }
            if (FAILED(hr)) return hr;
            if (!session->camera) return E_UNEXPECTED;
            auto manager = std::unique_ptr<VirtualCamera>(new VirtualCamera(original, std::move(session)));
            hr = manager->CurrentOwner(); if (FAILED(hr)) return hr;
            result = std::move(manager); return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }
    HRESULT VirtualCamera::CurrentOwner() noexcept
    {
        if (stopped_.load()) return MF_E_SHUTDOWN;
        if (uncertainRegistration.load()) { stopped_.store(true); return HRESULT_FROM_WIN32(ERROR_BUSY); }
        HRESULT hr = Exact(owner_.current(owner_.context));
        if (FAILED(hr)) stopped_.store(true);
        if (hr == S_OK && uncertainRegistration.load()) { stopped_.store(true); return HRESULT_FROM_WIN32(ERROR_BUSY); }
        return stopped_.load() && hr == S_OK ? MF_E_SHUTDOWN : hr;
    }
    HRESULT VirtualCamera::Start() noexcept
    {
        std::lock_guard<std::mutex> lock(operation_);
        if (startAttempted_ || closeAttempted_) return MF_E_SHUTDOWN;
        startAttempted_ = true;
        HRESULT hr = CurrentOwner();
        if (SUCCEEDED(hr))
        {
            // Linearize SDK calls across original instances: another owner may
            // have reported unknown shutdown after our CurrentOwner check.
            std::lock_guard<std::mutex> registration(registrationCalls);
            hr = uncertainRegistration.load() ? HRESULT_FROM_WIN32(ERROR_BUSY) :
                stopped_.load() ? MF_E_SHUTDOWN : Exact(session_->Start());
        }
        if (SUCCEEDED(hr)) hr = CurrentOwner();
        if (FAILED(hr)) { CloseLocked(); return hr; }
        started_.store(true); return S_OK; // Registration only, NEVER Ready/SEND.
    }
    HRESULT VirtualCamera::RequireCurrent() noexcept
    {
        HRESULT hr = CurrentOwner(); if (FAILED(hr)) return hr;
        return started_.load() ? S_OK : MF_E_NOT_INITIALIZED;
    }
    HRESULT VirtualCamera::SendSourceBinding(BYTE* property, ULONG bytes) noexcept
    {
        std::lock_guard<std::mutex> lock(operation_);
        if (bindingAttempted_ || closeAttempted_ || !started_.load()) return MF_E_SHUTDOWN;
        bindingAttempted_ = true;
        if (!property || bytes != BrokerProperty::Bytes) return E_INVALIDARG;
        HRESULT hr = CurrentOwner();
        // The broker listener already exists and runs concurrently. Never hold
        // the cross-instance registration mutex over a synchronous broker call.
        if (SUCCEEDED(hr)) hr = Exact(session_->SendBinding(property, bytes));
        if (SUCCEEDED(hr)) hr = CurrentOwner();
        return hr; // OS return is not peer authentication or media readiness.
    }
    HRESULT VirtualCamera::CloseLocked() noexcept
    {
        stopped_.store(true); started_.store(false);
        if (closeAttempted_) return closeResult_;
        closeAttempted_ = true;
        {
            std::lock_guard<std::mutex> registration(registrationCalls);
            closeResult_ = Exact(session_->Shutdown());
            if (closeResult_ != S_OK) uncertainRegistration.store(true);
        }
        if (closeResult_ == S_OK) session_.reset();
        // No Remove(), retry, re-open or different lifetime/access fallback.
        return closeResult_;
    }
    HRESULT VirtualCamera::Close() noexcept
    {
        RequestStop();
        std::lock_guard<std::mutex> lock(operation_);
        return CloseLocked();
    }
#ifdef MAGNOLIE_NATIVE_VIRTUAL_CAMERA_TESTS
    void VirtualCamera::ResetFakeUncertainty() noexcept { uncertainRegistration.store(false); }
#endif
}
