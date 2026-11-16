#!/bin/bash
# Builds the Mac program "CCU eBay Reports" (one file; it builds the requested-fields CSV) from ccu_ebay_app.py.
# Keep this file next to the .py files (unzip "CCU eBay Reports - Mac build kit.zip") and double-click it,
# or run:  bash "Build Mac eBay App.command"
# Needs Python 3.10+ (python.org recommended). Takes 1-2 minutes; the internet is used only to download the
# build tool (PyInstaller) and certifi from PyPI. config.yaml is NOT put inside the program.
# The program only runs on Macs with the same chip type as this one (Apple silicon or Intel).
set -euo pipefail
cd "$(dirname "$0")"
NAME="CCU eBay Reports"
for f in ccu_ebay_app.py ccu_ebay_report.py requested_fields_report.py; do
  [ -f "$f" ] || { echo "Missing $f - keep this file in the same folder as the eBay scripts."; read -r -p "Press Return to close."; exit 1; }
done

PY=""
for c in /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys, venv; assert sys.version_info >= (3, 10)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "No suitable Python found. Install the latest Python 3 for macOS from https://www.python.org/downloads/ and run this again."
  read -r -p "Press Return to close."; exit 1
fi
echo "Using $("$PY" --version) at $PY ($(uname -m))"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
"$PY" -m venv "$WORK/venv"
"$WORK/venv/bin/python" -m pip install -q --disable-pip-version-check pyinstaller certifi
"$WORK/venv/bin/python" -m PyInstaller --noconfirm --onefile --console --name "$NAME" --hidden-import certifi \
  --distpath "$WORK/dist" --workpath "$WORK/build" --specpath "$WORK" ccu_ebay_app.py

rm -f "$NAME"
mv "$WORK/dist/$NAME" .
chmod +x "$NAME"
echo
echo "Done: $(pwd)/$NAME"
echo "Double-click it to run (it opens in Terminal). Keep config.yaml next to it, or in Downloads / Documents."
echo "On another Mac: the first time, right-click it > Open > Open (it is not signed by Apple)."
open -R "$NAME"
read -r -p "Press Return to close."
