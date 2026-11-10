#pragma once
#include <windows.h>
#include <array>
#include <memory>
#include <string>

namespace Magnolie::PhoneCamera
{
    // Exact original publisher package, never A+B/C+D or a repacked driver.
    inline constexpr wchar_t CablePackageUrl[] = L"https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack46.zip";
    inline constexpr wchar_t CablePackageSha256[] = L"bc44e8974191a5a2427d6c979e2dab08dbb09925f3f435dfa2f0ba3e45b6eb90";
    inline constexpr wchar_t CableManualUrl[] = L"https://vb-audio.com/Cable/";
    inline constexpr wchar_t CableLicenseUrl[] = L"https://vb-audio.com/Services/licensing.htm";
    inline constexpr wchar_t CableDriverName[] = L"VB-CABLE (VB-Audio Virtual Cable)";

    // Read-only package trust/identity lease, NOT permission to install or a
    // witness that native render/capture endpoints exist. Held file handles
    // deny write/delete sharing until the last installer/reader reference ends.
    class CablePackage final
    {
    public:
        static HRESULT Verify(const std::wstring& directory, std::unique_ptr<CablePackage>& result) noexcept;
        ~CablePackage();
        const std::wstring& Directory() const noexcept { return directory_; }
        static const wchar_t* Filename(std::size_t index) noexcept;
        CablePackage(const CablePackage&) = delete;
        CablePackage& operator=(const CablePackage&) = delete;
    private:
        explicit CablePackage(std::wstring directory) : directory_(std::move(directory)) {}
        std::wstring directory_;
        std::array<HANDLE, 4> files_{};
    };
}
