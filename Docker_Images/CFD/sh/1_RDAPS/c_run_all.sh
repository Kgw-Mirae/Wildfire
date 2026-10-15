#!/bin/bash
set -u

SOURCE_ENV="./rdaps_source_plan.env"

if [[ ! -r "$SOURCE_ENV" ]]; then
  echo "ERROR: Source plan not found: $SOURCE_ENV"
  exit 1
fi

. "$SOURCE_ENV"

case "${RDAPS_SOURCE_TYPE:-}" in
  nc_pres)
    echo "[INFO] Running RDAPS NC pres extractor"
    exec bash ./c_run_all_nc.sh
    ;;
  grib_etas|grib_pres)
    echo "[INFO] Running RDAPS GRIB extractor: ${RDAPS_SOURCE_TYPE}"
    export RDAPS_GRIB_PRODUCT="${RDAPS_GRIB_PRODUCT:-etas}"
    exec bash ./c_run_all_grib.sh
    ;;
  *)
    echo "ERROR: Unknown RDAPS_SOURCE_TYPE=${RDAPS_SOURCE_TYPE:-}"
    exit 1
    ;;
esac
