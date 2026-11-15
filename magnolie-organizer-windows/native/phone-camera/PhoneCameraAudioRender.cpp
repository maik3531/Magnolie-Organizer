#include "PhoneCameraAudioRender.h"
#include "PhoneCameraPipe.h"
#include "PhoneCameraOutputLease.h"
#include <aclapi.h>
#include <cfgmgr32.h>
#include <devicetopology.h>
#include <initguid.h>
#include <devpkey.h>
#include <functiondiscoverykeys_devpkey.h>
#include <mfapi.h>
#include <mferror.h>
#include <mmdeviceapi.h>
#include <mmreg.h>
#include <setupapi.h>
#include <tlhelp32.h>
#include <algorithm>
#include <cstring>
#include <cwchar>
#include <string>

namespace Magnolie::PhoneCamera
{
    using Microsoft::WRL::ComPtr;
    namespace
    {
        struct Key { HKEY value = nullptr; ~Key() { if (value) RegCloseKey(value); } };
        struct Local { void* value = nullptr; ~Local() { if (value) LocalFree(value); } };
        struct Text { wchar_t* value = nullptr; ~Text() { CoTaskMemFree(value); } };
        struct Format { WAVEFORMATEX* value = nullptr; ~Format() { CoTaskMemFree(value); } };
        struct Devices { HDEVINFO value = INVALID_HANDLE_VALUE; ~Devices() { if (value != INVALID_HANDLE_VALUE) SetupDiDestroyDeviceInfoList(value); } };

