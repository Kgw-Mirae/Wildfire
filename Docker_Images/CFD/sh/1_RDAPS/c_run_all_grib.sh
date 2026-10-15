#!/bin/bash
# ==========================================================
# RDAPS extraction launcher - mini-GRIB + level-batched version
# ==========================================================

POINT_FILE="./RDAPS_point.txt"
DATES_FILE="./rdaps_dates.txt"
EXTRACT_SCRIPT="./b_extract_all.ksh"
N_WORKERS="${RDAPS_EXTRACT_WORKERS:?RDAPS_EXTRACT_WORKERS must be set by 0_run_all.sh}"

export OMP_NUM_THREADS=1

if [[ ! -f "$EXTRACT_SCRIPT" ]]; then
  echo "ERROR: Extraction script not found: $EXTRACT_SCRIPT"
  exit 1
fi
if [[ ! -f "$POINT_FILE" ]]; then
  echo "ERROR: Point list not found: $POINT_FILE"
  exit 1
fi
if [[ ! -f "$DATES_FILE" ]]; then
  echo "ERROR: Date list not found: $DATES_FILE"
  exit 1
fi
if ! [[ "$N_WORKERS" =~ ^[0-9]+$ ]] || (( N_WORKERS <= 0 )); then
  echo "ERROR: RDAPS_EXTRACT_WORKERS must be a positive integer"
  exit 1
fi

DATES=()
while IFS= read -r line; do
  line=$(echo "$line" | tr -d '[:space:]')
  [[ -z "$line" || "$line" == \#* ]] && continue
  DATES+=("$line")
done < "$DATES_FILE"

POINTS=()
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  read -r x y lon lat role <<< "$line"
  [[ -z "${x:-}" || -z "${y:-}" || -z "${lon:-}" || -z "${lat:-}" ]] && continue
  [[ -z "${role:-}" ]] && role="interior"
  POINTS+=("$x $y $lon $lat $role")
done < "$POINT_FILE"

N_TIMES=${#DATES[@]}
N_POINTS=${#POINTS[@]}
VARS=(tmp u v hgt)

if (( N_TIMES == 0 )); then
  echo "ERROR: No valid dates found in $DATES_FILE"
  exit 1
fi
if (( N_POINTS == 0 )); then
  echo "ERROR: No valid points found in $POINT_FILE"
  exit 1
fi

# ----------------------------------------------------------
# Stage A: create small mini-GRIBs.
# 4 times x 4 variables = 16 one-time copies for current case.
# ----------------------------------------------------------
BUILD_TASKS=$(mktemp ./rdaps_build_tasks.XXXXXX) || exit 1
EXTRACT_TASKS=$(mktemp ./rdaps_extract_tasks.XXXXXX) || exit 1
trap 'rm -f "$BUILD_TASKS" "$EXTRACT_TASKS"' EXIT INT TERM

for ((ti=0; ti<N_TIMES; ti++)); do
  date_index=$((ti + 1))
  for var in "${VARS[@]}"; do
    printf '%s %d %s\n' "${DATES[$ti]}" "$date_index" "$var" >> "$BUILD_TASKS"
  done
done

BUILD_JOBS=$(( N_TIMES * ${#VARS[@]} ))
BUILD_WORKERS=$(( BUILD_JOBS < N_WORKERS ? BUILD_JOBS : N_WORKERS ))

echo "[INFO] Building mini GRIBs: ${BUILD_JOBS} jobs, ${BUILD_WORKERS} workers"
xargs -n 3 -P "$BUILD_WORKERS" bash "$EXTRACT_SCRIPT" build < "$BUILD_TASKS"
status=$?
if (( status != 0 )); then
  echo "ERROR: One or more mini-GRIB build jobs failed."
  exit "$status"
fi

# ----------------------------------------------------------
# Stage B: one task = one time + variable + point.
# Each task reads a tiny mini-GRIB and extracts all required levels
# in ONE wgrib2 call.
# ----------------------------------------------------------
for ((ti=0; ti<N_TIMES; ti++)); do
  date_index=$((ti + 1))
  for point in "${POINTS[@]}"; do
    read -r x y lon lat role <<< "$point"
    for var in "${VARS[@]}"; do
      printf '%s\t%d\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "${DATES[$ti]}" "$date_index" "$var" "$x" "$y" "$lon" "$lat" "$role" >> "$EXTRACT_TASKS"
    done
  done
done

TOTAL_JOBS=$(( N_TIMES * N_POINTS * ${#VARS[@]} ))
ACTUAL_WORKERS=$(( TOTAL_JOBS < N_WORKERS ? TOTAL_JOBS : N_WORKERS ))

echo "[INFO] Mini-GRIB point extraction: ${N_TIMES} times, ${N_POINTS} points, ${TOTAL_JOBS} jobs, ${ACTUAL_WORKERS} workers"
echo "[INFO] Each point-variable job extracts all required vertical levels with one wgrib2 call; OMP_NUM_THREADS=${OMP_NUM_THREADS}"

xargs -d '\n' -P "$ACTUAL_WORKERS" -I '{}' bash -c '
  IFS=$'"'"'\t'"'"' read -r date idx var x y lon lat role <<< "$1"
  exec bash "$2" extract "$date" "$idx" "$var" "$x" "$y" "$lon" "$lat" "$role"
' _ '{}' "$EXTRACT_SCRIPT" < "$EXTRACT_TASKS"
status=$?

if (( status != 0 )); then
  echo "ERROR: One or more point extraction jobs failed."
  exit "$status"
fi

echo "Successfully stop !"
