# FindOpenSSL gained OpenSSL 3 support in CMake 3.18.
cmake_minimum_required(VERSION 3.18)
project(MagnolieAirPlayReceiver LANGUAGES C CXX)

if(NOT APPLE)
    message(FATAL_ERROR "The bundled receiver needs the native macOS SDK. Portable IPC tests use tests/test_receiver.py.")
endif()

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Never use upstream's -march=native for a distributable Intel build. Dependency
# discovery deliberately preserves the caller's isolated PKG_CONFIG_LIBDIR.
if(NOT MAGNOLIE_AIRPLAY_SDK_ROOT OR NOT IS_DIRECTORY "${MAGNOLIE_AIRPLAY_SDK_ROOT}")
    message(FATAL_ERROR "Set MAGNOLIE_AIRPLAY_SDK_ROOT to the explicitly staged receiver SDK.")
endif()
get_filename_component(RECEIVER_SDK "${MAGNOLIE_AIRPLAY_SDK_ROOT}" REALPATH)
function(require_sdk_path path)
    get_filename_component(resolved "${path}" REALPATH)
    string(FIND "${resolved}/" "${RECEIVER_SDK}/" at)
    if(NOT at EQUAL 0)
        message(FATAL_ERROR "Receiver dependency escapes the staged SDK: ${path}")
    endif()
endfunction()
find_package(PkgConfig REQUIRED)
set(OPENSSL_USE_STATIC_LIBS FALSE)
find_package(OpenSSL 3.0 REQUIRED COMPONENTS Crypto)
require_sdk_path("${OPENSSL_CRYPTO_LIBRARY}")
require_sdk_path("${OPENSSL_INCLUDE_DIR}")
if(NOT OPENSSL_CRYPTO_LIBRARY MATCHES "\\.dylib$")
    message(FATAL_ERROR "Receiver requires SDK-local dynamic OpenSSL 3 for the audited bundle closure.")
endif()
pkg_check_modules(PLIST REQUIRED IMPORTED_TARGET libplist-2.0>=2.0)
pkg_check_modules(GST REQUIRED IMPORTED_TARGET
    gstreamer-1.0>=1.22 gstreamer-sdp-1.0 gstreamer-video-1.0 gstreamer-app-1.0 glib-2.0)
foreach(dependency PLIST GST)
    foreach(directory IN LISTS ${dependency}_INCLUDE_DIRS ${dependency}_LIBRARY_DIRS)
        require_sdk_path("${directory}")
    endforeach()
    foreach(library IN LISTS ${dependency}_LINK_LIBRARIES)
        if(IS_ABSOLUTE "${library}")
            if(NOT library MATCHES "^/usr/lib/" AND NOT library MATCHES "^/System/Library/")
                require_sdk_path("${library}")
                if(library MATCHES "\\.a$")
                    message(FATAL_ERROR "Static external libraries bypass bundle closure auditing: ${library}")
                endif()
            endif()
        elseif(NOT library MATCHES "^(m|pthread|dl|c|System)$")
            message(FATAL_ERROR "pkg-config returned an unresolved receiver library: ${library}")
        endif()
    endforeach()
endforeach()
find_package(Threads REQUIRED)

set(UPSTREAM "${CMAKE_CURRENT_SOURCE_DIR}/vendor/UxPlay")

add_library(magnolie-receiver-support STATIC receiver_protocol.cpp receiver_registration.cpp)
target_include_directories(magnolie-receiver-support PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(magnolie-receiver-support PUBLIC Threads::Threads)

add_library(magnolie-llhttp STATIC
    "${UPSTREAM}/lib/llhttp/api.c" "${UPSTREAM}/lib/llhttp/http.c" "${UPSTREAM}/lib/llhttp/llhttp.c")
target_include_directories(magnolie-llhttp PUBLIC "${UPSTREAM}/lib/llhttp")

add_library(magnolie-playfair STATIC
    "${UPSTREAM}/lib/playfair/playfair.c" "${UPSTREAM}/lib/playfair/hand_garble.c"
    "${UPSTREAM}/lib/playfair/modified_md5.c" "${UPSTREAM}/lib/playfair/omg_hax.c"
    "${UPSTREAM}/lib/playfair/sap_hash.c")
target_include_directories(magnolie-playfair PUBLIC "${UPSTREAM}/lib/playfair")

set(AIRPLAY_FILES airplay_video byteutils compat crypto dnssd fairplay_playfair
    http_request http_response httpd logger mirror_buffer netutils pairing raop
    raop_buffer raop_ntp raop_rtp raop_rtp_mirror srp utils)
set(AIRPLAY_SOURCES "")
foreach(name IN LISTS AIRPLAY_FILES)
    list(APPEND AIRPLAY_SOURCES "${UPSTREAM}/lib/${name}.c")
endforeach()
add_library(magnolie-airplay STATIC ${AIRPLAY_SOURCES})
target_include_directories(magnolie-airplay PUBLIC "${UPSTREAM}/lib")
target_compile_definitions(magnolie-airplay PRIVATE NOHOLD OPENSSL_API_COMPAT=0x10101000L)
if(PLIST_VERSION VERSION_GREATER_EQUAL "2.1")
    target_compile_definitions(magnolie-airplay PRIVATE PLIST_210)
endif()
if(PLIST_VERSION VERSION_GREATER_EQUAL "2.3")
    target_compile_definitions(magnolie-airplay PRIVATE PLIST_230)
endif()
target_link_libraries(magnolie-airplay PUBLIC magnolie-playfair magnolie-llhttp
    magnolie-receiver-support OpenSSL::Crypto PkgConfig::PLIST Threads::Threads)

add_library(magnolie-renderers STATIC "${UPSTREAM}/renderers/audio_renderer.c"
    "${UPSTREAM}/renderers/video_renderer.c" "${UPSTREAM}/renderers/mux_renderer.c")
target_include_directories(magnolie-renderers PUBLIC "${UPSTREAM}/renderers")
target_link_libraries(magnolie-renderers PUBLIC magnolie-airplay PkgConfig::GST)
# Upstream's compatibility function is needed only with old GLib installations.
pkg_check_modules(GLIB_CURRENT glib-2.0>=2.68)
if(NOT GLIB_CURRENT_FOUND)
    target_compile_definitions(magnolie-renderers PRIVATE NEED_G_STRING_REPLACE)
endif()

add_executable(magnolie-airplay-receiver "${UPSTREAM}/uxplay.cpp")
# gst_macos_main owns Cocoa's main thread; do not call UxPlay in Swift's process.
target_compile_definitions(magnolie-airplay-receiver PRIVATE GST_MACOS)
target_link_libraries(magnolie-airplay-receiver PRIVATE magnolie-renderers)
target_link_options(magnolie-airplay-receiver PRIVATE "-Wl,-headerpad_max_install_names")
set_target_properties(magnolie-airplay-receiver PROPERTIES
    INSTALL_RPATH "@executable_path/../Frameworks/AirPlay"
    BUILD_WITH_INSTALL_RPATH FALSE)

install(TARGETS magnolie-airplay-receiver RUNTIME DESTINATION Helpers)
