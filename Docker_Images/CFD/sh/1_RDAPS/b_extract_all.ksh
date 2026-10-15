#!/bin/bash
# ==========================================================
# RDAPS GRIB2 extraction - mini-GRIB + level-batched version
#
# Modes:
#   bash b_extract_all.ksh build   YYYY.MM.DD.HH DATE_INDEX VAR
#   bash b_extract_all.ksh extract YYYY.MM.DD.HH DATE_INDEX VAR XXX YYY LON LAT ROLE
#
# Strategy:
#   1) build: copy only the max required vertical records for one time+variable
#      from the original large RDAPS GRIB into a small temporary GRIB.
#   2) extract: read that small GRIB and extract all required levels for one
#      point in ONE wgrib2 call.
# ==========================================================

set -u

SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
RDAPS_DIR="$(dirname "$SCRIPT_PATH")"
PROJECT_DIR="$(dirname "$RDAPS_DIR")"

DATA_ROOT="${PROJECT_DIR}/data/RDAPS-KIM"
WORK_DIR="${RDAPS_DIR}/1_gb2"
MINI_DIR="${RDAPS_DIR}/mini_grib"
POINT_FILE="${RDAPS_DIR}/RDAPS_point.txt"
VERTICAL_CONFIG="${RDAPS_DIR}/rdaps_vertical_config.env"
SOURCE_PLAN="${RDAPS_DIR}/rdaps_source_plan.txt"

MODE="${1:-}"
LINE="${2:-}"
date_count="${3:-}"
var="${4:-}"

if [[ "$MODE" != "build" && "$MODE" != "extract" ]]; then
  echo "ERROR: MODE must be build or extract"
  exit 1
fi

if [[ -z "$LINE" || -z "$date_count" || -z "$var" ]]; then
  echo "ERROR: Missing required arguments"
  exit 1
fi

case "$var" in
  tmp|u|v|hgt) ;;
  *) echo "ERROR: VAR must be one of tmp, u, v, hgt"; exit 1 ;;
esac

if [[ ! -r "$POINT_FILE" ]]; then
  echo "ERROR: Cannot read $POINT_FILE"
  exit 1
fi
if [[ ! -r "$VERTICAL_CONFIG" ]]; then
  echo "ERROR: Cannot read $VERTICAL_CONFIG"
  exit 1
fi

. "$VERTICAL_CONFIG"
if [[ "${RDAPS_VERTICAL_PLAN_VERSION:-0}" != 2 ]]; then
  echo "ERROR: Regenerate the hourly vertical plan with prepare_vertical_levels.py"
  exit 1
fi

mkdir -p "$WORK_DIR" "$MINI_DIR" || exit 1

zp2() { printf "%02d" "$((10#$1))"; }
zp3() { printf "%03d" "$((10#$1))"; }

