#!/usr/bin/env bash
# The gate: every Python file compiles, the unit tests pass, the UI smoke test (if present)
# builds every page headless and saves screenshots to build/screenshots/. Last line on success:
# "All checks passed."
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build/screenshots

mapfile -t py < <(find spaced_monitor tests bin scripts -type f \( -name '*.py' -o -path 'bin/*' \) -not -path '*/__pycache__/*' | sort)
python3 -m py_compile "${py[@]}"
find spaced_monitor tests bin -name __pycache__ -prune -exec rm -rf {} +
echo "OK: ${#py[@]} Python files compile"

mapfile -t sh < <(find scripts -name '*.sh' | sort)
[ "${#sh[@]}" -eq 0 ] || shellcheck "${sh[@]}"
echo "OK: shell scripts pass shellcheck"

timeout 300 python3 -m unittest discover -s tests -t . 2>&1 | tail -n 3
echo "OK: unit tests"

if [ -f tests/ui_smoke.py ]; then
    timeout 180 xvfb-run -a -s "-screen 0 1600x1000x24" python3 tests/ui_smoke.py
    echo "OK: UI smoke test (screenshots in build/screenshots/)"
fi

if [ -f tests/ui_live.py ]; then
    timeout 180 xvfb-run -a -s "-screen 0 2000x1200x24" python3 tests/ui_live.py
    echo "OK: Live UI test (real samplers, real window)"
fi

timeout 60 xvfb-run -a python3 tests/ui_lifecycle.py
echo "OK: application lifecycle (no invisible process after close)"

if [ -f tests/ui_themes.py ]; then
    timeout 600 python3 tests/ui_themes.py
    echo "OK: UI theme tests (screenshots in build/screenshots/)"
fi

bash scripts/build-deb.sh >/dev/null
timeout 600 bash scripts/test-deb.sh | tail -n 1
echo "OK: the .deb builds and passes its own gate (scripts/test-deb.sh)"

if grep -rIl --exclude-dir=.git -e systemd -e systemctl spaced_monitor bin packaging 2>/dev/null; then
    echo "FAIL: systemd reference above (Spaced Linux has no systemd)"; exit 1
fi
echo "All checks passed."
