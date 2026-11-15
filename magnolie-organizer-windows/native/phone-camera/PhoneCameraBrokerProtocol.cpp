#include "PhoneCameraBrokerProtocol.h"
#include <bcrypt.h>
#include <objbase.h>
#include <cstring>

namespace Magnolie::PhoneCamera
{
    namespace
    {
        template<class T> T Read(const BYTE* bytes) noexcept { T value{}; std::memcpy(&value, bytes, sizeof(value)); return value; }
        template<class T> void Put(BYTE* bytes, const T& value) noexcept { std::memcpy(bytes, &value, sizeof(value)); }
        HRESULT Status(NTSTATUS status) noexcept { return status < 0 ? HRESULT_FROM_NT(status) : S_OK; }
    }
    GUID BrokerProperty::Scope() const noexcept { return Read<GUID>(bytes_.data() + 16); }
    GUID BrokerProperty::Pipe() const noexcept { return Read<GUID>(bytes_.data() + 32); }
    DWORD BrokerProperty::ParentPid() const noexcept { return Read<DWORD>(bytes_.data() + 48); }
    DWORD BrokerProperty::ParentSession() const noexcept { return Read<DWORD>(bytes_.data() + 52); }
    ULONGLONG BrokerProperty::ParentBirth() const noexcept { return Read<ULONGLONG>(bytes_.data() + 56); }
    HRESULT BrokerProperty::Random(BYTE* nonce) noexcept
    { return nonce ? Status(BCryptGenRandom(nullptr, nonce, NonceBytes, BCRYPT_USE_SYSTEM_PREFERRED_RNG)) : E_POINTER; }
    HRESULT BrokerProperty::CreateOriginal(const GUID& scope, BrokerProperty& result) noexcept
    {
        if (result.initialized_ || scope == GUID_NULL) return E_INVALIDARG;
        std::array<BYTE, Bytes> bytes{};
        struct Clear { BYTE* data; ~Clear() { SecureZeroMemory(data, Bytes); } } clear{bytes.data()};
        std::memcpy(bytes.data(), "MGFSB001", 8); Put<DWORD>(bytes.data() + 8, 1); Put<DWORD>(bytes.data() + 12, Bytes);
        Put(bytes.data() + 16, scope);
        GUID pipe{}; HRESULT hr = CoCreateGuid(&pipe); if (FAILED(hr)) return hr;
        Put(bytes.data() + 32, pipe); Put<DWORD>(bytes.data() + 48, GetCurrentProcessId());
        DWORD session = 0;
        if (!ProcessIdToSessionId(GetCurrentProcessId(), &session)) return HRESULT_FROM_WIN32(GetLastError());
        if (!session) return E_ACCESSDENIED;
        Put(bytes.data() + 52, session);
        FILETIME birth{}, exit{}, kernel{}, user{};
        if (!GetProcessTimes(GetCurrentProcess(), &birth, &exit, &kernel, &user)) return HRESULT_FROM_WIN32(GetLastError());
        std::memcpy(bytes.data() + 56, &birth, sizeof(birth));
        hr = Random(bytes.data() + 64); if (FAILED(hr)) return hr;
        return Decode(bytes.data(), Bytes, result);
    }
    HRESULT BrokerProperty::Decode(const BYTE* bytes, ULONG size, BrokerProperty& result) noexcept
    {
        if (!bytes || size != Bytes || result.initialized_) return E_INVALIDARG;
        // Copy before inspection: property callers must not retain mutable state.
        std::array<BYTE, Bytes> owned{}; std::memcpy(owned.data(), bytes, size);
        struct Clear { BYTE* data; ~Clear() { SecureZeroMemory(data, Bytes); } } clear{owned.data()};
        BYTE key = 0; for (ULONG i = 64; i < Bytes; ++i) key |= owned[i];
        if (std::memcmp(owned.data(), "MGFSB001", 8) || Read<DWORD>(owned.data() + 8) != 1 ||
            Read<DWORD>(owned.data() + 12) != Bytes || Read<GUID>(owned.data() + 16) == GUID_NULL ||
            Read<GUID>(owned.data() + 32) == GUID_NULL || !Read<DWORD>(owned.data() + 48) ||
            !Read<DWORD>(owned.data() + 52) || !Read<ULONGLONG>(owned.data() + 56) || !key) return E_INVALIDARG;
        result.bytes_ = owned; result.initialized_ = true; result.keyAvailable_ = true; return S_OK;
    }
    HRESULT BrokerProperty::Mac(bool source, const BYTE* parentNonce, const BYTE* sourceNonce, BYTE* result) const noexcept
    {
        if (!initialized_ || !keyAvailable_ || !parentNonce || !sourceNonce || !result) return E_INVALIDARG;
        std::array<BYTE, 136> body{};
        std::memcpy(body.data(), source ? "MGFSSRC1" : "MGFSPAR1", 8);
        std::memcpy(body.data() + 8, bytes_.data(), 64);
        std::memcpy(body.data() + 72, parentNonce, NonceBytes); std::memcpy(body.data() + 104, sourceNonce, NonceBytes);
        BCRYPT_ALG_HANDLE algorithm = nullptr; BCRYPT_HASH_HANDLE hash = nullptr;
        struct Clear
        {
            BCRYPT_ALG_HANDLE& algorithm; BCRYPT_HASH_HANDLE& hash; BYTE* body;
            ~Clear() { if (hash) BCryptDestroyHash(hash); if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0); SecureZeroMemory(body, 136); }
        } clear{algorithm, hash, body.data()};
        NTSTATUS status = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, BCRYPT_ALG_HANDLE_HMAC_FLAG);
        if (status >= 0) status = BCryptCreateHash(algorithm, &hash, nullptr, 0, const_cast<BYTE*>(bytes_.data() + 64), NonceBytes, 0);
        if (status >= 0) status = BCryptHashData(hash, body.data(), static_cast<ULONG>(body.size()), 0);
        if (status >= 0) status = BCryptFinishHash(hash, result, NonceBytes, 0);
        if (status < 0) SecureZeroMemory(result, NonceBytes);
        return Status(status);
    }
    bool BrokerProperty::EqualMac(const BYTE* a, const BYTE* b) noexcept
    {
        if (!a || !b) return false;
        volatile BYTE different = 0;
        for (ULONG i = 0; i < NonceBytes; ++i) different = static_cast<BYTE>(different | (a[i] ^ b[i]));
        return different == 0;
    }
}
