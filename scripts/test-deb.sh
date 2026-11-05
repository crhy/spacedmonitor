#!/usr/bin/env bash
# Prove the built .deb works: layout, metadata, dependency completeness, and a real
# headless render of the packaged code. Run as a normal user; as root it also does a
# real dpkg install/verify/purge cycle.
# Usage: bash scripts/test-deb.sh
set -euo pipefail
cd "$(dirname "$0")/.."

fail() { echo "FAIL: $*"; exit 1; }
ok()   { echo "OK: $*"; }

version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' spaced_monitor/__init__.py)
[ -n "$version" ] || fail "could not read version from spaced_monitor/__init__.py"

pkg="spaced-monitor"
deb="build/${pkg}_${version}_all.deb"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

[ -f "$deb" ] || bash scripts/build-deb.sh >/dev/null
ok "using $deb ($(wc -c < "$deb") bytes)"

# --- 1. Maintainer scripts: only the reviewed RAPL postinst (chmod 0444 on energy_uj). ---
mkdir "$tmp/ctrl"
dpkg-deb -e "$deb" "$tmp/ctrl"
extra=$(find "$tmp/ctrl" -type f -not -name control -not -name postinst -not -name md5sums | grep -c . || true)
[ "$extra" -eq 0 ] || fail "unexpected maintainer scripts: only the RAPL postinst is allowed"
if [ -f "$tmp/ctrl/postinst" ]; then
    cmp -s "$tmp/ctrl/postinst" packaging/postinst || fail "postinst differs from packaging/postinst"
    ok "postinst is the reviewed RAPL permission script"
else
    ok "no maintainer scripts"
fi

# --- 2. Layout: everything the launcher and the desktop entry need is inside. ---
listing=$(dpkg-deb -c "$deb")
for path in \
    "./usr/bin/spaced-monitor" \
    "./usr/lib/${pkg}/spaced_monitor/__init__.py" \
    "./usr/lib/${pkg}/spaced_monitor/app.py" \
    "./usr/lib/${pkg}/spaced_monitor/collect.py" \
    "./usr/lib/${pkg}/spaced_monitor/widgets.py" \
    "./usr/share/applications/org.spacedlinux.Monitor.desktop" \
    "./usr/share/icons/hicolor/scalable/apps/org.spacedlinux.Monitor.svg" \
    "./usr/share/doc/${pkg}/copyright"; do
    grep -qF "$path" <<<"$listing" || fail "missing from package: $path"
done
junk=$(grep -E "systemd|__pycache__|/usr/lib/python3|^\./etc/|tests/|\.git" <<<"$listing" || true)
[ -z "$junk" ] || fail "package contains junk: $junk"
loose=$(dpkg-deb -c "$deb" | awk '$1 ~ /^.....w/ {print $1, $NF}' || true)
[ -z "$loose" ] || fail "group-writable paths in the package: $loose"
ok "layout complete, no junk, modes 755/644"

# --- 3. Control metadata: version matches the source, deps and description present. ---
control=$(dpkg-deb -f "$deb")
field() { sed -n "s/^$1: //p" <<<"$control" | head -1; }
[ "$(field Version)" = "$version" ] || fail "control Version != __version__"
[ "$(field Package)" = "$pkg" ] || fail "wrong package name"
[ "$(field Architecture)" = "all" ] || fail "Architecture should be all"
[ -n "$(field Depends)" ] || fail "no Depends"
grep -q "^Description" <<<"$control" || fail "no Description"
if grep -qiE "systemd|systemctl" <<<"$(field Depends)"; then fail "systemd in Depends"; fi
ok "control metadata (Version $(field Version))"

# --- 4. The desktop entry validates and points at packaged paths. ---
mkdir "$tmp/pfx"
dpkg-deb -x "$deb" "$tmp/pfx"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$tmp/pfx/usr/share/applications/org.spacedlinux.Monitor.desktop" \
        || fail "desktop-file-validate rejected the .desktop file"
    ok "desktop entry validates"
    exec_line=$(grep -m1 '^Exec=' "$tmp/pfx/usr/share/applications/org.spacedlinux.Monitor.desktop" | cut -d= -f2-)
    [ "$exec_line" = "spaced-monitor" ] || fail "Exec= should be spaced-monitor, got: $exec_line"
    icon=$(grep -m1 '^Icon=' "$tmp/pfx/usr/share/applications/org.spacedlinux.Monitor.desktop" | cut -d= -f2-)
    [ -f "$tmp/pfx/usr/share/icons/hicolor/scalable/apps/${icon}.svg" ] \
        || fail "Icon= $icon has no matching file in the package"
    ok "Exec= and Icon= resolve inside the package"
else
    ok "desktop-file-validate not installed, skipped"
fi

# --- 5. The launcher works from the extracted tree with a scrubbed environment. ---
out=$(env -i PATH=/usr/bin:/bin HOME="$tmp" "$tmp/pfx/usr/bin/spaced-monitor" --version)
[ "$out" = "spaced-monitor $version" ] || fail "--version from extracted tree: got '$out'"
ok "launcher runs from an extracted prefix with env -i"

