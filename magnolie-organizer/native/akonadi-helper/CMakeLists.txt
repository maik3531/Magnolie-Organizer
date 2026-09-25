cmake_minimum_required(VERSION 3.16)

project(magnolie-akonadi-helper VERSION 2.0.23 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(ECM REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})

# Prefer the current Qt/KDE PIM stack, but retain support for distributions
# which still ship the Qt 5 based Akonadi libraries.
find_package(KPim6Akonadi CONFIG QUIET)
find_package(KF6CalendarCore CONFIG QUIET)
find_package(KF6Contacts CONFIG QUIET)

if(TARGET KPim6::AkonadiCore AND TARGET KF6::CalendarCore AND
   TARGET KF6::Contacts)
    find_package(Qt6 REQUIRED COMPONENTS Core DBus)
    set(QT_CORE Qt6::Core Qt6::DBus)
    set(AKONADI_CORE KPim6::AkonadiCore)
    set(CALENDAR_CORE KF6::CalendarCore)
    set(CONTACTS_CORE KF6::Contacts)
    set(KDE_STACK "KF6")
else()
    # A host may provide Qt 6 without the matching PIM stack. KDE's KF5
    # package files use this variable when both Qt generations are visible.
    find_package(Qt5 5.15 REQUIRED COMPONENTS Core DBus)
    find_package(KPim5Akonadi CONFIG QUIET)
    if(NOT TARGET KPim5::AkonadiCore)
        find_package(KF5Akonadi CONFIG REQUIRED)
    endif()
    find_package(KF5CalendarCore CONFIG REQUIRED)
    find_package(KF5Contacts CONFIG REQUIRED)

    set(QT_CORE Qt5::Core Qt5::DBus)
    if(TARGET KPim5::AkonadiCore)
        set(AKONADI_CORE KPim5::AkonadiCore)
    elseif(TARGET KF5::AkonadiCore)
        set(AKONADI_CORE KF5::AkonadiCore)
    else()
        message(FATAL_ERROR "No KF5 AkonadiCore target was exported")
    endif()
    set(CALENDAR_CORE KF5::CalendarCore)
    set(CONTACTS_CORE KF5::Contacts)
    set(KDE_STACK "KF5")
endif()

message(STATUS "Building magnolie-akonadi-helper with ${KDE_STACK}")

add_executable(magnolie-akonadi-helper main.cpp)
target_link_libraries(magnolie-akonadi-helper PRIVATE
    ${QT_CORE}
    ${AKONADI_CORE}
    ${CALENDAR_CORE}
    ${CONTACTS_CORE}
)

include(GNUInstallDirs)
install(TARGETS magnolie-akonadi-helper
    RUNTIME DESTINATION ${CMAKE_INSTALL_LIBEXECDIR}/magnolie-organizer)

include(CTest)
if(BUILD_TESTING)
    add_executable(serialization-test serialization-test.cpp)
    target_link_libraries(serialization-test PRIVATE
        ${QT_CORE} ${AKONADI_CORE} ${CALENDAR_CORE} ${CONTACTS_CORE})
    add_test(NAME serialization COMMAND serialization-test)
endif()
