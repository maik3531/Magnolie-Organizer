#include "PhoneCameraCableSetup.h"
#include <setupapi.h>
#include <newdev.h>
#include <cfgmgr32.h>
#include <sddl.h>
#include <aclapi.h>
#include <shlobj.h>
#include <cwchar>
#include <cstring>
#include <regstr.h>
#include <mmdeviceapi.h>
#include <wrl/client.h>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        constexpr GUID MediaClass = {0x4d36e96c,0xe325,0x11ce,{0xbf,0xc1,0x08,0x00,0x2b,0xe1,0x03,0x18}};
        constexpr wchar_t HardwareId[] = L"VBAudioVACWDM";
        constexpr wchar_t Journal[] = L"SOFTWARE\\Magnolie Organizer\\WebcamDriver\\VB-CABLE-Pack46";
        constexpr wchar_t Marker[] = L"Magnolie VB-CABLE Pack46 setup v1";
        constexpr ULONGLONG Version = (3ULL<<48)|(5ULL<<32)|(2ULL<<16);
        constexpr GUID AudioCategory = {0x6994ad04,0x93ef,0x11d0,{0xa3,0xcc,0x00,0xa0,0xc9,0x22,0x31,0x96}};
        constexpr GUID TopologyCategory = {0xdda54a40,0x1e4c,0x11d1,{0xa0,0x50,0x40,0x57,0x05,0xc1,0x00,0x00}};
        struct Devices { HDEVINFO value = INVALID_HANDLE_VALUE; ~Devices(){ if(value!=INVALID_HANDLE_VALUE) SetupDiDestroyDeviceInfoList(value); } };
        struct Handle { HANDLE value = nullptr; ~Handle(){ if(value && value!=INVALID_HANDLE_VALUE) CloseHandle(value); } };
        struct Key { HKEY value = nullptr; ~Key(){ if(value) RegCloseKey(value); } };
        struct Local { void* value = nullptr; ~Local(){ if(value) LocalFree(value); } };
        struct ComMemory { wchar_t* value = nullptr; ~ComMemory(){ if(value) CoTaskMemFree(value); } };
        HRESULT LastError() noexcept { return HRESULT_FROM_WIN32(GetLastError()); }
        struct ComApartment
        {
            HRESULT status=CoInitializeEx(nullptr,COINIT_MULTITHREADED);
            ~ComApartment(){if(SUCCEEDED(status)) CoUninitialize();}
        };
        HRESULT AudioDefaults(std::array<std::wstring,6>& result)
        {
            ComApartment com;
            if(FAILED(com.status) && com.status!=RPC_E_CHANGED_MODE) return com.status;
            Microsoft::WRL::ComPtr<IMMDeviceEnumerator> devices;
            HRESULT hr=CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&devices));
            if(FAILED(hr)) return hr;
            std::size_t at=0;
            for(EDataFlow flow:{eRender,eCapture}) for(ERole role:{eConsole,eMultimedia,eCommunications})
            {
                Microsoft::WRL::ComPtr<IMMDevice> endpoint;
                hr=devices->GetDefaultAudioEndpoint(flow,role,&endpoint);
                if(hr==HRESULT_FROM_WIN32(ERROR_NOT_FOUND)){result[at++].clear();continue;}
                if(FAILED(hr)) return hr;
                ComMemory id;
                hr=endpoint->GetId(&id.value);
                if(FAILED(hr)) return hr;
                result[at++]=id.value;
            }
            return S_OK; // Metadata only: never Activate/IAudioClient/capture.
        }
        HRESULT ConfigureOwnAppScopedInterfaces(HDEVINFO devices,SP_DEVINFO_DATA& device,const std::wstring& infPath,bool verifyOnly=false)
        {
            struct Inf {HINF value=INVALID_HANDLE_VALUE;~Inf(){if(value!=INVALID_HANDLE_VALUE) SetupCloseInfFile(value);}} inf;
            inf.value=SetupOpenInfFileW(infPath.c_str(),nullptr,INF_STYLE_WIN4,nullptr);
            if(inf.value==INVALID_HANDLE_VALUE) return LastError();
            for(const wchar_t* name:{L"REFERENCESTRING_TopoRender1",L"REFERENCESTRING_TopoCapture1"})
            {
                INFCONTEXT context{};wchar_t reference[256]{};DWORD required=0;
                if(!SetupFindFirstLineW(inf.value,L"Strings",name,&context) || !SetupGetStringFieldW(&context,1,reference,256,&required)) return LastError();
                if(required<2 || required>256 || std::wcschr(reference,L'\\') || std::wcschr(reference,L'/')) return E_INVALIDARG;
                for(const GUID category:{AudioCategory,TopologyCategory})
                {
                    SP_DEVICE_INTERFACE_DATA interfaceData{};interfaceData.cbSize=sizeof(interfaceData);
                    if(!SetupDiCreateDeviceInterfaceW(devices,&device,&category,reference,0,&interfaceData)) return LastError();
                    Key interfaceKey;
                    interfaceKey.value=verifyOnly ? SetupDiOpenDeviceInterfaceRegKey(devices,&interfaceData,0,KEY_READ) :
                        SetupDiCreateDeviceInterfaceRegKeyW(devices,&interfaceData,0,KEY_READ|KEY_WRITE,nullptr,nullptr);
                    if(interfaceKey.value==INVALID_HANDLE_VALUE){interfaceKey.value=nullptr;return LastError();}
                    Key endpoint;
                    const LSTATUS opened=verifyOnly ? RegOpenKeyExW(interfaceKey.value,L"EP\\0",0,KEY_READ,&endpoint.value) :
                        RegCreateKeyExW(interfaceKey.value,L"EP\\0",0,nullptr,REG_OPTION_NON_VOLATILE,KEY_READ|KEY_WRITE,nullptr,&endpoint.value,nullptr);
                    if(opened!=ERROR_SUCCESS) return HRESULT_FROM_WIN32(opened);
                    constexpr wchar_t association[]=L"{00000000-0000-0000-0000-000000000000}";
                    constexpr DWORD mask=0x00000307; // All roles/flows, own app-specific endpoints only.
                    if(!verifyOnly)
                    {
                        LSTATUS status=RegSetValueExW(endpoint.value,L"{1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E},2",0,REG_SZ,
                            reinterpret_cast<const BYTE*>(association),sizeof(association));
                        if(status==ERROR_SUCCESS) status=RegSetValueExW(endpoint.value,L"{F3E80BEF-1723-4FF2-BCC4-7F83DC5E46D4},3",0,REG_DWORD,
                            reinterpret_cast<const BYTE*>(&mask),sizeof(mask));
                        if(status==ERROR_SUCCESS) status=RegFlushKey(endpoint.value);
                        if(status!=ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
                    }
                    wchar_t actualAssociation[40]{};DWORD actualMask=0,size=sizeof(actualAssociation);
                    LSTATUS status=RegGetValueW(endpoint.value,nullptr,L"{1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E},2",RRF_RT_REG_SZ,nullptr,actualAssociation,&size);
                    if(status!=ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
                    if(size!=sizeof(association) || std::wcscmp(actualAssociation,association)) return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
                    size=sizeof(actualMask);
                    status=RegGetValueW(endpoint.value,nullptr,L"{F3E80BEF-1723-4FF2-BCC4-7F83DC5E46D4},3",RRF_RT_REG_DWORD,nullptr,&actualMask,&size);
                    if(status!=ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
                    if(size!=sizeof(actualMask) || actualMask!=mask) return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
                }
            }
            // Original signed INF/catalog bytes stay untouched. Only this newly
            // owned disabled devnode's interfaces receive documented policy.
            // UI must disclose explicit per-app selection, not system default use.
            return S_OK;
        }
        bool Elevated() noexcept
        {
            Handle token;
            if(!OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&token.value)) return false;
            TOKEN_ELEVATION elevation{}; DWORD size=0;
            return GetTokenInformation(token.value,TokenElevation,&elevation,sizeof(elevation),&size) && elevation.TokenIsElevated;
        }
        bool Supported() noexcept
        {
            USHORT process=0,native=0;
            if(!IsWow64Process2(GetCurrentProcess(),&process,&native) || process!=IMAGE_FILE_MACHINE_UNKNOWN ||
                (native!=IMAGE_FILE_MACHINE_AMD64 && native!=IMAGE_FILE_MACHINE_ARM64)) return false;
            using VersionFn = LONG (WINAPI*)(OSVERSIONINFOW*);
            FARPROC address=GetProcAddress(GetModuleHandleW(L"ntdll.dll"),"RtlGetVersion");
            VersionFn version=nullptr; static_assert(sizeof(version)==sizeof(address)); std::memcpy(&version,&address,sizeof(version));
            OSVERSIONINFOW info{}; info.dwOSVersionInfoSize=sizeof(info);
            return version && version(&info)>=0 && info.dwMajorVersion>=10 && info.dwBuildNumber>=22000;
        }
        HRESULT ExistingDevices(std::vector<std::wstring>& result)
        {
            Devices devices; devices.value=SetupDiGetClassDevsW(&MediaClass,nullptr,nullptr,0); // Includes pending/non-present devices.
            if(devices.value==INVALID_HANDLE_VALUE) return LastError();
            SP_DEVINFO_DATA device{}; device.cbSize=sizeof(device);
            for(DWORD index=0;SetupDiEnumDeviceInfo(devices.value,index,&device);++index)
            {
                DWORD type=0,bytes=0;
                if(!SetupDiGetDeviceRegistryPropertyW(devices.value,&device,SPDRP_HARDWAREID,&type,nullptr,0,&bytes))
                {
                    const DWORD error=GetLastError();
                    if(error==ERROR_INVALID_DATA) continue;
                    if(error!=ERROR_INSUFFICIENT_BUFFER) return HRESULT_FROM_WIN32(error);
                }
                if(type!=REG_MULTI_SZ || bytes<2*sizeof(wchar_t) || bytes>65536 || bytes%sizeof(wchar_t)) return E_INVALIDARG;
                std::vector<wchar_t> ids(bytes/sizeof(wchar_t));
                if(!SetupDiGetDeviceRegistryPropertyW(devices.value,&device,SPDRP_HARDWAREID,&type,
                    reinterpret_cast<BYTE*>(ids.data()),bytes,&bytes)) return LastError();
                if(type!=REG_MULTI_SZ || bytes<2*sizeof(wchar_t) || bytes%sizeof(wchar_t) || bytes/sizeof(wchar_t)>ids.size()) return E_INVALIDARG;
                ids.resize(bytes/sizeof(wchar_t));
                if(ids.back()!=L'\0' || ids[ids.size()-2]!=L'\0') return E_INVALIDARG;
                bool found=false;
                for(std::size_t at=0;at+1<ids.size() && ids[at];)
                {
                    if(!_wcsicmp(ids.data()+at,HardwareId)) found=true;
                    at+=std::wcslen(ids.data()+at)+1;
                }
                if(found)
                {
                    wchar_t instance[MAX_DEVICE_ID_LEN]{};
                    if(!SetupDiGetDeviceInstanceIdW(devices.value,&device,instance,MAX_DEVICE_ID_LEN,nullptr)) return LastError();
                    result.emplace_back(instance);
                }
            }
            return GetLastError()==ERROR_NO_MORE_ITEMS ? S_OK : LastError();
        }
        bool ProtectedAcl(const std::wstring& path, bool baseDirectory)
        {
            Local descriptor; PSID owner=nullptr; PACL dacl=nullptr;
            if(GetNamedSecurityInfoW(path.c_str(),SE_FILE_OBJECT,OWNER_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION,
                &owner,nullptr,&dacl,nullptr,reinterpret_cast<PSECURITY_DESCRIPTOR*>(&descriptor.value))!=ERROR_SUCCESS || !owner || !dacl) return false;
            BYTE admin[SECURITY_MAX_SID_SIZE]{},system[SECURITY_MAX_SID_SIZE]{}; DWORD adminBytes=sizeof(admin),systemBytes=sizeof(system);
            if(!CreateWellKnownSid(WinBuiltinAdministratorsSid,nullptr,admin,&adminBytes) ||
                !CreateWellKnownSid(WinLocalSystemSid,nullptr,system,&systemBytes)) return false;
            if(!EqualSid(owner,admin) && !EqualSid(owner,system)) return false;
            const DWORD dangerous=baseDirectory ? (FILE_DELETE_CHILD|DELETE|WRITE_DAC|WRITE_OWNER|GENERIC_ALL) :
                (FILE_WRITE_DATA|FILE_APPEND_DATA|FILE_WRITE_EA|FILE_WRITE_ATTRIBUTES|FILE_DELETE_CHILD|DELETE|WRITE_DAC|WRITE_OWNER|GENERIC_WRITE|GENERIC_ALL);
            for(DWORD i=0;i<dacl->AceCount;++i)
            {
                void* opaque=nullptr; if(!GetAce(dacl,i,&opaque)) return false;
                auto* header=static_cast<ACE_HEADER*>(opaque);
                if(header->AceFlags & INHERIT_ONLY_ACE) continue;
                if(header->AceType==ACCESS_DENIED_ACE_TYPE || header->AceType==SYSTEM_AUDIT_ACE_TYPE) continue;
                if(header->AceType!=ACCESS_ALLOWED_ACE_TYPE) return false;
                auto* ace=static_cast<ACCESS_ALLOWED_ACE*>(opaque);
                auto* sid=reinterpret_cast<PSID>(&ace->SidStart);
                if((ace->Mask & dangerous) && !EqualSid(sid,admin) && !EqualSid(sid,system)) return false;
            }
            return true;
        }
        bool ProtectedPackage(const CablePackage& package)
        {
            ComMemory programData;
            if(FAILED(SHGetKnownFolderPath(FOLDERID_ProgramData,KF_FLAG_DEFAULT,nullptr,&programData.value))) return false;
            const std::wstring base=programData.value, root=base+L"\\Magnolie-Webcam-Driver-Setup";
            const auto& directory=package.Directory(); const auto prefix=root+L"\\";
            if(directory.size()!=prefix.size()+38 || _wcsnicmp(directory.c_str(),prefix.c_str(),prefix.size())) return false;
            const auto leaf=directory.substr(prefix.size()); GUID id{};
            if(leaf.front()!=L'{' || leaf.back()!=L'}' || FAILED(CLSIDFromString(leaf.c_str(),&id)) || id==GUID_NULL) return false;
            for(const auto& path : {base,root,directory})
            {
                const DWORD flags=GetFileAttributesW(path.c_str());
                if(flags==INVALID_FILE_ATTRIBUTES || !(flags & FILE_ATTRIBUTE_DIRECTORY) || (flags & FILE_ATTRIBUTE_REPARSE_POINT) ||
                    !ProtectedAcl(path,path==base)) return false;
            }
            for(std::size_t i=0;i<4;++i) if(!ProtectedAcl(directory+L"\\"+CablePackage::Filename(i),false)) return false;
            return true;
        }
        DWORD Put(HKEY key,const wchar_t* name,const std::wstring& value) noexcept
        { return static_cast<DWORD>(RegSetValueExW(key,name,0,REG_SZ,reinterpret_cast<const BYTE*>(value.c_str()),static_cast<DWORD>((value.size()+1)*sizeof(wchar_t)))); }
        DWORD PutState(HKEY key,const wchar_t* value,DWORD error) noexcept
        {
            DWORD status=Put(key,L"State",value);
            if(status==ERROR_SUCCESS) status=static_cast<DWORD>(RegSetValueExW(key,L"Error",0,REG_DWORD,reinterpret_cast<const BYTE*>(&error),sizeof(error)));
            if(status==ERROR_SUCCESS) status=static_cast<DWORD>(RegFlushKey(key));
            return status;
        }
    }
    HRESULT PlanCableSetup(const CablePackage& package,CableSetupPlan& result) noexcept
    {
        try
        {
            result={}; result.supportedHost=Supported(); result.elevated=Elevated(); result.protectedPackage=ProtectedPackage(package);
            std::array<std::wstring,6> defaults;
            result.canInspectAudioDefaults=SUCCEEDED(AudioDefaults(defaults));
            Key journal; const LSTATUS status=RegOpenKeyExW(HKEY_LOCAL_MACHINE,Journal,0,KEY_READ,&journal.value);
            if(status!=ERROR_SUCCESS && status!=ERROR_FILE_NOT_FOUND) return HRESULT_FROM_WIN32(status);
            result.existingTransaction=status==ERROR_SUCCESS;
            return ExistingDevices(result.existingDevices);
        }
        catch(...) { return E_OUTOFMEMORY; }
    }
    CableSetupResult InstallCable(const CablePackage& package) noexcept
    {
        CableSetupResult result;
        try
        {
            CableSetupPlan plan; HRESULT hr=PlanCableSetup(package,plan);
            if(FAILED(hr)) {result.error=static_cast<DWORD>(hr);return result;}
            if(!plan.supportedHost){result.state=CableSetupState::Unsupported;result.error=ERROR_NOT_SUPPORTED;return result;}
            if(!plan.elevated){result.state=CableSetupState::AdministratorRequired;result.error=ERROR_ELEVATION_REQUIRED;return result;}
            if(!plan.protectedPackage){result.state=CableSetupState::UnprotectedPackage;result.error=ERROR_ACCESS_DENIED;return result;}
            if(!plan.canInspectAudioDefaults){result.state=CableSetupState::Unsupported;result.error=ERROR_NOT_SUPPORTED;return result;}
            if(!plan.existingDevices.empty()){result.state=CableSetupState::ExistingDevice;result.error=ERROR_ALREADY_EXISTS;return result;}
            if(plan.existingTransaction){result.state=CableSetupState::ExistingTransaction;result.error=ERROR_ALREADY_EXISTS;return result;}
            std::array<std::wstring,6> originalDefaults;
            hr=AudioDefaults(originalDefaults);
            if(FAILED(hr)){result.error=static_cast<DWORD>(hr);return result;}
            Local security;
            if(!ConvertStringSecurityDescriptorToSecurityDescriptorW(L"O:BAG:BAD:P(A;CI;KA;;;SY)(A;CI;KA;;;BA)(A;CI;KR;;;BU)",
                SDDL_REVISION_1,reinterpret_cast<PSECURITY_DESCRIPTOR*>(&security.value),nullptr)) {result.error=GetLastError();return result;}
            SECURITY_ATTRIBUTES attributes{sizeof(attributes),security.value,FALSE}; Key journal; DWORD created=0;
            LSTATUS status=RegCreateKeyExW(HKEY_LOCAL_MACHINE,Journal,0,nullptr,REG_OPTION_NON_VOLATILE,KEY_ALL_ACCESS,&attributes,&journal.value,&created);
            if(status!=ERROR_SUCCESS){result.error=static_cast<DWORD>(status);return result;}
            if(created!=REG_CREATED_NEW_KEY){result.state=CableSetupState::ExistingTransaction;result.error=ERROR_ALREADY_EXISTS;return result;}
            if(Put(journal.value,L"ScopeMarker",Marker)!=ERROR_SUCCESS || PutState(journal.value,L"in_progress",ERROR_SUCCESS)!=ERROR_SUCCESS)
            {result.state=CableSetupState::UnknownPending;result.error=ERROR_WRITE_FAULT;return result;}
            // The durable collision-refusing journal is established BEFORE any
            // driver-store or PnP mutation. It is never erased to permit retries.
            Devices deviceSet; SP_DEVINFO_DATA device{}; device.cbSize=sizeof(device);
            bool registered=false; BOOL needReboot=FALSE;
            auto fail=[&](DWORD error)
            {
                result.error=error; result.state=CableSetupState::Failed;
                if(registered)
                {
                    BOOL cleanupReboot=FALSE;
                    if(DiUninstallDevice(nullptr,deviceSet.value,&device,0,&cleanupReboot)) result.ownDeviceRemoved=true;
                    else result.state=CableSetupState::CleanupPending;
                    result.rebootRequired=needReboot || cleanupReboot;
                }
                if(PutState(journal.value,result.state==CableSetupState::CleanupPending ? L"cleanup_pending" : L"failed",error)!=ERROR_SUCCESS)
                    result.state=CableSetupState::UnknownPending;
            };
            const auto inf=package.Directory()+L"\\"+CablePackage::Filename(0);
            wchar_t copied[MAX_PATH]{};
            if(!SetupCopyOEMInfW(inf.c_str(),package.Directory().c_str(),SPOST_PATH,SP_COPY_NOOVERWRITE,copied,MAX_PATH,nullptr,nullptr) && GetLastError()!=ERROR_FILE_EXISTS)
            {fail(GetLastError());return result;}
            // Never use UpdateDriverForPlugAndPlayDevices: that would update
            // every matching foreign device rather than our exact new devnode.
            deviceSet.value=SetupDiCreateDeviceInfoList(&MediaClass,nullptr);
            if(deviceSet.value==INVALID_HANDLE_VALUE){fail(GetLastError());return result;}
            if(!SetupDiCreateDeviceInfoW(deviceSet.value,L"MEDIA",&MediaClass,L"VB-Audio Virtual Cable",nullptr,DICD_GENERATE_ID,&device))
            {fail(GetLastError());return result;}
            constexpr wchar_t ids[]=L"VBAudioVACWDM\0";
            if(!SetupDiSetDeviceRegistryPropertyW(deviceSet.value,&device,SPDRP_HARDWAREID,reinterpret_cast<const BYTE*>(ids),sizeof(ids)))
            {fail(GetLastError());return result;}
            constexpr DWORD disabled=CONFIGFLAG_DISABLED;
            if(!SetupDiSetDeviceRegistryPropertyW(deviceSet.value,&device,SPDRP_CONFIGFLAGS,reinterpret_cast<const BYTE*>(&disabled),sizeof(disabled)))
            {fail(GetLastError());return result;}
            SP_DEVINSTALL_PARAMS_W parameters{}; parameters.cbSize=sizeof(parameters);
            if(!SetupDiGetDeviceInstallParamsW(deviceSet.value,&device,&parameters)){fail(GetLastError());return result;}
            // Documented installation flag: CONFIGFLAG_DISABLED alone is not
            // the contract for DIF_INSTALLDEVICE's default handler. Install
            // disabled until own endpoint policy has survived the INF install.
            parameters.Flags|=DI_ENUMSINGLEINF|DI_QUIETINSTALL|DI_INSTALLDISABLED;
            if(wcscpy_s(parameters.DriverPath,inf.c_str()) || !SetupDiSetDeviceInstallParamsW(deviceSet.value,&device,&parameters) ||
                !SetupDiBuildDriverInfoList(deviceSet.value,&device,SPDIT_COMPATDRIVER)) {fail(GetLastError());return result;}
            SP_DRVINFO_DATA_W driver{};driver.cbSize=sizeof(driver);
            if(!SetupDiEnumDriverInfoW(deviceSet.value,&device,SPDIT_COMPATDRIVER,0,&driver)){fail(GetLastError());return result;}
            if(driver.DriverVersion!=Version || _wcsicmp(driver.ProviderName,L"VB-Audio Software")){fail(ERROR_INVALID_DATA);return result;}
            std::vector<std::wstring> existing;
            hr=ExistingDevices(existing);
            if(FAILED(hr) || !existing.empty()){fail(ERROR_ALREADY_EXISTS);return result;}
            if(!SetupDiSetSelectedDriverW(deviceSet.value,&device,&driver) || !SetupDiCallClassInstaller(DIF_REGISTERDEVICE,deviceSet.value,&device))
            {fail(GetLastError());return result;}
            registered=true;result.ownDeviceRegistered=true;
            wchar_t instance[MAX_DEVICE_ID_LEN]{};
            if(!SetupDiGetDeviceInstanceIdW(deviceSet.value,&device,instance,MAX_DEVICE_ID_LEN,nullptr)){fail(GetLastError());return result;}
            result.ownInstance=instance;
            if(Put(journal.value,L"OwnInstance",result.ownInstance)!=ERROR_SUCCESS || RegFlushKey(journal.value)!=ERROR_SUCCESS)
            {fail(ERROR_WRITE_FAULT);return result;}
            hr=ConfigureOwnAppScopedInterfaces(deviceSet.value,device,inf);
            if(FAILED(hr)){fail(static_cast<DWORD>(hr));return result;}
            if(Put(journal.value,L"EndpointPolicy",L"explicit_app_selection_never_system_default")!=ERROR_SUCCESS)
            {fail(ERROR_WRITE_FAULT);return result;}
            if(!DiInstallDevice(nullptr,deviceSet.value,&device,&driver,DIIDFLAG_NOFINISHINSTALLUI,&needReboot)) {fail(GetLastError());return result;}
            // Do not assume the INF/co-installer retained policy written before
            // installation. Re-read exact own interface values before enabling.
            hr=ConfigureOwnAppScopedInterfaces(deviceSet.value,device,inf,true);
            if(FAILED(hr)){fail(static_cast<DWORD>(hr));return result;}
            parameters={};parameters.cbSize=sizeof(parameters);
            if(!SetupDiGetDeviceInstallParamsW(deviceSet.value,&device,&parameters)){fail(GetLastError());return result;}
            parameters.Flags&=~static_cast<DWORD>(DI_INSTALLDISABLED);
            if(!SetupDiSetDeviceInstallParamsW(deviceSet.value,&device,&parameters)){fail(GetLastError());return result;}
            DWORD configured=0,type=0,bytes=0;
            if(!SetupDiGetDeviceRegistryPropertyW(deviceSet.value,&device,SPDRP_CONFIGFLAGS,&type,reinterpret_cast<BYTE*>(&configured),sizeof(configured),&bytes) || type!=REG_DWORD || bytes!=sizeof(configured))
            {fail(ERROR_INVALID_DATA);return result;}
            configured&=~static_cast<DWORD>(CONFIGFLAG_DISABLED);
            if(!SetupDiSetDeviceRegistryPropertyW(deviceSet.value,&device,SPDRP_CONFIGFLAGS,reinterpret_cast<const BYTE*>(&configured),sizeof(configured)))
            {fail(GetLastError());return result;}
            SP_PROPCHANGE_PARAMS enable{};enable.ClassInstallHeader.cbSize=sizeof(SP_CLASSINSTALL_HEADER);enable.ClassInstallHeader.InstallFunction=DIF_PROPERTYCHANGE;
            enable.StateChange=DICS_ENABLE;enable.Scope=DICS_FLAG_GLOBAL;enable.HwProfile=0;
            if(!SetupDiSetClassInstallParamsW(deviceSet.value,&device,&enable.ClassInstallHeader,sizeof(enable)) || !SetupDiCallClassInstaller(DIF_PROPERTYCHANGE,deviceSet.value,&device))
            {fail(GetLastError());return result;}
            std::array<std::wstring,6> afterDefaults;
            hr=AudioDefaults(afterDefaults);
            if(FAILED(hr) || afterDefaults!=originalDefaults){fail(ERROR_RETRY);return result;}
            result.defaultsPreserved=true;
            // Publisher documentation explicitly requires a restart. Report it
            // even if PnP's per-device flag is false; never reboot automatically.
            result.rebootRequired=true; result.state=CableSetupState::RebootRequired;
            if(PutState(journal.value,L"reboot_required",ERROR_SUCCESS)!=ERROR_SUCCESS) result.state=CableSetupState::UnknownPending;
            return result;
        }
        catch(...){result.state=CableSetupState::UnknownPending;result.error=ERROR_UNHANDLED_EXCEPTION;return result;}
    }
}
