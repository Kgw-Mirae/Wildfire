#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SRC="1_post_nc.f"
BIN="post_nc"
DOMAIN_INC="../data/Domain/postproc_domain.inc"
BUILD_MARKER=".post_nc.container-build"

FC="${FC:-gfortran}"

if ! command -v "$FC" >/dev/null 2>&1; then
    echo "ERROR: Fortran compiler not found: $FC"
    exit 1
fi

if ! command -v nf-config >/dev/null 2>&1; then
    echo "ERROR: nf-config not found"
    exit 1
fi

if [ ! -f "$SRC" ]; then
    echo "ERROR: Source file not found: $SCRIPT_DIR/$SRC"
    exit 1
fi

if [ ! -f "$DOMAIN_INC" ]; then
    echo "ERROR: Domain include not found: $DOMAIN_INC"
    exit 1
fi

mkdir -p results

needs_build=false

if [ ! -x "$BIN" ]; then
    needs_build=true
elif [ ! -f "$BUILD_MARKER" ]; then
    needs_build=true
elif [ "$SRC" -nt "$BIN" ]; then
    needs_build=true
elif [ "$DOMAIN_INC" -nt "$BIN" ]; then
    needs_build=true
fi

if [ "$needs_build" = true ]; then
    echo ">> building $BIN"
    echo ">> compiler: $(command -v "$FC")"
    echo ">> nf-config: $(command -v nf-config)"

    TMP_BIN="${BIN}.tmp.$$"

    if ! "$FC" \
        -O2 \
        -std=legacy \
        -ffixed-line-length-none \
        $(nf-config --fflags) \
        "$SRC" \
        -o "$TMP_BIN" \
        $(nf-config --flibs); then

        rm -f "$TMP_BIN"
        echo "ERROR: Failed to build $BIN"
        exit 2
    fi

    mv -f "$TMP_BIN" "$BIN"
    chmod 755 "$BIN"
    touch "$BUILD_MARKER"

    echo ">> build completed: $BIN"
else
    echo ">> using existing binary: $BIN"
fi

# 빌드 여부와 관계없이 항상 실행
echo ">> running $BIN"
"./$BIN" "$@"

post_status=$?

if [ "$post_status" -ne 0 ]; then
    echo "ERROR: $BIN failed with exit code $post_status"
    exit "$post_status"
fi

# 인자로 전달한 DAT에 대응하는 NC 확인
if (( $# > 0 )); then
    missing_count=0

    for dat_file in "$@"; do
        dat_name="$(basename "$dat_file")"
        nc_name="${dat_name%.dat}.nc"
        nc_file="results/$nc_name"

        if [ ! -s "$nc_file" ]; then
            echo "ERROR: Expected NetCDF was not produced: $nc_file"
            missing_count=$((missing_count + 1))
        else
            echo ">> produced: $nc_file"
        fi
    done

    if (( missing_count > 0 )); then
        exit 3
    fi
else
    shopt -s nullglob
    nc_files=(results/*.nc)

    if (( ${#nc_files[@]} == 0 )); then
        echo "ERROR: No NetCDF files were produced in $SCRIPT_DIR/results"
        exit 3
    fi
fi

echo ">> nc files:"
ls -lah results/*.nc

echo ">> NetCDF postprocessing completed"
exit 0
