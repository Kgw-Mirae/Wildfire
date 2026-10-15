#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CURRENT_PID=""
CURRENT_STAGE=""
CANCEL_REQUESTED=0
CANCEL_GRACE_SECONDS="${CANCEL_GRACE_SECONDS:-30}"

terminate_current_stage() {
    CANCEL_REQUESTED=1

    echo "[STOP ] CFD termination signal received"
    echo "[STOP ] Current stage: ${CURRENT_STAGE:-unknown}"

    if [ -n "$CURRENT_PID" ] && kill -0 "$CURRENT_PID" 2>/dev/null; then
        echo "[STOP ] Sending SIGTERM to process group: $CURRENT_PID"

        kill -TERM -- "-${CURRENT_PID}" 2>/dev/null ||
            kill -TERM "$CURRENT_PID" 2>/dev/null ||
            true
    fi
}

trap terminate_current_stage TERM INT

wait_after_cancel() {
    local waited=0

    while [ "$waited" -lt "$CANCEL_GRACE_SECONDS" ]; do
        if ! kill -0 "$CURRENT_PID" 2>/dev/null; then
            break
        fi

        sleep 1
        waited=$((waited + 1))
    done

    if kill -0 "$CURRENT_PID" 2>/dev/null; then
        echo "[STOP ] Grace period expired; sending SIGKILL"

        kill -KILL -- "-${CURRENT_PID}" 2>/dev/null ||
            kill -KILL "$CURRENT_PID" 2>/dev/null ||
            true
    fi

    wait "$CURRENT_PID" 2>/dev/null || true
}

run_stage() {
    local stage_name="$1"
    shift

    CURRENT_STAGE="$stage_name"

    local started_at
    local ended_at
    local elapsed
    local status

    started_at=$(date +%s)

    echo "[START] CFD stage: $CURRENT_STAGE"

    setsid "$@" &
    CURRENT_PID=$!

    wait "$CURRENT_PID"
    status=$?

    if [ "$CANCEL_REQUESTED" -eq 1 ]; then
        wait_after_cancel
        status=143
    fi

    ended_at=$(date +%s)
    elapsed=$((ended_at - started_at))

    echo "[INFO ] CFD stage: $CURRENT_STAGE"
    echo "[INFO ] Elapsed seconds: $elapsed"
    echo "[INFO ] Exit code: $status"

    CURRENT_PID=""

    return "$status"
}

# 1단계: 전처리
run_stage \
    "preprocessing" \
    bash "$SCRIPT_DIR/01_run_pre.sh"

STATUS=$?

if [ "$STATUS" -eq 143 ]; then
    echo "[CANCELLED] CFD preprocessing was cancelled"
    exit 143
elif [ "$STATUS" -ne 0 ]; then
    echo "[ERROR] CFD preprocessing failed"
    exit "$STATUS"
fi

# 실행 워커가 이 로그 또는 이벤트 파일을 감지하여 첫 번째 콜백 전송
echo "[EVENT] CFD_PREPROCESS_COMPLETED"

# 전처리와 모델 실행 사이에 취소 요청이 들어온 경우
if [ "$CANCEL_REQUESTED" -eq 1 ]; then
    echo "[CANCELLED] CFD was cancelled before model execution"
    exit 143
fi

# 2단계: 모델 및 후처리
run_stage \
    "model" \
    bash "$SCRIPT_DIR/02_run_model.sh"

STATUS=$?

if [ "$STATUS" -eq 143 ]; then
    echo "[CANCELLED] CFD model was cancelled"
    exit 143
elif [ "$STATUS" -ne 0 ]; then
    echo "[ERROR] CFD model failed"
    exit "$STATUS"
fi

echo "[EVENT] CFD_MODEL_COMPLETED"
echo "[DONE ] CFD job completed successfully"

exit 0
