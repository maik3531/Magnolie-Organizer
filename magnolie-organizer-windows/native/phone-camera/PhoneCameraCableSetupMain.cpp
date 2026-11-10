#include "PhoneCameraCableSetup.h"
#include <cstdio>
#include <cwchar>

using namespace Magnolie::PhoneCamera;
namespace
{
    const char* State(CableSetupState state) noexcept
    {
        switch(state)
        {
            case CableSetupState::Unsupported:return "unsupported";
            case CableSetupState::AdministratorRequired:return "administrator_required";
            case CableSetupState::ExistingDevice:return "existing_device";
            case CableSetupState::ExistingTransaction:return "existing_transaction";
            case CableSetupState::UnprotectedPackage:return "unprotected_package";
            case CableSetupState::Prepared:return "prepared";
            case CableSetupState::Installed:return "installed";
            case CableSetupState::RebootRequired:return "reboot_required";
            case CableSetupState::CleanupPending:return "cleanup_pending";
            case CableSetupState::UnknownPending:return "unknown_pending";
            default:return "failed";
        }
    }
    std::string Json(const std::wstring& value)
    {
        const int bytes=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,value.data(),static_cast<int>(value.size()),nullptr,0,nullptr,nullptr);
        if(!value.empty() && !bytes) return "null";
        std::string utf8(static_cast<std::size_t>(bytes),'\0');
        WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,value.data(),static_cast<int>(value.size()),utf8.data(),bytes,nullptr,nullptr);
        std::string result="\"";
        constexpr char hex[]="0123456789abcdef";
        for(unsigned char c:utf8)
        {
            if(c=='\\' || c=='"'){result+='\\';result+=static_cast<char>(c);}
            else if(c<32){result+="\\u00";result+=hex[c>>4];result+=hex[c&15];}
            else result+=static_cast<char>(c);
        }
        return result+'"';
    }
}
int wmain(int argc,wchar_t** argv)
{
    // No elevation request or implicit default action. Product native UI must
    // obtain one explicit setup confirmation before its normal runas helper.
    if(argc!=3 || (std::wcscmp(argv[1],L"--plan") && std::wcscmp(argv[1],L"--install"))) return ERROR_INVALID_PARAMETER;
    try
    {
        std::unique_ptr<CablePackage> package;
        const HRESULT verified=CablePackage::Verify(argv[2],package);
        if(FAILED(verified))
        {
            std::printf("{\"schema\":1,\"driver\":\"VB-CABLE\",\"state\":\"verification_failed\",\"hresult\":%ld}\n",static_cast<long>(verified));
            return ERROR_INSTALL_PACKAGE_REJECTED;
        }
        if(!std::wcscmp(argv[1],L"--plan"))
        {
            CableSetupPlan plan; const HRESULT planned=PlanCableSetup(*package,plan);
            if(FAILED(planned))
            {
                std::printf("{\"schema\":1,\"driver\":\"VB-CABLE\",\"mode\":\"plan\",\"state\":\"query_failed\",\"hresult\":%ld}\n",static_cast<long>(planned));
                return ERROR_INSTALL_FAILURE;
            }
            std::printf("{\"schema\":1,\"driver\":\"VB-CABLE\",\"mode\":\"plan\",\"supportedHost\":%s,\"elevated\":%s,\"protectedPackage\":%s,\"existingTransaction\":%s,\"existingDeviceCount\":%zu,\"canInspectAudioDefaults\":%s,\"endpointPolicy\":\"explicit_app_selection_never_system_default\",\"installationAttempted\":false}\n",
                plan.supportedHost?"true":"false",plan.elevated?"true":"false",plan.protectedPackage?"true":"false",plan.existingTransaction?"true":"false",plan.existingDevices.size(),plan.canInspectAudioDefaults?"true":"false");
            return ERROR_SUCCESS;
        }
        const auto result=InstallCable(*package);
        std::printf("{\"schema\":1,\"driver\":\"VB-CABLE\",\"mode\":\"install\",\"state\":\"%s\",\"error\":%lu,\"ownDeviceRegistered\":%s,\"ownDeviceRemoved\":%s,\"rebootRequired\":%s,\"defaultsPreserved\":%s,\"ownInstance\":%s}\n",
            State(result.state),result.error,result.ownDeviceRegistered?"true":"false",result.ownDeviceRemoved?"true":"false",result.rebootRequired?"true":"false",result.defaultsPreserved?"true":"false",Json(result.ownInstance).c_str());
        switch(result.state)
        {
            case CableSetupState::Installed:return ERROR_SUCCESS;
            case CableSetupState::RebootRequired:return ERROR_SUCCESS_REBOOT_REQUIRED;
            case CableSetupState::AdministratorRequired:return ERROR_ELEVATION_REQUIRED;
            case CableSetupState::Unsupported:return ERROR_NOT_SUPPORTED;
            case CableSetupState::UnprotectedPackage:return ERROR_ACCESS_DENIED;
            case CableSetupState::ExistingDevice:return ERROR_PRODUCT_VERSION;
            case CableSetupState::ExistingTransaction:case CableSetupState::UnknownPending:case CableSetupState::CleanupPending:return ERROR_INSTALL_ALREADY_RUNNING;
            default:return ERROR_INSTALL_FAILURE;
        }
    }
    catch(...){return ERROR_UNHANDLED_EXCEPTION;}
}