# ----------------------------------------------------------
# Parse valid time and locate original RDAPS GRIB
# ----------------------------------------------------------
LINE="$(echo "$LINE" | tr -d '[:space:]')"
year=${LINE%%.*}
rest=${LINE#*.}
month=${rest%%.*}
rest=${rest#*.}
day=${rest%%.*}
vhour=${rest#*.}

y=$((10#${year}))
m=$((10#${month}))
d=$((10#${day}))
h=$((10#${vhour}))

yy=$(printf "%04d" "$y")
mm=$(printf "%02d" "$m")
dd=$(printf "%02d" "$d")
HHv=$(printf "%02d" "$h")

utc_stamp=$(perl -MTime::Local -MPOSIX=strftime -e '
  my ($y,$m,$d,$h)=@ARGV;
  my $t=timegm(0,0,$h,$d,$m-1,$y) - 9*3600;
  print strftime("%Y%m%d%H", gmtime($t));
' "$yy" "$mm" "$dd" "$HHv")

yy_utc=${utc_stamp:0:4}
mm_utc=${utc_stamp:4:2}
dd_utc=${utc_stamp:6:2}
HH_utc=${utc_stamp:8:2}

vhi=$((10#${HH_utc}))
base_hour=$(( (vhi / 6) * 6 ))
hhh=$(( vhi - base_hour ))

if [[ $hhh -eq 0 ]]; then
  utc_stamp=$(perl -MTime::Local -MPOSIX=strftime -e '
    my ($y,$m,$d,$h)=@ARGV;
    my $t=timegm(0,0,$h,$d,$m-1,$y) - 6*3600;
    print strftime("%Y%m%d%H", gmtime($t));
  ' "$yy_utc" "$mm_utc" "$dd_utc" "$HH_utc")

  yy_utc=${utc_stamp:0:4}
  mm_utc=${utc_stamp:4:2}
  dd_utc=${utc_stamp:6:2}
  base_hour=$((10#${utc_stamp:8:2}))
  hhh=6
fi

base_hh=$(zp2 "$base_hour")
HHH=$(zp3 "$hhh")

yyyymmdd="${yy}${mm}${dd}"
yyyymmdd_utc="${yy_utc}${mm_utc}${dd_utc}"
date_valid="${yyyymmdd}${HHv}"
date2="${yyyymmdd_utc}${base_hh}"

if [[ -r "$SOURCE_PLAN" ]]; then
  plan_line=$(awk -v key="$date_valid" 'NF >= 7 && $1 == key {print; exit}' "$SOURCE_PLAN")
else
  plan_line=""
fi

if [[ -n "$plan_line" ]]; then
  read -r _plan_valid _plan_utc plan_source plan_product _plan_cycle _plan_fhr plan_file <<< "$plan_line"
  if [[ "$plan_source" != grib_* ]]; then
    echo "ERROR: GRIB extractor selected but source plan says $plan_source for $date_valid"
    exit 1
  fi
  in_gb2="$plan_file"
else
  product="${RDAPS_GRIB_PRODUCT:-etas}"
  in_gb2="${DATA_ROOT}/r030_v040_ne36_${product}_h${HHH}.${date2}.gb2"
fi
mini_gb2="${MINI_DIR}/${date_valid}_${var}.gb2"

if [[ ! -f "$in_gb2" ]]; then
  echo "ERROR: Missing GRIB2: $in_gb2"
  exit 1
fi

# ----------------------------------------------------------
# Determine original record start for this variable.
# The first point is only used to recover the configured start record.
# ----------------------------------------------------------
first_point=$(grep -v '^[[:space:]]*#' "$POINT_FILE" | awk 'NF>=4 {print; exit}')
if [[ -z "$first_point" ]]; then
  echo "ERROR: No usable point in $POINT_FILE"
  exit 1
fi
read -r first_x first_y first_lon first_lat first_role <<< "$first_point"
set_vertical_lists "$first_x" "$first_y" "$date_valid" || exit 1

case "$var" in
  tmp) FULL_LIST_FIRST="$TMP_LIST_FULL" ;;
  u)   FULL_LIST_FIRST="$U_LIST_FULL" ;;
  v)   FULL_LIST_FIRST="$V_LIST_FULL" ;;
  hgt) FULL_LIST_FIRST="$HGT_LIST_FULL" ;;
esac

read -r VAR_START _ <<< "$FULL_LIST_FIRST"
MAX_COUNT=$((10#${RDAPS_TIME_MAX_EXTRACTION_LEVEL_COUNT}))
VAR_END=$(( VAR_START + MAX_COUNT - 1 ))

# ==========================================================
# BUILD MODE
# ==========================================================
if [[ "$MODE" == "build" ]]; then
  tmp_gb2="${mini_gb2}.tmp.$$"
  rm -f "$tmp_gb2"

  # -grib copies selected GRIB messages without decoding/repacking them.
  wgrib2 "$in_gb2" -for "${VAR_START}:${VAR_END}" -grib "$tmp_gb2" >/dev/null
  status=$?
  if (( status != 0 )); then
    rm -f "$tmp_gb2"
    echo "ERROR: Failed to build mini GRIB: date=$LINE var=$var range=${VAR_START}:${VAR_END}"
    exit "$status"
  fi

  if [[ ! -s "$tmp_gb2" ]]; then
    rm -f "$tmp_gb2"
    echo "ERROR: Empty mini GRIB created: date=$LINE var=$var"
    exit 1
  fi

  mv -f "$tmp_gb2" "$mini_gb2"
  exit 0
fi

# ==========================================================
# EXTRACT MODE
# ==========================================================
xxx="${5:-}"
yyy="${6:-}"
lon="${7:-}"
lat="${8:-}"
point_role="${9:-interior}"

if [[ -z "$xxx" || -z "$yyy" || -z "$lon" || -z "$lat" ]]; then
  echo "ERROR: extract mode requires XXX YYY LON LAT ROLE"
  exit 1
fi

if [[ ! -s "$mini_gb2" ]]; then
  echo "ERROR: Mini GRIB not found: $mini_gb2"
  exit 1
fi

set_vertical_lists "$xxx" "$yyy" "$date_valid" || exit 1

case "$var" in
  tmp)
    FULL_ITEMS="$TMP_LIST_FULL"
    TOP_ITEMS="$TMP_LIST_TOP"
    ;;
  u)
    FULL_ITEMS="$U_LIST_FULL"
    TOP_ITEMS="$U_LIST_TOP"
    ;;
  v)
    FULL_ITEMS="$V_LIST_FULL"
    TOP_ITEMS="$V_LIST_TOP"
    ;;
  hgt)
    FULL_ITEMS="$HGT_LIST_FULL"
    TOP_ITEMS="$HGT_LIST_TOP"
    ;;
esac

if [[ "$date_count" -eq 1 || "$point_role" == "boundary" ]]; then
  ITEMS="$FULL_ITEMS"
else
  ITEMS="$TOP_ITEMS"
fi

# ITEMS are contiguous record numbers. Convert original record numbers
# to 1-based positions inside the mini GRIB.
read -ra REC_ARRAY <<< "$ITEMS"
if (( ${#REC_ARRAY[@]} == 0 )); then
  echo "ERROR: Empty vertical record list for ${xxx}_${yyy} var=$var"
  exit 1
fi

REC_FIRST=${REC_ARRAY[0]}
REC_LAST=${REC_ARRAY[$(( ${#REC_ARRAY[@]} - 1 ))]}
REL_FIRST=$(( REC_FIRST - VAR_START + 1 ))
REL_LAST=$(( REC_LAST - VAR_START + 1 ))

if (( REL_FIRST < 1 || REL_LAST > MAX_COUNT || REL_FIRST > REL_LAST )); then
  echo "ERROR: Invalid mini-GRIB record range ${REL_FIRST}:${REL_LAST} for ${xxx}_${yyy} var=$var"
  exit 1
fi

out_file="${WORK_DIR}/${xxx}_${yyy}_${date_valid}_${var}.txt"
tmp_out="${out_file}.tmp.$$"

# One wgrib2 call extracts ALL required vertical levels for this point.
wgrib2 "$mini_gb2" -for "${REL_FIRST}:${REL_LAST}" -lon "$lon" "$lat" > "$tmp_out"
status=$?
if (( status != 0 )); then
  rm -f "$tmp_out"
  echo "ERROR: Point extraction failed: date=$LINE var=$var point=${xxx}_${yyy}"
  exit "$status"
fi

expected=$(( REL_LAST - REL_FIRST + 1 ))
actual=$(grep -c 'val=' "$tmp_out" || true)
if (( actual != expected )); then
  rm -f "$tmp_out"
  echo "ERROR: Unexpected output count for ${xxx}_${yyy} date=$LINE var=$var: got=$actual expected=$expected"
  exit 1
fi

mv -f "$tmp_out" "$out_file"
exit 0
