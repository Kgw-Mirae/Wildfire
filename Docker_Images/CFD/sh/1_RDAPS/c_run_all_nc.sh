#!/bin/bash
# ==========================================================
# RDAPS NetCDF pressure-level extraction launcher
# ==========================================================

POINT_FILE="./RDAPS_point.txt"
DATES_FILE="./rdaps_dates.txt"
EXTRACT_SCRIPT="./b_extract_all_nc.py"
N_WORKERS="${RDAPS_EXTRACT_WORKERS:?RDAPS_EXTRACT_WORKERS must be set by 0_run_all.sh}"
PYTHON_BIN="${PYTHON_BIN:-python}"

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

if (( N_TIMES == 0 )); then
  echo "ERROR: No valid dates found in $DATES_FILE"
  exit 1
fi
if (( N_POINTS == 0 )); then
  echo "ERROR: No valid points found in $POINT_FILE"
  exit 1
fi

TASKS=$(mktemp ./rdaps_nc_extract_tasks.XXXXXX) || exit 1
trap 'rm -f "$TASKS"' EXIT INT TERM

for ((ti=0; ti<N_TIMES; ti++)); do
  date_index=$((ti + 1))
  for point in "${POINTS[@]}"; do
    read -r x y lon lat role <<< "$point"
    printf '%s\t%d\t%s\t%s\t%s\t%s\t%s\n' \
      "${DATES[$ti]}" "$date_index" "$x" "$y" "$lon" "$lat" "$role" >> "$TASKS"
  done
done

TOTAL_JOBS=$(( N_TIMES * N_POINTS ))
ACTUAL_WORKERS=$(( TOTAL_JOBS < N_WORKERS ? TOTAL_JOBS : N_WORKERS ))

echo "[INFO] RDAPS NetCDF point extraction: ${N_TIMES} times, ${N_POINTS} points, ${TOTAL_JOBS} jobs, ${ACTUAL_WORKERS} workers"
echo "[INFO] Each job writes u/v/tmp/hgt numeric profiles to ./1_nc; OMP_NUM_THREADS=${OMP_NUM_THREADS}"

xargs -d '\n' -P "$ACTUAL_WORKERS" -I '{}' bash -c '
  IFS=$'"'"'\t'"'"' read -r date idx x y lon lat role <<< "$1"
  exec "$2" "$3" "$date" "$idx" "$x" "$y" "$lon" "$lat" "$role"
' _ '{}' "$PYTHON_BIN" "$EXTRACT_SCRIPT" < "$TASKS"
status=$?

if (( status != 0 )); then
  echo "ERROR: One or more NetCDF point extraction jobs failed."
  exit "$status"
fi

echo "Successfully stop !"
