// SPDX-License-Identifier: GPL-3.0-or-later
#include "receiver_registration.h"

#include <algorithm>
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace {
constexpr size_t max_size = 1024 * 1024;
constexpr size_t max_line = 4096;
constexpr size_t max_keys = 1024;

bool private_file(int fd, struct stat &st) {
    return !fstat(fd, &st) && S_ISREG(st.st_mode) && st.st_uid == getuid() &&
        st.st_nlink == 1 && (st.st_mode & 0077) == 0 &&
        st.st_size >= 0 && static_cast<size_t>(st.st_size) <= max_size;
}

bool add_line(const std::string &line, std::vector<std::string> &keys) {
    if (line.size() < 44 || line.size() > max_line ||
        (line.size() > 44 && line[44] != ',')) return false;
    const std::string key = line.substr(0, 44);
    if (!magnolie_valid_registration_key(key)) return false;
    if (std::find(keys.begin(), keys.end(), key) == keys.end()) keys.push_back(key);
    return keys.size() <= max_keys;
}
}

bool magnolie_valid_registration_key(const std::string &key) {
    if (key.size() != 44 || key[43] != '=') return false;
    const std::string alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for (size_t i = 0; i < 43; ++i) if (alphabet.find(key[i]) == std::string::npos) return false;
    // Ed25519 public keys have 32 bytes: the last base64 sextet has two zero bits.
    return (alphabet.find(key[42]) & 3u) == 0;
}

bool magnolie_load_registration(const std::string &path, std::vector<std::string> &keys) {
    keys.clear();
    int fd = open(path.c_str(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return errno == ENOENT;
    struct stat st;
    if (!private_file(fd, st)) { close(fd); return false; }
    char buffer[4096];
    size_t total = 0;
    std::string line;
    bool good = true;
    for (;;) {
        ssize_t count = read(fd, buffer, sizeof(buffer));
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) { good = false; break; }
        if (count == 0) break;
        total += static_cast<size_t>(count);
        if (total > max_size) { good = false; break; }
        for (ssize_t i = 0; i < count; ++i) {
            if (buffer[i] == '\n') {
                if (!add_line(line, keys)) { good = false; break; }
                line.clear();
            } else {
                line.push_back(buffer[i]);
                if (line.size() > max_line) { good = false; break; }
            }
        }
        if (!good) break;
    }
    // A truncated append must not silently grant trust from an incomplete line.
    if (!line.empty()) good = false;
    close(fd);
    if (!good) keys.clear();
    return good;
}

bool magnolie_save_registration(const std::string &path, const std::string &key) {
    if (!magnolie_valid_registration_key(key)) return false;
    int fd = open(path.c_str(), O_WRONLY | O_APPEND | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return false;
    struct stat st;
    if (!private_file(fd, st) || static_cast<size_t>(st.st_size) + 45 > max_size) {
        close(fd); return false;
    }
    const std::string line = key + '\n';
    ssize_t count;
    do { count = write(fd, line.data(), line.size()); } while (count < 0 && errno == EINTR);
    const bool good = count == static_cast<ssize_t>(line.size()) && fsync(fd) == 0;
    close(fd);
    return good;
}
