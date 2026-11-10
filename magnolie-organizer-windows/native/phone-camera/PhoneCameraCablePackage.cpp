#include "PhoneCameraCablePackage.h"
#include <bcrypt.h>
#include <wincrypt.h>
#include <wintrust.h>
#include <softpub.h>
#include <mscat.h>
#include <vector>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        struct Entry { const wchar_t* name; const char* sha256; };
        constexpr Entry Entries[] = {
            {L"vbMmeCable64_win10.inf", "cecf9181b6c85842d707330efc594824a749a1d9e01db46eba0e60e72f0a66ee"},
            {L"vbaudio_cable64_win10.cat", "5d24c17858b49ad83bb856c66c24c5c2aecdb89cbaae2f8179c15d351124fa9f"},
            {L"vbaudio_cable64_win10.sys", "7ebcbbe7004d185f7b29613cd27fdc2dd71c1712224b767a74d2f66bdc33a7ef"},
            {L"vbaudio_cable64arm_win10.sys", "85c217af826c2e1d478b52afc7c2248889c8478030d44e8134bd4c23b8915216"}
        };
        HRESULT LastError() noexcept { return HRESULT_FROM_WIN32(GetLastError()); }
        struct Algorithm { BCRYPT_ALG_HANDLE value = nullptr; ~Algorithm() { if(value) BCryptCloseAlgorithmProvider(value,0); } };
        struct Hash { BCRYPT_HASH_HANDLE value = nullptr; ~Hash() { if(value) BCryptDestroyHash(value); } };
        HRESULT PinnedHash(HANDLE file, const char* expected) noexcept
        {
            Algorithm algorithm; Hash hash;
            NTSTATUS status = BCryptOpenAlgorithmProvider(&algorithm.value,BCRYPT_SHA256_ALGORITHM,nullptr,0);
            if(status < 0) return HRESULT_FROM_NT(status);
            status = BCryptCreateHash(algorithm.value,&hash.value,nullptr,0,nullptr,0,0);
            if(status < 0) return HRESULT_FROM_NT(status);
            LARGE_INTEGER zero{};
            if(!SetFilePointerEx(file,zero,nullptr,FILE_BEGIN)) return LastError();
            BYTE buffer[16384]{}; DWORD bytes = 0;
            do
            {
                if(!ReadFile(file,buffer,sizeof(buffer),&bytes,nullptr)) return LastError();
                status = BCryptHashData(hash.value,buffer,bytes,0);
                if(status < 0) return HRESULT_FROM_NT(status);
            } while(bytes);
            BYTE digest[32]{};
            status = BCryptFinishHash(hash.value,digest,sizeof(digest),0);
            if(status < 0) return HRESULT_FROM_NT(status);
            constexpr char hex[] = "0123456789abcdef";
            unsigned int difference = 0;
            for(std::size_t i=0;i<32;++i)
            {
                difference |= static_cast<unsigned int>(hex[digest[i]>>4] ^ expected[2*i]);
                difference |= static_cast<unsigned int>(hex[digest[i]&15] ^ expected[2*i+1]);
            }
            return difference ? TRUST_E_BAD_DIGEST : S_OK;
        }
        HRESULT CatalogMember(HANDLE file, const std::wstring& path, const std::wstring& catalog)
        {
            GUID policy = DRIVER_ACTION_VERIFY;
            struct Admin { HCATADMIN value = nullptr; ~Admin() { if(value) CryptCATAdminReleaseContext(value,0); } } admin;
            if(!CryptCATAdminAcquireContext(&admin.value,&policy,0)) return LastError();
            LARGE_INTEGER zero{};
            if(!SetFilePointerEx(file,zero,nullptr,FILE_BEGIN)) return LastError();
            DWORD bytes = 0;
            if(!CryptCATAdminCalcHashFromFileHandle(file,&bytes,nullptr,0) && GetLastError()!=ERROR_INSUFFICIENT_BUFFER) return LastError();
            if(!bytes || bytes>64) return TRUST_E_BAD_DIGEST;
            std::vector<BYTE> hash(bytes);
            if(!CryptCATAdminCalcHashFromFileHandle(file,&bytes,hash.data(),0)) return LastError();
            constexpr wchar_t hex[] = L"0123456789ABCDEF";
            std::wstring tag;
            for(DWORD i=0;i<bytes;++i) { tag+=hex[hash[i]>>4]; tag+=hex[hash[i]&15]; }
            WINTRUST_CATALOG_INFO member{}; member.cbStruct=sizeof(member);
            member.pcwszCatalogFilePath=catalog.c_str(); member.pcwszMemberTag=tag.c_str();
            member.pcwszMemberFilePath=path.c_str(); member.hMemberFile=file;
            member.pbCalculatedFileHash=hash.data(); member.cbCalculatedFileHash=bytes; member.hCatAdmin=admin.value;
            WINTRUST_DATA trust{}; trust.cbStruct=sizeof(trust); trust.dwUIChoice=WTD_UI_NONE;
            trust.fdwRevocationChecks=WTD_REVOKE_WHOLECHAIN; trust.dwUnionChoice=WTD_CHOICE_CATALOG;
            trust.pCatalog=&member; trust.dwStateAction=WTD_STATEACTION_VERIFY;
            // Fail closed on unavailable cached revocation evidence. This helper
            // neither changes trust roots nor blocks on arbitrary network URLs.
            trust.dwProvFlags=WTD_CACHE_ONLY_URL_RETRIEVAL | WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT;
            const LONG verified = WinVerifyTrust(nullptr,&policy,&trust);
            trust.dwStateAction=WTD_STATEACTION_CLOSE; WinVerifyTrust(nullptr,&policy,&trust);
            return static_cast<HRESULT>(verified);
        }
    }
    const wchar_t* CablePackage::Filename(std::size_t index) noexcept
    { return index<4 ? Entries[index].name : nullptr; }
    CablePackage::~CablePackage()
    { for(HANDLE file:files_) if(file && file!=INVALID_HANDLE_VALUE) CloseHandle(file); }
    HRESULT CablePackage::Verify(const std::wstring& directory, std::unique_ptr<CablePackage>& result) noexcept
    {
        if(result || directory.size()<3 || directory.size()>30000 || directory[1]!=L':' || directory[2]!=L'\\') return E_INVALIDARG;
        try
        {
            wchar_t full[32768]{};
            const DWORD length=GetFullPathNameW(directory.c_str(),32768,full,nullptr);
            if(!length || length>=32768 || _wcsicmp(full,directory.c_str())) return E_INVALIDARG;
            std::unique_ptr<CablePackage> package(new CablePackage(directory));
            for(std::size_t i=0;i<4;++i)
            {
                const auto path=directory+L"\\"+Entries[i].name;
                HANDLE file=CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
                if(file==INVALID_HANDLE_VALUE) return LastError();
                package->files_[i]=file;
                BY_HANDLE_FILE_INFORMATION info{}; LARGE_INTEGER size{};
                if(!GetFileInformationByHandle(file,&info) || !GetFileSizeEx(file,&size)) return LastError();
                if(info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT) || size.QuadPart<1 || size.QuadPart>32*1024*1024) return E_INVALIDARG;
                HRESULT hr=PinnedHash(file,Entries[i].sha256); if(FAILED(hr)) return hr;
            }
            const auto catalog=directory+L"\\"+Entries[1].name;
            for(std::size_t i : {std::size_t(0),std::size_t(2),std::size_t(3)})
            {
                HRESULT hr=CatalogMember(package->files_[i],directory+L"\\"+Entries[i].name,catalog);
                if(FAILED(hr)) return hr;
            }
            result=std::move(package); return S_OK;
        }
        catch(...) { return E_OUTOFMEMORY; }
    }
}
