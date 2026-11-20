/* Private #727 fixture. Exposes 2 existing outputs, then adds and removes one
 * selected output over a socketpair. It never creates a Wayland listener. */
#include <stdlib.h>
#include <unistd.h>
#include <wayland-server.h>

struct fixture {
    struct wl_display *display;
    struct wl_global *other, *selected;
};

static void release_output(struct wl_client *client, struct wl_resource *resource)
{
    (void)client;
    wl_resource_destroy(resource);
}

static const struct wl_output_interface output_methods = { .release = release_output };

static void bind_output(struct wl_client *client, void *data, uint32_t version, uint32_t id)
{
    struct wl_resource *resource = wl_resource_create(client, &wl_output_interface, version, id);
    if (!resource) {
        wl_client_post_no_memory(client);
        return;
    }
    wl_resource_set_implementation(resource, &output_methods, NULL, NULL);
    wl_output_send_name(resource, data);
    wl_output_send_done(resource);
}

static struct wl_global *add_output(struct fixture *fixture, char *name)
{
    return wl_global_create(fixture->display, &wl_output_interface, 4, name, bind_output);
}

static int step(int fd, uint32_t mask, void *data)
{
    (void)mask;
    struct fixture *fixture = data;
    char command;
    if (read(fd, &command, 1) == 1) {
        switch (command) {
        case '+':
            fixture->selected = add_output(fixture, "Virtual-virtual-xdp-kde-magnolie-1");
            if (fixture->selected) return 0;
            break;
        case 'o':
            if (fixture->other) {
                wl_global_destroy(fixture->other);
                fixture->other = NULL;
                return 0;
            }
            break;
        case '-':
            if (fixture->selected) {
                wl_global_destroy(fixture->selected);
                fixture->selected = NULL;
                return 0;
            }
            break;
        }
    }
    wl_display_terminate(fixture->display);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    struct fixture fixture = { .display = wl_display_create() };
    if (!fixture.display) return 2;
    fixture.other = add_output(&fixture, "HDMI-A-1");
    struct wl_event_source *input = wl_event_loop_add_fd(wl_display_get_event_loop(fixture.display),
                                                        0, WL_EVENT_READABLE, step, &fixture);
    int rc = 2;
    if (input && fixture.other && add_output(&fixture, "eDP-1") && wl_client_create(fixture.display, atoi(argv[1]))) {
        wl_display_run(fixture.display);
        rc = 0;
    }
    if (input) wl_event_source_remove(input);
    wl_display_destroy_clients(fixture.display);
    wl_display_destroy(fixture.display);
    return rc;
}