        HRESULT ReadText(HKEY key, const wchar_t* name, std::wstring& result)
        {
            wchar_t text[512]{}; DWORD size = sizeof(text);
            const LSTATUS status = RegGetValueW(key, nullptr, name, RRF_RT_REG_SZ | RRF_NOEXPAND, nullptr, text, &size);
            if (status != ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
            if (size < sizeof(wchar_t) || size > sizeof(text) || size % sizeof(wchar_t) ||
                wcsnlen_s(text, 512) != size / sizeof(wchar_t) - 1) return E_INVALIDARG;
            result = text; return S_OK;
        }

        bool ProtectedJournal(HKEY key) noexcept
        {
            Local descriptor; PSID owner = nullptr; PACL acl = nullptr;
            if (GetSecurityInfo(key, SE_REGISTRY_KEY, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &owner, nullptr, &acl, nullptr, reinterpret_cast<PSECURITY_DESCRIPTOR*>(&descriptor.value)) != ERROR_SUCCESS || !acl) return false;
            BYTE admin[SECURITY_MAX_SID_SIZE]{}, system[SECURITY_MAX_SID_SIZE]{};
            DWORD adminSize = sizeof(admin), systemSize = sizeof(system);
            if (!CreateWellKnownSid(WinBuiltinAdministratorsSid, nullptr, admin, &adminSize) ||
                !CreateWellKnownSid(WinLocalSystemSid, nullptr, system, &systemSize)) return false;
            auto privileged = [&](PSID sid) { return sid && (EqualSid(sid, admin) || EqualSid(sid, system)); };
            SECURITY_DESCRIPTOR_CONTROL control{}; DWORD revision = 0;
            if (!privileged(owner) || !GetSecurityDescriptorControl(descriptor.value, &control, &revision) || !(control & SE_DACL_PROTECTED) || acl->AceCount > 16) return false;
            constexpr DWORD write = KEY_SET_VALUE | KEY_CREATE_SUB_KEY | KEY_CREATE_LINK | DELETE | WRITE_DAC | WRITE_OWNER | GENERIC_WRITE | GENERIC_ALL;
            for (DWORD i = 0; i < acl->AceCount; ++i)
            {
                void* raw = nullptr; if (!GetAce(acl, i, &raw)) return false;
                const auto header = static_cast<ACE_HEADER*>(raw);
                if (header->AceType == ACCESS_DENIED_ACE_TYPE) continue;
                if (header->AceType != ACCESS_ALLOWED_ACE_TYPE) return false;
                const auto ace = static_cast<ACCESS_ALLOWED_ACE*>(raw);
                if ((ace->Mask & write) && !privileged(&ace->SidStart)) return false;
            }
            return true;
        }

        HRESULT OwnInstance(std::wstring& instance)
        {
            Key key;
            LSTATUS status = RegOpenKeyExW(HKEY_LOCAL_MACHINE,
                L"SOFTWARE\\Magnolie Organizer\\WebcamDriver\\VB-CABLE-Pack46", 0,
                KEY_QUERY_VALUE | READ_CONTROL | KEY_WOW64_64KEY, &key.value);
            if (status != ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
            if (!ProtectedJournal(key.value)) return E_ACCESSDENIED;
            std::wstring marker, state;
            HRESULT hr = ReadText(key.value, L"ScopeMarker", marker);
            if (SUCCEEDED(hr)) hr = ReadText(key.value, L"State", state);
            if (SUCCEEDED(hr)) hr = ReadText(key.value, L"OwnInstance", instance);
            if (FAILED(hr)) return hr;
            DWORD error = ~0UL, size = sizeof(error);
            status = RegGetValueW(key.value, nullptr, L"Error", RRF_RT_REG_DWORD, nullptr, &error, &size);
            if (status != ERROR_SUCCESS || size != sizeof(error) || error != ERROR_SUCCESS ||
                marker != L"Magnolie VB-CABLE Pack46 setup v1" ||
                (state != L"installed" && state != L"reboot_required") || instance.size() != 15 ||
                _wcsnicmp(instance.c_str(), L"ROOT\\MEDIA\\", 11)) return E_ACCESSDENIED;
            for (std::size_t i = 11; i < instance.size(); ++i)
                if (!((instance[i] >= L'0' && instance[i] <= L'9') || (instance[i] >= L'A' && instance[i] <= L'F') || (instance[i] >= L'a' && instance[i] <= L'f'))) return E_ACCESSDENIED;

            const GUID media = {0x4d36e96c,0xe325,0x11ce,{0xbf,0xc1,0x08,0x00,0x2b,0xe1,0x03,0x18}};
            Devices devices; devices.value = SetupDiCreateDeviceInfoList(&media, nullptr);
            if (devices.value == INVALID_HANDLE_VALUE) return HRESULT_FROM_WIN32(GetLastError());
            SP_DEVINFO_DATA device{}; device.cbSize = sizeof(device);
            if (!SetupDiOpenDeviceInfoW(devices.value, instance.c_str(), nullptr, 0, &device) || device.ClassGuid != media) return E_ACCESSDENIED;
            wchar_t hardware[256]{}; DWORD hardwareType = 0, hardwareBytes = 0;
            if (!SetupDiGetDeviceRegistryPropertyW(devices.value, &device, SPDRP_HARDWAREID, &hardwareType,
                reinterpret_cast<BYTE*>(hardware), sizeof(hardware), &hardwareBytes) || hardwareType != REG_MULTI_SZ ||
                hardwareBytes < 2 * sizeof(wchar_t) || hardwareBytes > sizeof(hardware) || hardwareBytes % sizeof(wchar_t)) return E_ACCESSDENIED;
            const std::size_t characters = hardwareBytes / sizeof(wchar_t);
            if (hardware[characters - 1] || hardware[characters - 2]) return E_ACCESSDENIED;
            bool cable = false;
            for (std::size_t at = 0; at < characters && hardware[at]; )
            {
                const std::size_t length = wcsnlen_s(hardware + at, characters - at);
                if (length == characters - at) return E_ACCESSDENIED;
                if (!_wcsicmp(hardware + at, L"VBAudioVACWDM")) cable = true;
                at += length + 1;
            }
            if (!cable) return E_ACCESSDENIED;
            ULONG flags = 0, problem = 0;
            if (CM_Get_DevNode_Status(&flags, &problem, device.DevInst, 0) != CR_SUCCESS || !(flags & DN_STARTED) || problem) return E_ACCESSDENIED;
            auto property = [&](const DEVPROPKEY& propertyKey, const wchar_t* expected) {
                wchar_t text[256]{}; DWORD bytes = 0; DEVPROPTYPE type = 0;
                return SetupDiGetDevicePropertyW(devices.value, &device, &propertyKey, &type,
                    reinterpret_cast<BYTE*>(text), sizeof(text), &bytes, 0) && type == DEVPROP_TYPE_STRING &&
                    bytes >= sizeof(wchar_t) && bytes <= sizeof(text) && bytes % sizeof(wchar_t) == 0 &&
                    wcsnlen_s(text, 256) == bytes / sizeof(wchar_t) - 1 && !_wcsicmp(text, expected);
            };
            if (!property(DEVPKEY_Device_DriverProvider, L"VB-Audio Software") ||
                !property(DEVPKEY_Device_DriverVersion, L"3.5.2.0")) return E_ACCESSDENIED;
            return S_OK;
        }

        HRESULT OwnRender(IMMDeviceEnumerator* enumerator, IMMDevice* device, const std::wstring& instance)
        {
            ComPtr<IDeviceTopology> topology; ComPtr<IConnector> connector; ComPtr<IMMDevice> adapter; Text id;
            UINT count = 0;
            HRESULT hr = device->Activate(__uuidof(IDeviceTopology), CLSCTX_INPROC_SERVER, nullptr, reinterpret_cast<void**>(topology.GetAddressOf()));
            if (SUCCEEDED(hr)) hr = topology->GetConnectorCount(&count);
            if (FAILED(hr) || count != 1) return S_FALSE; // Unrelated endpoint, never selected by name.
            hr = topology->GetConnector(0, &connector);
            if (SUCCEEDED(hr)) hr = connector->GetDeviceIdConnectedTo(&id.value);
            if (SUCCEEDED(hr)) hr = enumerator->GetDevice(id.value, &adapter);
            if (FAILED(hr)) return S_FALSE;
            ComPtr<IPropertyStore> properties; PROPVARIANT value{};
            hr = adapter->OpenPropertyStore(STGM_READ, &properties);
            if (SUCCEEDED(hr)) hr = properties->GetValue(PKEY_Device_InstanceId, &value);
            const bool own = SUCCEEDED(hr) && value.vt == VT_LPWSTR && value.pwszVal && !_wcsicmp(value.pwszVal, instance.c_str());
            PropVariantClear(&value); if (!own) return S_FALSE;
            constexpr PROPERTYKEY neverDefault = {{0xf3e80bef,0x1723,0x4ff2,{0xbc,0xc4,0x7f,0x83,0xdc,0x5e,0x46,0xd4}},3};
            constexpr PROPERTYKEY form = {{0x1da5d803,0xd492,0x4edd,{0x8c,0x23,0xe0,0xc0,0xff,0xee,0x7f,0x0e}},0};
            properties.Reset(); hr = device->OpenPropertyStore(STGM_READ, &properties);
            if (SUCCEEDED(hr)) hr = properties->GetValue(neverDefault, &value);
            const bool policy = SUCCEEDED(hr) && value.vt == VT_UI4 && value.ulVal == 0x307;
            PropVariantClear(&value); if (!policy) return E_ACCESSDENIED;
            hr = properties->GetValue(form, &value);
            const bool speaker = SUCCEEDED(hr) && value.vt == VT_UI4 && value.ulVal == 1;
            PropVariantClear(&value); return FAILED(hr) ? hr : speaker ? S_OK : S_FALSE;
        }
    }

    HRESULT AudioRender::Fail(HRESULT reason) noexcept
    {
        if (!retired_.exchange(true))
        {
            if (stop_) SetEvent(stop_);
            if (owner_.retired) owner_.retired(owner_.context, reason);
        }
        return reason;
    }
    void AudioRender::Stop() noexcept { Fail(MF_E_SHUTDOWN); }
    HRESULT AudioRender::Check(bool requireSend) noexcept
    {
        if (IsRetired()) return MF_E_SHUTDOWN;
        HRESULT hr = owner_.current(owner_.context);
        if (hr != S_OK) return Fail(FAILED(hr) ? hr : E_ACCESSDENIED);
        if (requireSend)
        {
            hr = owner_.sending(owner_.context);
            if (hr != S_OK) return Fail(FAILED(hr) ? hr : E_ACCESSDENIED);
        }
        if (SUCCEEDED(hr) && control_) hr = control_->RequireCurrent();
        if (FAILED(hr)) return Fail(hr);
        return IsRetired() ? MF_E_SHUTDOWN : S_OK;
    }
    LONGLONG AudioRender::Now() const noexcept
    { return owner_.nowUs ? owner_.nowUs(owner_.context) : MFGetSystemTime() / 10; }

    HRESULT AudioRender::AdmitParent(PipeReader* control) noexcept
    {
        if (!control || control->IsRetired()) return E_ACCESSDENIED;
        HRESULT hr = control->RequireCurrent(); if (FAILED(hr)) return hr;
        const DWORD original = GetProcessId(control->server_);
        const DWORD self = GetCurrentProcessId();
        if (!original || original == self) return E_ACCESSDENIED;
        HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if (snapshot == INVALID_HANDLE_VALUE) return HRESULT_FROM_WIN32(GetLastError());
        PROCESSENTRY32W entry{}; entry.dwSize = sizeof(entry); bool matched = false;
        if (Process32FirstW(snapshot, &entry)) do
        {
            if (entry.th32ProcessID == self) { matched = entry.th32ParentProcessID == original; break; }
        } while (Process32NextW(snapshot, &entry));
        CloseHandle(snapshot);
        return matched ? control->RequireCurrent() : E_ACCESSDENIED;
    }

    HRESULT AudioRender::Open(OutputLease* lease, std::unique_ptr<AudioRender>& result) noexcept
    {
        if (result || !lease) return E_INVALIDARG;
        try
        {
            const ClockOwner owner = lease->Callbacks();
            PipeReader* const control = lease->Control();
            std::unique_ptr<AudioRender> output(new AudioRender(owner));
            // The original joined session prepares outputs BEFORE publishing
            // SEND. Require its actual current capture context here, but never
            // Start/write before its separate sending callback succeeds.
            HRESULT hr = output->Check(false);
            if (FAILED(hr)) return hr;
            hr = AdmitParent(control);
            if (FAILED(hr)) return output->Fail(hr);
            output->control_ = control;
            hr = output->Initialize();
            if (FAILED(hr)) return output->Fail(hr);
            result = std::move(output); return S_OK;
        }
        catch (...) { return E_OUTOFMEMORY; }
    }

    HRESULT AudioRender::Initialize() noexcept
    {
        try
        {
            stop_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            ready_ = CreateEventW(nullptr, FALSE, FALSE, nullptr);
            if (!stop_ || !ready_) return HRESULT_FROM_WIN32(GetLastError());
            std::wstring instance; HRESULT hr = OwnInstance(instance);
            if (FAILED(hr)) return hr;
            ComPtr<IMMDeviceEnumerator> enumerator; ComPtr<IMMDeviceCollection> endpoints; ComPtr<IMMDevice> selected;
            hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&enumerator));
            if (SUCCEEDED(hr)) hr = enumerator->EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE, &endpoints);
            UINT count = 0, matches = 0;
            if (SUCCEEDED(hr)) hr = endpoints->GetCount(&count);
            if (FAILED(hr)) return hr;
            if (count > 256) return E_INVALIDARG;
            for (UINT i = 0; i < count; ++i)
            {
                hr = Check(false); if (FAILED(hr)) return hr;
                ComPtr<IMMDevice> candidate; hr = endpoints->Item(i, &candidate); if (FAILED(hr)) return hr;
                hr = OwnRender(enumerator.Get(), candidate.Get(), instance);
                if (FAILED(hr)) return hr;
                if (hr == S_OK) { selected = candidate; ++matches; }
            }
            if (matches != 1) return E_ACCESSDENIED;
            hr = Check(false); if (FAILED(hr)) return hr;
            hr = selected->Activate(__uuidof(IAudioClient), CLSCTX_INPROC_SERVER, nullptr, reinterpret_cast<void**>(client_.GetAddressOf()));
            if (FAILED(hr)) return hr;
            ComPtr<IAudioClient2> properties; hr = client_.As(&properties);
            AudioClientProperties options{}; options.cbSize = sizeof(options); options.eCategory = AudioCategory_Other;
            options.bIsOffload = FALSE; options.Options = AUDCLNT_STREAMOPTIONS_RAW;
            if (SUCCEEDED(hr)) hr = properties->SetClientProperties(&options);
            Format format; if (SUCCEEDED(hr)) hr = client_->GetMixFormat(&format.value);
            if (FAILED(hr)) return hr;
            const auto wave = format.value;
            const GUID floating = {3,0,0x10,{0x80,0,0,0xaa,0,0x38,0x9b,0x71}};
            if (!wave || wave->wFormatTag != WAVE_FORMAT_EXTENSIBLE || wave->cbSize != 22 || wave->nChannels != 2 ||
                wave->nSamplesPerSec != 48000 || wave->wBitsPerSample != 32 || wave->nBlockAlign != 8 || wave->nAvgBytesPerSec != 384000)
                return AUDCLNT_E_UNSUPPORTED_FORMAT;
            const auto extended = reinterpret_cast<const WAVEFORMATEXTENSIBLE*>(wave);
            if (extended->SubFormat != floating || extended->Samples.wValidBitsPerSample != 32 || extended->dwChannelMask != 3)
                return AUDCLNT_E_UNSUPPORTED_FORMAT;
            GUID session{}; hr = CoCreateGuid(&session);
            if (SUCCEEDED(hr)) hr = Check(false);
            if (SUCCEEDED(hr)) hr = client_->Initialize(AUDCLNT_SHAREMODE_SHARED,
                AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_NOPERSIST, 1000000, 0, wave, &session);
            if (SUCCEEDED(hr)) hr = client_->SetEventHandle(ready_);
            if (SUCCEEDED(hr)) hr = client_->GetBufferSize(&capacity_);
            if (FAILED(hr)) return hr;
            if (capacity_ < 960 || capacity_ > 4800) return E_INVALIDARG;
            hr = client_->GetService(IID_PPV_ARGS(&writer_));
            return FAILED(hr) ? hr : Check(false);
        }
        catch (...) { return E_OUTOFMEMORY; }
    }

    HRESULT AudioRender::Write(IMFSample* sample, LONGLONG nativePtsUs) noexcept
    {
        try
        {
            std::unique_lock<std::mutex> lock(gate_, std::try_to_lock);
            if (!lock.owns_lock()) return Fail(HRESULT_FROM_WIN32(ERROR_BUSY));
            const ULONGLONG deadline = GetTickCount64() + 250;
            HRESULT hr = Check(); if (FAILED(hr)) return hr;
            if (!sample || nativePtsUs < 0) return Fail(E_INVALIDARG);
            LONGLONG pts = -1, duration = -1; DWORD count = 0;
            hr = sample->GetSampleTime(&pts);
            if (SUCCEEDED(hr)) hr = sample->GetSampleDuration(&duration);
            if (SUCCEEDED(hr)) hr = sample->GetBufferCount(&count);
            if (FAILED(hr)) return Fail(hr);
            if (pts < 0 || pts > 90071992547409910LL || pts % 10 || duration != 200000 || count != 1) return Fail(E_INVALIDARG);
            ComPtr<IMFMediaBuffer> source; hr = sample->GetBufferByIndex(0, &source);
            if (FAILED(hr)) return Fail(hr);
            std::array<BYTE, Samples::AudioBytes> pcm{};
            struct Clear { BYTE* bytes; std::size_t size; ~Clear() { SecureZeroMemory(bytes, size); } } clear{pcm.data(), pcm.size()};
            BYTE* bytes = nullptr; DWORD capacity = 0, size = 0;
            hr = source->Lock(&bytes, &capacity, &size); if (FAILED(hr)) return Fail(hr);
            hr = Check();
            if (SUCCEEDED(hr) && (!bytes || size != pcm.size() || capacity < size)) hr = E_INVALIDARG;
            if (SUCCEEDED(hr)) std::memcpy(pcm.data(), bytes, pcm.size());
            const HRESULT unlocked = source->Unlock();
            if (FAILED(hr)) return Fail(hr);
            if (FAILED(unlocked)) return Fail(unlocked);
            auto timely = [&]() noexcept -> HRESULT {
                const LONGLONG now = Now();
                if (now < 0 || now < lastNow_) return Fail(E_INVALIDARG);
                lastNow_ = now;
                const LONGLONG remaining = nativePtsUs - now;
                if (remaining < -250000 || remaining > 250000 || GetTickCount64() >= deadline)
                    return Fail(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
                return S_OK;
            };
            for (;;)
            {
                hr = Check(); if (FAILED(hr)) return hr;
                const LONGLONG now = Now();
                if (now < 0 || now < lastNow_) return Fail(E_INVALIDARG);
                lastNow_ = now;
                const LONGLONG remaining = nativePtsUs - now;
                if (remaining < -250000 || remaining > 250000) return Fail(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
                if (GetTickCount64() >= deadline) return Fail(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
                if (remaining > 0)
                {
                    const DWORD wait = WaitForSingleObject(stop_, static_cast<DWORD>((std::min)(10LL, (remaining + 999) / 1000)));
                    if (wait == WAIT_OBJECT_0) return Fail(MF_E_SHUTDOWN);
                    if (wait == WAIT_FAILED) return Fail(HRESULT_FROM_WIN32(GetLastError()));
                    continue;
                }
                UINT32 padding = 0; hr = client_->GetCurrentPadding(&padding);
                if (FAILED(hr)) return Fail(hr);
                hr = timely(); if (FAILED(hr)) return hr;
                if (padding > capacity_) return Fail(E_UNEXPECTED);
                if (capacity_ - padding < 960)
                {
                    const HANDLE events[] = {stop_, ready_};
                    const DWORD wait = WaitForMultipleObjects(2, events, FALSE, 10);
                    if (wait == WAIT_OBJECT_0) return Fail(MF_E_SHUTDOWN);
                    if (wait == WAIT_FAILED) return Fail(HRESULT_FROM_WIN32(GetLastError()));
                    continue;
                }
                hr = Check(); if (FAILED(hr)) return hr;
                BYTE* target = nullptr; hr = writer_->GetBuffer(960, &target);
                if (FAILED(hr)) return Fail(hr);
                hr = Check();
                if (SUCCEEDED(hr)) hr = timely();
                if (SUCCEEDED(hr) && !target) hr = E_POINTER;
                if (SUCCEEDED(hr))
                {
                    auto output = reinterpret_cast<float*>(target);
                    for (std::size_t i = 0; i < 960; ++i)
                    {
                        const unsigned int raw = pcm[2 * i] | (static_cast<unsigned int>(pcm[2 * i + 1]) << 8);
                        const int signedValue = raw >= 32768 ? static_cast<int>(raw) - 65536 : static_cast<int>(raw);
                        const float value = static_cast<float>(signedValue) / 32768.0f;
                        output[2 * i] = value; output[2 * i + 1] = value;
                    }
                    hr = Check();
                    if (SUCCEEDED(hr)) hr = timely();
                }
                if (FAILED(hr))
                {
                    if (target) SecureZeroMemory(target, 960 * 2 * sizeof(float));
                    writer_->ReleaseBuffer(960, AUDCLNT_BUFFERFLAGS_SILENT);
                    return Fail(hr);
                }
                hr = writer_->ReleaseBuffer(960, 0);
                if (FAILED(hr)) return Fail(hr);
                hr = Check(); if (FAILED(hr)) return hr;
                hr = timely(); if (FAILED(hr)) return hr;
                if (!started_)
                {
                    hr = client_->Start(); if (FAILED(hr)) return Fail(hr);
                    started_ = true;
                }
                hr = Check(); return FAILED(hr) ? hr : timely();
            }
        }
        catch (...) { return Fail(E_FAIL); }
    }

    AudioRender::~AudioRender()
    {
        Stop();
        // Original controller first signals and joins this isolated worker.
        // If the service hangs here, its external child-process guardian owns timeout.
        std::lock_guard<std::mutex> lock(gate_);
        if (client_) { if (started_) client_->Stop(); client_->Reset(); }
        writer_.Reset(); client_.Reset();
        if (ready_) CloseHandle(ready_);
        if (stop_) CloseHandle(stop_);
    }
}
