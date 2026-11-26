/* #802: isolated CPython entry point for the signed ImportPython.app helper.
 *
 * Link this only after CPython's normal build, with its own interpreter link
 * flags and static core. The stock build interpreter must remain unchanged.
 * The executable determines every runtime path; argv, cwd and environment
 * never select an interpreter or add a module directory.
 */
#define PY_SSIZE_T_CLEAN
#include "Python.h"

#include <limits.h>
#include <mach-o/dyld.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define MAGNOLIE_STRING_VALUE(value) #value
#define MAGNOLIE_STRING(value) MAGNOLIE_STRING_VALUE(value)
#define MAGNOLIE_PYTHON_SERIES \
    MAGNOLIE_STRING(PY_MAJOR_VERSION) "." MAGNOLIE_STRING(PY_MINOR_VERSION)

static int
real_directory(const char *path)
{
    char resolved[PATH_MAX];
    struct stat info;
    return realpath(path, resolved) != NULL && strcmp(path, resolved) == 0 &&
           stat(path, &info) == 0 && S_ISDIR(info.st_mode);
}

static int
runtime_paths(char *executable, char *prefix, char *stdlib, char *plugins)
{
    char reported[PATH_MAX];
    uint32_t capacity = sizeof(reported);
    const char suffix[] = "/Contents/MacOS/python" MAGNOLIE_PYTHON_SERIES;
    const char executable_suffix[] = "/MacOS/python" MAGNOLIE_PYTHON_SERIES;

    if (_NSGetExecutablePath(reported, &capacity) != 0 ||
        realpath(reported, executable) == NULL) {
        return 0;
    }
    size_t length = strlen(executable);
    if (length <= sizeof(suffix) - 1 ||
        strcmp(executable + length - (sizeof(suffix) - 1), suffix) != 0) {
        return 0;
    }
    size_t prefix_length = length - (sizeof(executable_suffix) - 1);
    memcpy(prefix, executable, prefix_length);
    prefix[prefix_length] = '\0';

    int stdlib_length = snprintf(stdlib, PATH_MAX, "%s/Resources/lib/python%s",
                                 prefix, MAGNOLIE_PYTHON_SERIES);
    int plugins_length = snprintf(plugins, PATH_MAX, "%s/PlugIns", prefix);
    return stdlib_length > 0 && stdlib_length < PATH_MAX &&
           plugins_length > 0 && plugins_length < PATH_MAX &&
           real_directory(stdlib) && real_directory(plugins);
}

int
main(int argc, char **argv)
{
    char executable[PATH_MAX], prefix[PATH_MAX];
    char stdlib[PATH_MAX], plugins[PATH_MAX];
    if (!runtime_paths(executable, prefix, stdlib, plugins)) {
        fputs("ImportPython: incomplete or linked helper runtime.\n", stderr);
        return 1;
    }

    /* CPython's macOS getpath also reads these launcher overrides outside its
     * normal use_environment check. They must not replace sys.executable. */
    if (unsetenv("PYTHONEXECUTABLE") != 0 || unsetenv("__PYVENV_LAUNCHER__") != 0) {
        fputs("ImportPython: could not isolate launcher configuration.\n", stderr);
        return 1;
    }

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.parse_argv = 1;
    config.site_import = 0;
    config.write_bytecode = 0;
    config.install_signal_handlers = 1;
    config.configure_c_stdio = 1;

    /* Set argv first: it participates in preinitialization. Reading it once
     * preserves ordinary -c / script arguments and Python's exit statuses. */
    PyStatus status = PyConfig_SetBytesArgv(&config, argc, argv);
    if (PyStatus_Exception(status)) {
        goto exception;
    }
    status = PyConfig_Read(&config);
    if (PyStatus_Exception(status)) {
        goto exception;
    }

    config.isolated = 1;
    config.use_environment = 0;
    config.user_site_directory = 0;
    config.safe_path = 1;
    config.site_import = 0;
    config.write_bytecode = 0;

    wchar_t **prefix_fields[] = {
        &config.prefix, &config.base_prefix,
        &config.exec_prefix, &config.base_exec_prefix
    };
    for (size_t index = 0; index < sizeof(prefix_fields) / sizeof(prefix_fields[0]); ++index) {
        status = PyConfig_SetBytesString(&config, prefix_fields[index], prefix);
        if (PyStatus_Exception(status)) {
            goto exception;
        }
    }
    wchar_t **executable_fields[] = {
        &config.program_name, &config.executable, &config.base_executable
    };
    for (size_t index = 0; index < sizeof(executable_fields) / sizeof(executable_fields[0]); ++index) {
        status = PyConfig_SetBytesString(&config, executable_fields[index], executable);
        if (PyStatus_Exception(status)) {
            goto exception;
        }
    }
    status = PyConfig_SetBytesString(&config, &config.stdlib_dir, stdlib);
    if (PyStatus_Exception(status)) {
        goto exception;
    }
    wchar_t *wide_plugins = Py_DecodeLocale(plugins, NULL);
    if (wide_plugins == NULL) {
        status = PyStatus_Error("cannot decode the internal extension path");
        goto exception;
    }
    wchar_t *module_paths[] = {config.stdlib_dir, wide_plugins};
    status = PyConfig_SetWideStringList(&config, &config.module_search_paths,
                                      2, module_paths);
    PyMem_RawFree(wide_plugins);
    if (PyStatus_Exception(status)) {
        goto exception;
    }
    config.module_search_paths_set = 1;

    status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) {
        goto exception;
    }
    PyConfig_Clear(&config);
    return Py_RunMain();

exception:
    PyConfig_Clear(&config);
    if (PyStatus_IsExit(status)) {
        return status.exitcode;
    }
    Py_ExitStatusException(status);
    return 1;
}
