#include "../../native/phone-camera/PhoneCameraCableSetup.h"
#include <cstdio>
#include <stdexcept>

using namespace Magnolie::PhoneCamera;
namespace
{
    bool JournalExists()
    {
        HKEY key=nullptr;
        const LSTATUS status=RegOpenKeyExW(HKEY_LOCAL_MACHINE,L"SOFTWARE\\Magnolie Organizer\\WebcamDriver\\VB-CABLE-Pack46",0,KEY_READ,&key);
        if(key) RegCloseKey(key);
        if(status!=ERROR_SUCCESS && status!=ERROR_FILE_NOT_FOUND) throw std::runtime_error("journal read failed");
        return status==ERROR_SUCCESS;
    }
    void Check(bool condition) { if(!condition) throw std::runtime_error("readonly setup plan assertion"); }
}
int wmain(int argc,wchar_t** argv)
{
    if(argc!=2) return 2;
    try
    {
        const bool before=JournalExists();
        std::unique_ptr<CablePackage> package;
        const HRESULT verified=CablePackage::Verify(argv[1],package);
        if(FAILED(verified)){std::printf("FAIL package-verification %08lx\n",static_cast<unsigned long>(verified));return 1;}
        CableSetupPlan plan;
        const HRESULT planned=PlanCableSetup(*package,plan);
        if(FAILED(planned)){std::printf("FAIL readonly-plan %08lx\n",static_cast<unsigned long>(planned));return 1;}
        Check(plan.supportedHost);
        Check(plan.canInspectAudioDefaults);
        std::printf("PASS cable-readonly-native-host-and-existing-device-plan (existing=%zu elevated=%d)\n",plan.existingDevices.size(),plan.elevated ? 1 : 0);
        // Canonical test input is the existing user-writable research staging
        // directory, never the protected installation subtree. It cannot be
        // promoted into an installable package just because bytes are trusted.
        Check(!plan.protectedPackage);
        Check(before==JournalExists() && plan.existingTransaction==before);
        std::puts("PASS cable-user-cache-not-installable-and-journal-not-created");
        // Deliberately DO NOT call InstallCable, registration, driver staging,
        // cleanup, vendor programs or any system-device mutation in this probe.
        return 0;
    }
    catch(...){std::puts("FAIL cable-readonly-plan");return 1;}
}
