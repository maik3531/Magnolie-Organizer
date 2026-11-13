#pragma once
#include <windows.h>
#include <array>

namespace Magnolie::PhoneCamera
{
    // Private OS-property rendezvous bytes, NEVER a SourceBindingProof, SEND,
    // peer identity or readiness. Authentication additionally requires the
    // original manager, both held kernel peers and the live original owner.
    class BrokerProperty final
    {
    public:
        static constexpr ULONG Bytes = 96;
        static constexpr ULONG NonceBytes = 32;
        inline static constexpr GUID PropertySet = {0x5ec92e36, 0xcf6a, 0x46ae, {0xa4, 0xe4, 0x59, 0x0b, 0x8c, 0xb8, 0x27, 0x97}};
        static constexpr ULONG PropertyId = 1;
        static HRESULT CreateOriginal(const GUID& originalScope, BrokerProperty& result) noexcept;
        static HRESULT Decode(const BYTE* exactBytes, ULONG bytes, BrokerProperty& result) noexcept;
        BrokerProperty() = default;
        ~BrokerProperty() { SecureZeroMemory(bytes_.data(), bytes_.size()); }
        BrokerProperty(const BrokerProperty&) = delete;
        BrokerProperty& operator=(const BrokerProperty&) = delete;
        void CopyForProperty(std::array<BYTE, Bytes>& owned) const noexcept { owned = bytes_; }
        GUID Scope() const noexcept;
        GUID Pipe() const noexcept;
        DWORD ParentPid() const noexcept;
        DWORD ParentSession() const noexcept;
        ULONGLONG ParentBirth() const noexcept;
        HRESULT Mac(bool fromSource, const BYTE* parentNonce, const BYTE* sourceNonce, BYTE* result) const noexcept;
        static HRESULT Random(BYTE* nonce) noexcept;
        static bool EqualMac(const BYTE* a, const BYTE* b) noexcept;
        void ClearKey() noexcept { SecureZeroMemory(bytes_.data() + 64, NonceBytes); keyAvailable_ = false; }
    private:
        std::array<BYTE, Bytes> bytes_{};
        bool initialized_ = false;
        bool keyAvailable_ = false;
    };
}
