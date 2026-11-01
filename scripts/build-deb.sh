#!/usr/bin/env bash
# Build a native Debian package for Spaced Monitor with dpkg-deb (no debhelper, no systemd).
# Usage: scripts/build-deb.sh
set -euo pipefail
cd "$(dirname "$0")/.."

version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' spaced_monitor/__init__.py)
if [ -z "$version" ]; then
    echo "FAIL: could not read version from spaced_monitor/__init__.py" >&2
    exit 1
fi

pkg="spaced-monitor"
stage="build/deb/${pkg}_${version}_all"
deb="build/${pkg}_${version}_all.deb"

rm -rf "$stage" "$deb"
mkdir -p "$stage/DEBIAN"

# Python package (no tests, no __pycache__).
mkdir -p "$stage/usr/lib/${pkg}"
cp -r spaced_monitor "$stage/usr/lib/${pkg}/spaced_monitor"
find "$stage/usr/lib/${pkg}" -name __pycache__ -prune -exec rm -rf {} +

# Launcher.
mkdir -p "$stage/usr/bin"
cp bin/spaced-monitor "$stage/usr/bin/spaced-monitor"
chmod 0755 "$stage/usr/bin/spaced-monitor"

# Desktop entry and icon.
mkdir -p "$stage/usr/share/applications"
cp packaging/org.spacedlinux.Monitor.desktop "$stage/usr/share/applications/"
mkdir -p "$stage/usr/share/icons/hicolor/scalable/apps"
cp packaging/org.spacedlinux.Monitor.svg "$stage/usr/share/icons/hicolor/scalable/apps/"

# Copyright notice.
mkdir -p "$stage/usr/share/doc/${pkg}"
cp LICENSE "$stage/usr/share/doc/${pkg}/LICENSE"
cat > "$stage/usr/share/doc/${pkg}/copyright" <<'EOF'
Format: GPL-3.0-or-later

Spaced Monitor is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License, version 3 or later,
as published by the Free Software Foundation.

This program includes code derived from Proxmox VE / PXVIRT, which is
licensed under the GNU Affero General Public License, version 3 (AGPLv3).
Upstream copyright notices are kept intact. "Proxmox" is a trademark and
is not used as a brand name here.

The full text of GPL-3.0-or-later is in /usr/share/doc/spaced-monitor/
LICENSE (see the repository LICENSE file).
EOF

# Control metadata.
cat > "$stage/DEBIAN/control" <<EOF
Package: ${pkg}
Version: ${version}
Architecture: all
Section: utils
Priority: optional
Maintainer: Spaced Linux Team
Depends: python3, python3-gi, gir1.2-gtk-3.0, python3-cairo, python3-psutil
Recommends: iproute2
Homepage: https://github.com/crhy/spacedmonitor
Description: See what your computer is doing
 A system monitor for Spaced Linux: CPU, GPU, memory and GPU-memory
 gauges, temperature graphs, disk and network activity, and the programs
 using them, in one easy-to-read GTK 3 window. No systemd.
EOF

# Modes: directories 755, data files 644, launcher 755 (cp keeps source group bits).
find "$stage" -type d -exec chmod 0755 {} +
find "$stage" -type f -exec chmod 0644 {} +
chmod 0755 "$stage/usr/bin/${pkg}"

dpkg-deb --root-owner-group --build "$stage" "$deb"
echo "built: $deb"
