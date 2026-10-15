#!/bin/bash
# ==========================================================
# run_all_master.sh
# 1 -> 2 -> (3,4,5 parallel; 6 after 3) -> 7
# ==========================================================

set -u

START_TIME=$(date +%s)
POSTPROC_PID=""
LOG_DIR=""

format_elapsed_time() {
    local elapsed_time="$1"
    local hours=$((elapsed_time / 3600))
    local minutes=$(((elapsed_time % 3600) / 60))
    local seconds=$((elapsed_time % 60))
    printf "%02d:%02d:%02d" "$hours" "$minutes" "$seconds"
}
safe_source_env() {
    export PS1="${PS1-}"
    export COLORTERM="${COLORTERM-}"
    export TERM="${TERM-xterm}"
    export HOSTNAME="${HOSTNAME-$(hostname 2>/dev/null || echo localhost)}"
}

cleanup_background_jobs() {
    if [ -n "${POSTPROC_PID:-}" ] && kill -0 "$POSTPROC_PID" 2>/dev/null; then
        echo "[STOP ] Step 8 watcher: stopping PID ${POSTPROC_PID}"
        kill "$POSTPROC_PID" 2>/dev/null || true
        wait "$POSTPROC_PID" 2>/dev/null || true
    fi
}

trap cleanup_background_jobs EXIT

# ----------------------------------------------------------
# Docker Python environment
# ----------------------------------------------------------

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"

if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
    echo "[ERROR] Python3 executable not found"
    exit 1
fi

if ! "$PYTHON_BIN" -c \
    "import numpy, pandas, geopandas, rasterio, pyproj" \
    2>/dev/null; then

    echo "[ERROR] Required Python packages are not available"
    echo "[INFO ] Python: $PYTHON_BIN"
    echo "[INFO ] Installed packages:"
    "$PYTHON_BIN" -m pip list
    exit 1
fi

# 좌표계와 GDAL/PROJ 데이터 접근까지 확인
if ! "$PYTHON_BIN" -c \
    "from pyproj import CRS; from rasterio.crs import CRS as RasterioCRS; CRS.from_epsg(5179); RasterioCRS.from_epsg(5179)" \
    2>/dev/null; then

    echo "[ERROR] GDAL/PROJ coordinate system initialization failed"
    exit 1
fi

echo "[INFO ] Python environment: Docker system Python"
echo "[INFO ] Python: $PYTHON_BIN"
echo "[INFO ] GeoPandas: $("$PYTHON_BIN" -c 'import geopandas; print(geopandas.__version__)')"
echo "[INFO ] Rasterio: $("$PYTHON_BIN" -c 'import rasterio; print(rasterio.__version__)')"


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR"
POSTPROC_DIR="${POSTPROC_DIR:-$BASE_DIR/3_postproc}"
LOG_DIR="$BASE_DIR/logs"
mkdir -p "$LOG_DIR"

echo "[INFO ] BASE_DIR: $BASE_DIR"
echo "[INFO ] POSTPROC_DIR: $POSTPROC_DIR"
echo "[INFO ] Loaded module: Docker Python"
echo "[INFO ] Detail logs: $LOG_DIR"

check_path() {
    local target="$1"
    if [ ! -e "$target" ]; then
        echo "[ERROR] Required path not found: $target"
        exit 1
    fi
}

run_step() {
    local step_name="$1"
    local log_name="$2"
    shift
    shift
    local log_file="$LOG_DIR/${log_name}.log"
    local step_start step_end elapsed status

    step_start=$(date +%s)
    echo "[START] ${step_name}"
    echo "===== ${step_name} =====" > "$log_file"
    echo "START: $(date '+%Y-%m-%d %H:%M:%S')" >> "$log_file"
    echo "CMD: $*" >> "$log_file"
    echo "----------------------------------------" >> "$log_file"

    "$@" >> "$log_file" 2>&1
    status=$?
    step_end=$(date +%s)
    elapsed=$((step_end - step_start))

    if [ $status -ne 0 ]; then
        echo "[ERROR] ${step_name} failed after $(format_elapsed_time "$elapsed") (exit ${status})"
        echo "[ERROR] Log: $log_file"
        echo "[ERROR] Last 40 log lines:"
        tail -n 40 "$log_file"
        exit $status
    fi

    if grep -Eqi '(^|[^A-Za-z])(error|failed|traceback|exception|fatal)([^A-Za-z]|$)' "$log_file"; then
        echo "[WARN ] ${step_name} completed but log contains error-like text: $log_file"
    fi

    echo "[DONE ] ${step_name} in $(format_elapsed_time "$elapsed")"
}

run_step_console() {
    local step_name="$1"
    shift
    local step_start step_end elapsed status

    step_start=$(date +%s)
    echo "[START] ${step_name}"

    "$@"
    status=$?
    step_end=$(date +%s)
    elapsed=$((step_end - step_start))

    if [ $status -ne 0 ]; then
        echo "[ERROR] ${step_name} failed after $(format_elapsed_time "$elapsed") (exit ${status})"
        exit $status
    fi

    echo "[DONE ] ${step_name} in $(format_elapsed_time "$elapsed")"
}

run_step_bg() {
    local pid_var="$1"
    local label="$2"
    local step_name="$3"
    local log_name="$4"
    shift 4
    local log_file="$LOG_DIR/${log_name}.log"

    echo "[START] ${step_name}"

    (
        echo "===== ${step_name} ====="
        echo "START: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "CMD: $*"
        echo "----------------------------------------"
        "$@"
        status=$?
        echo "----------------------------------------"
        echo "END: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "EXIT: $status"
        exit "$status"
    ) > "$log_file" 2>&1 &
    local bg_pid=$!

    printf -v "$pid_var" '%s' "$bg_pid"
    printf -v "${pid_var}_START" '%s' "$(date +%s)"
    printf -v "${pid_var}_LOG" '%s' "$log_file"
    printf -v "${pid_var}_NAME" '%s' "$step_name"
}

