Name:           magnolie-organizer-akonadi
Version:        1.0.0
Release:        1%{?dist}
Summary:        KDE system-account bridge for Magnolie Organizer
License:        GPL-3.0-or-later
URL:            https://gitlab.com/maik3531/mint-forgs
Source0:        %{name}-%{version}.tar.xz

BuildRequires:  cmake
BuildRequires:  gcc-c++
BuildRequires:  extra-cmake-modules
BuildRequires:  cmake(Qt6Core)
BuildRequires:  cmake(KPim6Akonadi)
BuildRequires:  cmake(KF6CalendarCore)
BuildRequires:  cmake(KF6Contacts)
Requires:       akonadi-server
Requires:       magnolie-organizer >= 2.0.17
Recommends:     kdepim-runtime

%description
This optional helper lets Magnolie Organizer use calendars and address books
already configured in KDE Akonadi. It never receives account credentials.

%prep
%autosetup

%build
%cmake
%cmake_build

%install
%cmake_install

%files
%license debian/copyright
%dir %{_libexecdir}/magnolie-organizer
%{_libexecdir}/magnolie-organizer/magnolie-akonadi-helper

%changelog
* Tue Sep 01 2026 Maik Walter <maik3531@gmail.com> - 1.0.0-1
- Initial optional Akonadi calendar and address-book bridge.
