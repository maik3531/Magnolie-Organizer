#include "../../native/phone-camera/PhoneCameraCablePackage.h"
#include <wintrust.h>
#include <objbase.h>
#include <cstdio>
#include <stdexcept>

using Magnolie::PhoneCamera::CablePackage;
namespace
{
    void Check(bool condition) { if(!condition) throw std::runtime_error("cable package assertion"); }
    void Ok(HRESULT hr) { if(FAILED(hr)) { std::printf("HRESULT=%08lx\n",static_cast<unsigned long>(hr)); Check(false); } }
    std::wstring directory;
    int cleanupFailures = 0;
    void OriginalPackageKernelPolicy()
    {
        std::unique_ptr<CablePackage> package; Ok(CablePackage::Verify(directory,package));
        Check(package && package->Directory()==directory);
        std::puts("PASS cable-original-sha256-and-kernel-catalog-membership");
        const auto path=directory+L"\\"+CablePackage::Filename(0);
        HANDLE changed=CreateFileW(path.c_str(),GENERIC_WRITE,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);
        Check(changed==INVALID_HANDLE_VALUE && GetLastError()==ERROR_SHARING_VIOLATION);
        Check(CablePackage::Verify(directory,package)==E_INVALIDARG);
        std::puts("PASS cable-held-files-refuse-write-and-live-lease-replacement");
    }
    struct Scratch
    {
        std::wstring path;
        bool created = false;
        Scratch()
        {
            wchar_t temp[32768]{},text[40]{}; GUID id{}; Ok(CoCreateGuid(&id)); StringFromGUID2(id,text,40);
            Check(GetTempPathW(32768,temp)!=0); path=std::wstring(temp)+L"Magnolie-Cable530-"+text;
            Check(CreateDirectoryW(path.c_str(),nullptr)!=FALSE);
            created = true;
            try
            {
                for(std::size_t i=0;i<4;++i) Check(CopyFileW((directory+L"\\"+CablePackage::Filename(i)).c_str(),(path+L"\\"+CablePackage::Filename(i)).c_str(),TRUE)!=FALSE);
            }
            catch(...) { Cleanup(); throw; }
        }
        ~Scratch() { Cleanup(); }
        void Cleanup() noexcept
        {
            if(!created) return;
            for(std::size_t i=0;i<4;++i) DeleteFileW((path+L"\\"+CablePackage::Filename(i)).c_str());
            if(!RemoveDirectoryW(path.c_str())) ++cleanupFailures;
            created = false;
        }
    };
    void TamperedPayloadRejected()
    {
        Scratch scratch; const auto path=scratch.path+L"\\"+CablePackage::Filename(0);
        HANDLE file=CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,OPEN_EXISTING,0,nullptr); Check(file!=INVALID_HANDLE_VALUE);
        const BYTE bad=0; DWORD bytes=0; Check(WriteFile(file,&bad,1,&bytes,nullptr)!=FALSE && bytes==1); CloseHandle(file);
        std::unique_ptr<CablePackage> package; Check(CablePackage::Verify(scratch.path,package)==TRUST_E_BAD_DIGEST && !package);
        std::puts("PASS cable-tampered-payload-denied-before-installation");
        Check(DeleteFileW(path.c_str())!=FALSE);
        Check(FAILED(CablePackage::Verify(scratch.path,package)) && !package);
        std::puts("PASS cable-missing-payload-no-partial-package-lease");
    }
    void NoArbitraryPathOrInstaller()
    {
        std::unique_ptr<CablePackage> package;
        Check(CablePackage::Verify(L"relative",package)==E_INVALIDARG && !package);
        Check(CablePackage::Verify(L"\\\\remote\\share",package)==E_INVALIDARG && !package);
        Check(CablePackage::Verify(directory+L"\\..",package)==E_INVALIDARG && !package);
        Check(CablePackage::Filename(4)==nullptr);
        std::puts("PASS cable-relative-remote-traversal-paths-refused");
    }
}
int wmain(int argc,wchar_t** argv)
{
    if(argc!=2) return 2; directory=argv[1];
    try { OriginalPackageKernelPolicy(); TamperedPayloadRejected(); NoArbitraryPathOrInstaller(); }
    catch(...) { std::puts("FAIL cable-package-readonly"); return 1; }
    // There is intentionally NO installation/device-registration call here.
    return cleanupFailures ? 1 : 0;
}
