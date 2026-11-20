/* Read-only #727 prototype. An explicit, connected FD is the only input.
 * No discovery, reconnection, setting changes or installed entry point. */
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-client.h>

enum { MAX_OUTPUTS = 128, MAX_NAME = 255 };

struct observer;
struct output {
    struct observer *owner;
    struct wl_output *proxy;
    uint32_t id;
    bool emitted;
    char name[MAX_NAME + 1];
};

struct observer {
    bool failed;
    struct output outputs[MAX_OUTPUTS];
};

static void geometry(void *d, struct wl_output *o, int32_t x, int32_t y,
                     int32_t w, int32_t h, int32_t sub, const char *a, const char *b, int32_t t)
{ (void)d; (void)o; (void)x; (void)y; (void)w; (void)h; (void)sub; (void)a; (void)b; (void)t; }
static void mode(void *d, struct wl_output *o, uint32_t f, int32_t w, int32_t h, int32_t r)
{ (void)d; (void)o; (void)f; (void)w; (void)h; (void)r; }
static void scale(void *d, struct wl_output *o, int32_t n) { (void)d; (void)o; (void)n; }
static void description(void *d, struct wl_output *o, const char *s) { (void)d; (void)o; (void)s; }

static void set_name(void *data, struct wl_output *proxy, const char *name)
{
    (void)proxy;
    struct output *output = data;
    size_t len = strlen(name);
    if (!len || len > MAX_NAME || output->name[0]) {
        output->owner->failed = true;
        return;
    }
    for (size_t i = 0; i < len; ++i) {
        if ((unsigned char)name[i] < 32 || (unsigned char)name[i] > 126) {
            output->owner->failed = true;
            return;
        }
    }
    memcpy(output->name, name, len + 1);
}

static void done(void *data, struct wl_output *proxy)
{
    (void)proxy;
    struct output *output = data;
    if (output->owner->failed || output->emitted)
        return;
    if (!output->name[0] || printf("+\t%u\t%s\n", output->id, output->name) < 0 || fflush(stdout)) {
        output->owner->failed = true;
        return;
    }
    output->emitted = true;
}

static const struct wl_output_listener output_listener = {
    .geometry = geometry, .mode = mode, .done = done, .scale = scale,
    .name = set_name, .description = description,
};

static void global(void *data, struct wl_registry *registry, uint32_t id,
                   const char *interface, uint32_t version)
{
    struct observer *observer = data;
    if (observer->failed || strcmp(interface, wl_output_interface.name))
        return;
    if (version >= 4 && id) {
        for (size_t i = 0; i < MAX_OUTPUTS; ++i) {
            struct output *output = &observer->outputs[i];
            if (output->proxy)
                continue;
            *output = (struct output){ .owner = observer, .id = id };
            output->proxy = wl_registry_bind(registry, id, &wl_output_interface, 4);
            if (output->proxy && !wl_output_add_listener(output->proxy, &output_listener, output) &&
                printf("?\t%u\n", id) >= 0 && !fflush(stdout))
                return;
            break;
        }
    }
    observer->failed = true;
}

static void remove_global(void *data, struct wl_registry *registry, uint32_t id)
{
    (void)registry;
    struct observer *observer = data;
    for (size_t i = 0; i < MAX_OUTPUTS; ++i) {
        struct output *output = &observer->outputs[i];
        if (!output->proxy || output->id != id)
            continue;
        if (!output->emitted || printf("-\t%u\n", id) < 0 || fflush(stdout))
            observer->failed = true;
        wl_output_release(output->proxy);
        output->proxy = NULL;
        return;
    }
}

static const struct wl_registry_listener registry_listener = { global, remove_global };

int main(int argc, char **argv)
{
    if (argc != 2)
        return 2;
    errno = 0;
    char *end;
    long fd = strtol(argv[1], &end, 10);
    if (errno || end == argv[1] || *end || fd < 3 || fd > INT_MAX)
        return 2;
    struct wl_display *display = wl_display_connect_to_fd((int)fd);
    if (!display)
        return 2;
    struct observer observer = {0};
    struct wl_registry *registry = wl_display_get_registry(display);
    if (!registry || wl_registry_add_listener(registry, &registry_listener, &observer) ||
        wl_display_roundtrip(display) < 0 || observer.failed || wl_display_roundtrip(display) < 0)
        observer.failed = true;
    for (size_t i = 0; i < MAX_OUTPUTS; ++i)
        if (observer.outputs[i].proxy && !observer.outputs[i].emitted)
            observer.failed = true;
    if (!observer.failed && fputs("ready\n", stdout) >= 0 && !fflush(stdout)) {
        while (!observer.failed && wl_display_dispatch(display) >= 0) {}
    }
    for (size_t i = 0; i < MAX_OUTPUTS; ++i)
        if (observer.outputs[i].proxy)
            wl_output_destroy(observer.outputs[i].proxy);
    if (registry)
        wl_registry_destroy(registry);
    wl_display_disconnect(display);
    return 1; /* A lost observer must not look like successful teardown. */
}
