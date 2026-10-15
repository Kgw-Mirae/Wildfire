#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IN_DIR="${1:-$BASE_DIR/2_moment/results}"
OUT_DIR="$SCRIPT_DIR/results"
POLL_SECONDS="${POSTPROC_POLL_SECONDS:-5}"
STABLE_SECONDS="${POSTPROC_STABLE_SECONDS:-2}"

mkdir -p "$OUT_DIR"

is_ready_for_nc() {
    local dat="$1"
    local base stamp nc size1 size2

    base="$(basename "$dat")"
    stamp="${base#output_}"
    stamp="${stamp%.dat}"
    nc="$OUT_DIR/output_${stamp}.nc"

    if [ -f "$nc" ] && [ ! "$dat" -nt "$nc" ]; then
        return 1
    fi

    size1=$(wc -c < "$dat" 2>/dev/null) || return 1
    sleep "$STABLE_SECONDS"
    size2=$(wc -c < "$dat" 2>/dev/null) || return 1

    [ "$size1" = "$size2" ] && [ "$size1" -gt 0 ]
}

process_pending_once() {
    local dat found=1 failed=0

    for dat in "$IN_DIR"/output_*.dat; do
        [ -e "$dat" ] || continue
        if is_ready_for_nc "$dat"; then
            echo "[POSTNC] converting $dat"
            ( cd "$SCRIPT_DIR" && bash ./0_run_nc.sh "$dat" ) || failed=1
            found=0
        fi
    done

    if [ "$failed" -ne 0 ]; then
        return 2
    fi
    return "$found"
}

if [ "${1:-}" = "--once" ]; then
    shift
    IN_DIR="${1:-$BASE_DIR/2_moment/results}"
    process_pending_once
    status=$?
    if [ "$status" -eq 1 ]; then
        exit 0
    fi
    exit "$status"
fi

echo "[POSTNC] watching $IN_DIR"
echo "[POSTNC] writing nc files to $OUT_DIR"

while true; do
    process_pending_once || true
    sleep "$POLL_SECONDS"
done
