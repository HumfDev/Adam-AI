#!/usr/bin/env bash
# Upload every .py file under ./mcu/<rev>/ to the connected MicroPython board using ampy.
#
# Usage:
#   ./upload_mcu.sh revA                 # auto-detect port, reset after upload
#   ./upload_mcu.sh revB -p /dev/cu.usbXXXX  # explicit port
#   ./upload_mcu.sh revA --no-reset      # skip the soft reset at the end
#   AMPY_PORT=/dev/cu.usbXXXX ./upload_mcu.sh revB
#
# Requires: ampy (pip install adafruit-ampy).

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MCU_ROOT="$SCRIPT_DIR/mcu"

PORT="${AMPY_PORT:-}"
RESET=1
REV=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        revA|revB)
            REV="$1"
            shift
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        --no-reset)
            RESET=0
            shift
            ;;
        -h|--help)
            sed -n '2,10p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

if [[ -z "$REV" ]]; then
    echo "Usage: $(basename "$0") revA|revB [-p PORT] [--no-reset]" >&2
    exit 2
fi

SRC_DIR="$MCU_ROOT/$REV"

if ! command -v ampy >/dev/null 2>&1; then
    echo "Error: ampy not found on PATH. Install with: pip install adafruit-ampy" >&2
    exit 1
fi

if [[ ! -d "$SRC_DIR" ]]; then
    echo "Error: source directory not found: $SRC_DIR" >&2
    exit 1
fi

if [[ -z "$PORT" ]]; then
    # Pick the first USB-ish serial device we find.
    for candidate in /dev/cu.usbmodem* /dev/cu.usbserial* /dev/cu.SLAB_USBtoUART /dev/cu.wchusbserial*; do
        if [[ -e "$candidate" ]]; then
            PORT="$candidate"
            break
        fi
    done
fi

if [[ -z "$PORT" ]]; then
    echo "Error: no serial port found. Pass one with -p /dev/cu.xxx or set AMPY_PORT." >&2
    exit 1
fi

if [[ ! -e "$PORT" ]]; then
    echo "Error: port $PORT does not exist." >&2
    exit 1
fi

shopt -s nullglob
FILES=("$SRC_DIR"/*.py)
shopt -u nullglob

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "Error: no .py files found in $SRC_DIR" >&2
    exit 1
fi

echo "Uploading to $PORT from $SRC_DIR ($REV)"

# Put main.py last so earlier imports exist by the time it runs on reset.
ORDERED=()
MAIN=""
for f in "${FILES[@]}"; do
    base="$(basename "$f")"
    if [[ "$base" == "main.py" ]]; then
        MAIN="$f"
    else
        ORDERED+=("$f")
    fi
done
if [[ -n "$MAIN" ]]; then
    ORDERED+=("$MAIN")
fi

for f in "${ORDERED[@]}"; do
    base="$(basename "$f")"
    echo "  put $base"
    ampy -p "$PORT" put "$f" "$base"
done

if [[ "$RESET" -eq 1 ]]; then
    echo "Resetting board..."
    ampy -p "$PORT" reset
fi

echo "Done."
