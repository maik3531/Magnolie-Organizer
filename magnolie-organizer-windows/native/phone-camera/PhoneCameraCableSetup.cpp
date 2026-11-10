#include "PhoneCameraCableSetup.h"
#include <setupapi.h>
#include <newdev.h>
#include <cfgmgr32.h>
#include <sddl.h>
#include <aclapi.h>
#include <shlobj.h>
#include <cwchar>
#include <cstring>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        constexpr GUID MediaClass = {0x4d36e96c,0xe325,0x11ce,{0xbf,0xc1,0x08,0x00,0x2b,0xe1,0x03,0x18}};
        constexpr wchar_t HardwareId[] = L"VBAudioVACWDM";
        constexpr wchar_t Journal[] = L"SOFTWARE\\Magnolie Organizer\\WebcamDriver\\VB-CABLE-Pack46";
        constexpr wchar_t Marker[] = L"Magnolie VB-CABLE Pack46 setup v1";
        constexpr ULONGLONG Version = (3ULL<<48)|(5ULL<<32)|(2ULL<<16);
        struct Devices { HDEVINFO value = INVALID_HANDLE_VALUE; ~Devices(){ if(value!=INVALID_HANDLE_VALUE) SetupDiDestroyDeviceInfoList(value); } };
        struct Handle { HANDLE value = nullptr; ~Handle(){ if(value && value!=INVALID_HANDLE_VALUE) CloseHandle(value); } };
        struct Key { HKEY value = nullptr; ~Key(){ if(value) RegCloseKey(value); } };
        struct Local { void* value = nullptr; ~Local(){ if(value) LocalFree(value); } };
        struct ComMemory { wchar_t* value = nullptr; ~ComMemory(){ if(value) CoTaskMemFree(value); } };
        HRESULT LastError() noexcept { return HRESULT_FROM_WIN32(GetLastError()); }
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
            if(!plan.existingDevices.empty()){result.state=CableSetupState::ExistingDevice;result.error=ERROR_ALREADY_EXISTS;return result;}
            if(plan.existingTransaction){result.state=CableSetupState::ExistingTransaction;result.error=ERROR_ALREADY_EXISTS;return result;}
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
            SP_DEVINSTALL_PARAMS_W parameters{}; parameters.cbSize=sizeof(parameters);
            if(!SetupDiGetDeviceInstallParamsW(deviceSet.value,&device,&parameters)){fail(GetLastError());return result;}
            parameters.Flags|=DI_ENUMSINGLEINF|DI_QUIETINSTALL;
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
            if(!DiInstallDevice(nullptr,deviceSet.value,&device,&driver,DIIDFLAG_NOFINISHINSTALLUI,&needReboot)) {fail(GetLastError());return result;}
            // Publisher documentation explicitly requires a restart. Report it
            // even if PnP's per-device flag is false; never reboot automatically.
            result.rebootRequired=true; result.state=CableSetupState::RebootRequired;
            if(PutState(journal.value,L"reboot_required",ERROR_SUCCESS)!=ERROR_SUCCESS) result.state=CableSetupState::UnknownPending;
            return result;
        }
        catch(...){result.state=CableSetupState::UnknownPending;result.error=ERROR_UNHANDLED_EXCEPTION;return result;}
    }
}