wait_step_bg() {
    local pid="$1"
    local step_start="$2"
    local step_name="$3"
    local log_file="$4"
    local step_end elapsed status

    wait "$pid"
    status=$?
    step_end=$(date +%s)
    elapsed=$((step_end - step_start))

    if [ $status -ne 0 ]; then
        echo "[ERROR] ${step_name} failed after $(format_elapsed_time "$elapsed") (exit ${status})"
        echo "[ERROR] Log: $log_file"
        echo "[ERROR] Last 40 log lines:"
        tail -n 40 "$log_file"
        return "$status"
    fi

    if grep -Eqi '(^|[^A-Za-z])(error|failed|traceback|exception|fatal)([^A-Za-z]|$)' "$log_file"; then
        echo "[WARN ] ${step_name} completed but log contains error-like text: $log_file"
    fi

    echo "[DONE ] ${step_name} in $(format_elapsed_time "$elapsed")"
    return 0
}

check_log_for_errors() {
    local label="$1"
    local log_file="$2"

    if [ ! -f "$log_file" ]; then
        return 0
    fi

    if grep -Eqi '(^|[^A-Za-z])(error|failed|traceback|exception|fatal)([^A-Za-z]|$)' "$log_file"; then
        echo "[WARN ] ${label} log contains error-like text: $log_file"
        echo "[WARN ] Last 40 matching-context log lines:"
        tail -n 40 "$log_file"
    fi
}

check_path "$BASE_DIR/0_fireline/1_find_fireline_center.py"
check_path "$BASE_DIR/0_TOPO/1_run_all.sh"
check_path "$BASE_DIR/0_fireline/2_make_fireline_topo.py"
check_path "$BASE_DIR/0_tree/1_run_all.sh"
check_path "$BASE_DIR/0_emission/1_run_all.sh"
check_path "$BASE_DIR/1_RDAPS/0_run_all.sh"
check_path "$BASE_DIR/2_moment/0_run_moment.sh"
check_path "$POSTPROC_DIR/watch_nc.sh"
check_path "$POSTPROC_DIR/0_run_nc.sh"
check_path "$POSTPROC_DIR/1_post_nc.f"


run_step_console "Step 1: Find fireline center" \
    "$PYTHON_BIN" "$BASE_DIR/0_fireline/1_find_fireline_center.py"

run_step_console "Apply domain config" \
    "$PYTHON_BIN" "$BASE_DIR/apply_domain_config.py"

export DOMAIN_CONFIG_QUIET=1

run_step "Step 2: Running TOPO" "step2_topo" \
    bash "$BASE_DIR/0_TOPO/1_run_all.sh"

echo "[INFO ] Launching Step 3, Step 4, Step 5 in parallel"

run_step_bg PID3 "STEP3" "Step 3: Make fireline topo" "step3_fireline_topo" \
    "$PYTHON_BIN" "$BASE_DIR/0_fireline/2_make_fireline_topo.py"

run_step_bg PID4 "STEP4" "Step 4: Running TREE" "step4_tree" \
    bash "$BASE_DIR/0_tree/1_run_all.sh"

run_step_bg PID5 "STEP5" "Step 5: Running RDAPS-KIM" "step5_rdaps_kim" \
    bash "$BASE_DIR/1_RDAPS/0_run_all.sh"

echo "[WAIT ] Waiting for Step 3 before starting Step 6"

if ! wait_step_bg "$PID3" "$PID3_START" "$PID3_NAME" "$PID3_LOG"; then
    exit 1
fi

run_step "Step 6: Running LANDCOVER" "step6_landcover" \
    bash "$BASE_DIR/0_emission/1_run_all.sh"

echo "[WAIT ] Waiting for Step 4 and Step 5"

FAIL=0

wait_step_bg "$PID4" "$PID4_START" "$PID4_NAME" "$PID4_LOG" || FAIL=1
wait_step_bg "$PID5" "$PID5_START" "$PID5_NAME" "$PID5_LOG" || FAIL=1

if [ $FAIL -ne 0 ]; then
    echo "[ERROR] One or more parallel steps failed"
    exit 1
fi

echo "[DONE ] Step 3, Step 4, Step 5, Step 6 completed"
echo "[DONE ] All input data preparing processes completed"

PREPROCESS_END_TIME=$(date +%s)
PREPROCESS_TIME=$((PREPROCESS_END_TIME - START_TIME))
printf "Preprocessing elapsed time: %s (hh:mm:ss)\n" "$(format_elapsed_time "$PREPROCESS_TIME")"

if [[ -n "${JOB_ID:-}" && -n "${EVENT_DIR:-}" ]]; then
    mkdir -p "$EVENT_DIR"

    EVENT_TMP="${EVENT_DIR}/cfd_preprocess_completed.json.tmp"
    EVENT_FILE="${EVENT_DIR}/cfd_preprocess_completed.json"

    printf \
        '{"job_id":"%s","model_type":"cfd","event_type":"preprocess_completed","model_status":"running","produced_at":"%s"}\n' \
        "$JOB_ID" \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        > "$EVENT_TMP"

    mv "$EVENT_TMP" "$EVENT_FILE"

    echo "[EVENT] CFD preprocessing completed: $EVENT_FILE"
fi

exit 0
