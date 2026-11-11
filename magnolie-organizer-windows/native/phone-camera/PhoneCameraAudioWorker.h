#pragma once
namespace Magnolie::PhoneCamera
{
    // Fixed native runtime entry. No alternative device/test/readiness route.
    // 64 invalid CLI, 65 missing own parent/job/stop bootstrap, 66 session/IO failure.
    int AudioWorkerMain(int argc, wchar_t** argv) noexcept;
#ifdef MAGNOLIE_NATIVE_AUDIO_WORKER_TESTS
    unsigned int AudioWorkerTestStage() noexcept; // Observer only; no endpoint/authority bypass.
#endif
}
