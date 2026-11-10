#pragma once
#include "PhoneCameraCablePackage.h"
#include <vector>

namespace Magnolie::PhoneCamera
{
    enum class CableSetupState
    {
        Unsupported, AdministratorRequired, ExistingDevice, ExistingTransaction,
        UnprotectedPackage, Prepared, Installed, RebootRequired, Failed,
        CleanupPending, UnknownPending
    };
    struct CableSetupResult
    {
        CableSetupState state = CableSetupState::Failed;
        DWORD error = ERROR_SUCCESS;
        bool ownDeviceRegistered = false, ownDeviceRemoved = false, rebootRequired = false, defaultsPreserved = false;
        std::wstring ownInstance;
    };
    struct CableSetupPlan
    {
        bool supportedHost = false, elevated = false, protectedPackage = false, existingTransaction = false, canInspectAudioDefaults = false;
        std::vector<std::wstring> existingDevices;
    };
    // Pure query: does NOT stage a driver, register a device, create a journal,
    // change an endpoint/default, execute a vendor installer or request elevation.
    HRESULT PlanCableSetup(const CablePackage& package, CableSetupPlan& result) noexcept;

    // Explicit elevated setup path ONLY. Caller first obtains native user
    // confirmation and one normal Windows administrator authorization. It must
    // create the as-is package under the protected fixed ProgramData subtree.
    // Never callable from incoming phone controls/renderer/native output startup.
    // Existing devices/transactions are refused, never updated or retried.
    CableSetupResult InstallCable(const CablePackage& package) noexcept;
}