# --- 6. Dependency completeness: every non-stdlib import must be declared. ---
missing=$(python3 - "$tmp/pfx/usr/lib/${pkg}/spaced_monitor" <<'PY'
import ast, sys, pathlib
root = pathlib.Path(sys.argv[1])
stdlib = set(sys.stdlib_module_names)
local = {"spaced_monitor"}
mods = set()
for path in root.glob("*.py"):
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
undeclared = sorted(m for m in mods if m not in stdlib and m not in local)
print("\n".join(str(m) for m in undeclared))
PY
)
depends=$(dpkg-deb -f "$deb" Depends)
for entry in $missing; do
    mod=${entry%% *}
    case "$mod" in
        gi)     want=python3-gi ;;
        psutil) want=python3-psutil ;;
        cairo)  want=python3-cairo ;;
        *)      want="" ;;
    esac
    [ -n "$want" ] || fail "import not understood: $mod (add it to the provider map)"
    grep -qE "(^|, )${want}( |,|$)" <<<"$depends" || fail "module imports '$mod' but Depends lacks $want"
done
# Cairo drawing from a GTK "draw" handler needs the GI<->cairo bridge (gi._gi_cairo),
# which only python3-gi-cairo ships; without it no gauge or graph can draw.
if grep -rqs '"draw"' "$tmp/pfx/usr/lib/${pkg}/spaced_monitor"; then
    grep -qE "(^|, )python3-gi-cairo( |,|$)" <<<"$depends" \
        || fail "draw handlers need python3-gi-cairo in Depends"
fi
ok "every import is declared in Depends ($depends)"

# --- 7. A real headless render of the packaged code, with no repo on sys.path. ---
cat > "$tmp/render.py" <<'PY'
import sys
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, GLib, Gdk

from spaced_monitor import collect, theme as theme_mod
from spaced_monitor.app import MonitorWindow

out = sys.argv[1]
pal = theme_mod.palette("dark")
theme_mod.apply_css(pal)
win = MonitorWindow(sampler=collect.Sampler().sample, refresh_ms=1000, pal=pal)
win.set_default_size(1200, 800)
win.show_all()
win.show_tab_only()
win.start_worker()

def grab():
    gdk_win = win.get_window()
    if gdk_win is None:
        return False
    w = win.get_allocated_width()
    h = win.get_allocated_height()
    if w < 1 or h < 1:
        return False
    pixbuf = Gdk.pixbuf_get_from_window(gdk_win, 0, 0, w, h)
    if pixbuf is not None:
        result = pixbuf.save_to_bufferv("png", [])
        if result[0]:
            with open(out, "wb") as f:
                f.write(result[1])
    Gtk.main_quit()
    return False

GLib.timeout_add_seconds(4, grab)
Gtk.main()
win.close()
PY
render_out="$tmp/render.png"
timeout 90 xvfb-run -a env PYTHONPATH="$tmp/pfx/usr/lib/${pkg}" /usr/bin/python3 "$tmp/render.py" "$render_out" >"$tmp/render.log" 2>&1 \
    || { tail -20 "$tmp/render.log"; fail "packaged app failed to run headless"; }
[ -s "$render_out" ] && [ "$(wc -c < "$render_out")" -gt 10240 ] \
    || fail "headless render produced no real image ($(wc -c < "$render_out" 2>/dev/null || echo 0) bytes)"
ok "packaged code renders a real window headless ($(wc -c < "$render_out") bytes)"

# --- 8. The samplers work with no shell tools on PATH (ip, nvidia-smi missing). ---
mkdir "$tmp/emptybin"
sample_report=$(env -i PATH="$tmp/emptybin" HOME="$tmp" /usr/bin/python3 - "$tmp/pfx/usr/lib/${pkg}" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from spaced_monitor import collect
snap = collect.Sampler().sample()
print(f"mem_total={snap.memory.total // (1024 * 1024)}MB "
      f"uptime={int(snap.uptime_s)}s "
      f"fs={len(snap.filesystems)} ifaces={len(snap.interfaces)} "
      f"gpu={snap.gpu is not None} temps={len(snap.temperatures)}")
PY
) || { fail "samplers crashed with no shell tools on PATH"; }
case "$sample_report" in
    *"mem_total=0MB"*) fail "samplers reported no memory data: $sample_report" ;;
esac
ok "samplers degrade and still report data ($sample_report)"
# --- 9. As root: a real dpkg install / verify / purge cycle. ---
if [ "$(id -u)" = 0 ]; then
    dpkg -i "$deb" >/dev/null || fail "dpkg -i failed"
    command -v spaced-monitor >/dev/null || fail "spaced-monitor not on PATH after install"
    [ "$(spaced-monitor --version)" = "spaced-monitor $version" ] || fail "installed launcher wrong version"
    dpkg -V spaced-monitor >/dev/null 2>&1 || fail "dpkg -V reports modified files"
    spaced-monitor --version >/dev/null </dev/null || fail "installed app cannot run headless"
    apt purge -y spaced-monitor >/dev/null 2>&1 || dpkg --purge spaced-monitor >/dev/null || fail "purge failed"
    dpkg -l spaced-monitor 2>/dev/null | grep -q "^ii" && fail "purge left the package installed"
    [ -z "$(find /usr/lib/spaced-monitor /usr/share/doc/spaced-monitor -mindepth 0 2>/dev/null)" ] \
        || fail "purge left files behind (the app wrote into the system prefix)"
    ok "dpkg install / verify / purge cycle, nothing left behind"
else
    ok "run as non-user: dpkg install cycle skipped (rerun with sudo to include it)"
fi

echo "All deb checks passed."
