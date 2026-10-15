#!/bin/bash
cd "$(dirname "$0")"

SECONDS=0
PYTHON_BIN="${PYTHON_BIN:-python}"
RDAPS_WORKERS="${RDAPS_WORKERS:-28}"
export RDAPS_VERTICAL_WORKERS="$RDAPS_WORKERS"
export RDAPS_EXTRACT_WORKERS="$RDAPS_WORKERS"

"$PYTHON_BIN" ../apply_domain_config.py
if [ $? -ne 0 ]; then
    echo "[Error] apply_domain_config.py failed!"
    exit 1
fi

echo "[Running] Preparing RDAPS date list ..."
"$PYTHON_BIN" make_rdaps_dates.py
if [ $? -ne 0 ]; then
    echo "[Error] make_rdaps_dates.py failed!"
    exit 1
fi

echo "[Running] Finding RDAPS-KIM point ..."
"$PYTHON_BIN" a_find_ldaps_point.py
if [ $? -ne 0 ]; then
    echo "[Error] a_find_ldaps_point.py failed!"
    exit 1
fi

echo "[Running] Preparing RDAPS vertical levels ..."
"$PYTHON_BIN" prepare_vertical_levels.py --workers "$RDAPS_WORKERS"
if [ $? -ne 0 ]; then
    echo "[Error] prepare_vertical_levels.py failed!"
    exit 1
fi


echo "[Running] Extracting and compiling ..."
bash c_run_all.sh
if [ $? -ne 0 ]; then
    echo "[Error] c_run_all.sh failed!"
    exit 1
fi

echo "[Running] Converting RDAPS extraction text ..."
perl d_change_txt.pl
if [ $? -ne 0 ]; then
    echo "[Error] d_change_txt.pl failed!"
    exit 1
fi

POSTPROCESS_SRC="e_postprocess.f90"

echo "[Running] Compiling postprocess: ${POSTPROCESS_SRC}"
gfortran "$POSTPROCESS_SRC" -o a.out
if [ $? -ne 0 ]; then
    echo "[Error] Compilation of ${POSTPROCESS_SRC} failed!"
    exit 1
fi

./a.out
if [ $? -ne 0 ]; then
    echo "[Error] a.out execution failed!"
    exit 1
fi

DEBUG_DIR="/app/sh/logs/rdaps_debug"
mkdir -p "$DEBUG_DIR"

DEBUG_FILE="$DEBUG_DIR/rdaps_debug_$(date +%Y%m%d_%H%M%S).tar.gz"

tar -czf "$DEBUG_FILE" \
    txt \
    txt_vertical_interpolation \
    txt_results \
    RDAPS_point.txt \
    rdaps_dates.txt \
    rdaps_vertical_config.env \
    rdaps_vertical_config.txt \
    e_postprocess.f90

echo "[DEBUG] Saved: $DEBUG_FILE"

echo "Total runtime: ${SECONDS} seconds"
