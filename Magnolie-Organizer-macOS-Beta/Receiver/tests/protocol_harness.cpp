// SPDX-License-Identifier: GPL-3.0-or-later
#include "receiver_protocol.h"
#include "receiver_registration.h"
#include <csignal>
#include <cstdio>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

int main(int argc, char **argv) {
    if (argc > 2 && std::string(argv[1]) == "registry") {
        std::vector<std::string> keys;
        if (!magnolie_load_registration(argv[2], keys)) return 9;
        std::printf("%zu\n", keys.size());
        return 0;
    }
    if (argc > 3 && std::string(argv[1]) == "save") {
        return magnolie_save_registration(argv[2], argv[3]) ? 0 : 9;
    }
    if (!magnolie_receiver_initialize()) return 70;
    if (argc > 1 && std::string(argv[1]) == "eof") {
        // The real host must die even if a native framework ignores SIGTERM.
        signal(SIGTERM, SIG_IGN);
        magnolie_receiver_ready();
        for (;;) pause();
    }
    if (argc > 1 && std::string(argv[1]) == "invalid_pin") {
        magnolie_receiver_pin("12\"4");
        return 1;
    }
    if (argc > 1 && std::string(argv[1]) == "bad_error") {
        magnolie_receiver_error("remote supplied \"name\"");
        magnolie_receiver_ready();
        return 0;
    }
    static int first, second;
    if (argc > 1 && std::string(argv[1]) == "overlapping") {
        magnolie_receiver_ready();
        magnolie_receiver_media(1, &first);
        magnolie_receiver_media(1, &second);
        magnolie_receiver_media(0, &first);
        magnolie_receiver_stream_ended(1, &first);
        magnolie_receiver_stream_ended(0, &first);
        magnolie_receiver_stream_ended(1, &second);
        return 0;
    }
    if (argc > 1 && std::string(argv[1]) == "pair_cancel") {
        magnolie_receiver_ready();
        magnolie_receiver_connection_opened();
        magnolie_receiver_connection_opened();
        magnolie_receiver_pin("0042");
        magnolie_receiver_connection_closed();
        magnolie_receiver_connection_closed();
        magnolie_receiver_connection_closed();
        return 0;
    }
    std::printf("upstream raw log must go to stderr\n");
    magnolie_receiver_pin("0042");
    magnolie_receiver_ready();
    magnolie_receiver_ready();
    magnolie_receiver_media(1, &first);
    magnolie_receiver_media(1, &first);
    magnolie_receiver_media(0, &first);
    magnolie_receiver_stream_ended(1, &first);
    // Ending an unrelated TCP/media connection must not report disconnected.
    magnolie_receiver_stream_ended(0, &second);
    magnolie_receiver_stream_ended(0, &first);
    magnolie_receiver_media(0, &second);
    magnolie_receiver_stream_ended(0, &second);
    return 0;
}
