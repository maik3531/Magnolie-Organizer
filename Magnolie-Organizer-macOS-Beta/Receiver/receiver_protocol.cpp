/* SPDX-License-Identifier: GPL-3.0-or-later
 * Private, local IPC for the bundled Magnolie AirPlay receiver. Refs #721.
 * No network values or raw logs are serialized onto this channel.
 */
#include "receiver_protocol.h"

#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <mutex>
#include <pthread.h>
#include <set>
#include <sys/stat.h>
#include <unistd.h>

namespace {
int events = -1;
bool ready = false;
bool failed = false;
bool emitted_media = false;
size_t connections = 0;
char pending_pin[5] = {};
std::set<const void *> audio_streams;
std::set<const void *> video_streams;
std::mutex state_mutex;

// Each frame is smaller than POSIX's minimum PIPE_BUF (512). A slow/dead parent
// must never leave a receiver running indefinitely in a blocked logging call.
void send_event(const char *event, const char *code = nullptr) {
    char frame[160];
    const int size = code
        ? std::snprintf(frame, sizeof(frame),
            "{\"protocol\":1,\"event\":\"%s\",\"code\":\"%s\"}\n", event, code)
        : std::snprintf(frame, sizeof(frame),
            "{\"protocol\":1,\"event\":\"%s\"}\n", event);
    if (events < 0 || size <= 0 || size >= static_cast<int>(sizeof(frame))) {
        _exit(70);
    }
    ssize_t result;
    do {
        result = write(events, frame, static_cast<size_t>(size));
    } while (result < 0 && errno == EINTR);
    if (result != size) {
        // EPIPE, full pipe and partial writes all invalidate the host channel.
        _exit(70);
    }
}

void *watch_parent(void *) {
    char buffer[32];
    for (;;) {
        const ssize_t result = read(STDIN_FILENO, buffer, sizeof(buffer));
        if (result > 0 || (result < 0 && errno == EINTR)) continue;
        break;
    }
    kill(getpid(), SIGTERM);
    // Gst's main-thread wrapper can be busy during startup or shutdown. The
    // fallback touches only this process and bounds the lifetime after EOF.
    sleep(3);
    _exit(0);
}

bool known_error(const char *code) {
    static const char *codes[] = {
        "event_channel", "parent_channel", "media_runtime", "network_start",
        "service_discovery", "registration_store", "invalid_config",
        "receiver_internal"
    };
    if (!code) return false;
    for (const char *known : codes) if (!std::strcmp(code, known)) return true;
    return false;
}
}

extern "C" int magnolie_receiver_initialize(void) {
    umask(0077);
    struct stat output_stat;
    if (fstat(STDOUT_FILENO, &output_stat) || !S_ISFIFO(output_stat.st_mode)) {
        return 0;
    }
    std::fflush(stdout);
    events = dup(STDOUT_FILENO);
    if (events < 0 || fcntl(events, F_SETFD, FD_CLOEXEC) < 0 ||
        fcntl(events, F_SETFL, O_NONBLOCK) < 0 ||
        dup2(STDERR_FILENO, STDOUT_FILENO) < 0) return 0;
    signal(SIGPIPE, SIG_IGN);

    struct stat input_stat;
    if (fstat(STDIN_FILENO, &input_stat) || !S_ISFIFO(input_stat.st_mode)) {
        magnolie_receiver_error("parent_channel");
        return 0;
    }
    if (fcntl(STDIN_FILENO, F_SETFD, FD_CLOEXEC) < 0) {
        magnolie_receiver_error("parent_channel");
        return 0;
    }
    pthread_t watcher;
    if (pthread_create(&watcher, nullptr, watch_parent, nullptr) != 0) {
        magnolie_receiver_error("parent_channel");
        return 0;
    }
    pthread_detach(watcher);
    return 1;
}

extern "C" void magnolie_receiver_ready(void) {
    std::lock_guard<std::mutex> lock(state_mutex);
    if (ready || failed) return;
    ready = true;
    send_event("ready");
    if (pending_pin[0]) send_event("pin", pending_pin);
    if (!audio_streams.empty()) { send_event("audio"); emitted_media = true; }
    if (!video_streams.empty()) { send_event("video"); emitted_media = true; }
}

extern "C" void magnolie_receiver_pin(const char *code) {
    bool valid = code && std::strlen(code) == 4;
    if (valid) for (int i = 0; i < 4; ++i) {
        if (code[i] < '0' || code[i] > '9') valid = false;
    }
    if (!valid) {
        magnolie_receiver_error("receiver_internal");
        _exit(70);
    }
    std::lock_guard<std::mutex> lock(state_mutex);
    if (failed) return;
    std::memcpy(pending_pin, code, 5);
    if (ready) send_event("pin", pending_pin);
}

extern "C" void magnolie_receiver_media(int video, const void *stream) {
    std::lock_guard<std::mutex> lock(state_mutex);
    if (failed || !stream) return;
    auto &streams = video ? video_streams : audio_streams;
    if (streams.count(stream)) return;
    if (streams.size() >= 16) {
        failed = true;
        send_event("error", "receiver_internal");
        _exit(70);
    }
    const bool first = streams.empty();
    streams.insert(stream);
    pending_pin[0] = '\0';
    if (first && ready) {
        send_event(video ? "video" : "audio");
        emitted_media = true;
    }
}

extern "C" void magnolie_receiver_connection_opened(void) {
    std::lock_guard<std::mutex> lock(state_mutex);
    ++connections;
}

extern "C" void magnolie_receiver_connection_closed(void) {
    std::lock_guard<std::mutex> lock(state_mutex);
    if (!connections) return;
    --connections;
    // Pairing uses additional TCP connections. Clear an abandoned PIN only
    // after the last connection, with no media stream still alive.
    if (!failed && !connections && audio_streams.empty() && video_streams.empty() && pending_pin[0]) {
        pending_pin[0] = '\0';
        if (ready) send_event("disconnected");
    }
}

extern "C" void magnolie_receiver_stream_ended(int video, const void *stream) {
    std::lock_guard<std::mutex> lock(state_mutex);
    if (failed || !stream) return;
    auto &streams = video ? video_streams : audio_streams;
    if (!streams.erase(stream) || !streams.empty()) return;
    if (emitted_media) {
        emitted_media = false;
        pending_pin[0] = '\0';
        if (ready) {
            // The host contract has no per-kind "ended" event. Reset the media
            // snapshot and immediately restore any surviving kind, in order.
            send_event("disconnected");
            if (!audio_streams.empty()) { send_event("audio"); emitted_media = true; }
            if (!video_streams.empty()) { send_event("video"); emitted_media = true; }
        }
    }
}

extern "C" void magnolie_receiver_error(const char *code) {
    std::lock_guard<std::mutex> lock(state_mutex);
    if (failed) return;
    failed = true;
    pending_pin[0] = '\0';
    send_event("error", known_error(code) ? code : "receiver_internal");
}
