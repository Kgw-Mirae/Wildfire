#!/bin/csh

# Compose에서 MPI_NP를 전달하지 않으면 기본값 16 사용
if ( ! $?MPI_NP ) then
    setenv MPI_NP 16
endif

if ( ! $?OMP_NUM_THREADS ) then
    setenv OMP_NUM_THREADS 1
endif

echo "[INFO] MPI processes: $MPI_NP"
echo "[INFO] OMP threads: $OMP_NUM_THREADS"

setenv CFD_HOME `pwd`
echo "PWD: " $CFD_HOME

python ../apply_domain_config.py
if ($status != 0) then
    echo "[ERROR] apply_domain_config.py failed"
    exit 1
endif

setenv AHOME1 "${CFD_HOME}"
echo "Running directory: " $AHOME1
cd $AHOME1

#mpif90 moment_for_wildfire_flux.f

mpif90 \
        -O2 \
        -std=legacy \
        -fallow-argument-mismatch \
        -ffixed-line-length-none \
        -fbacktrace \
        moment_for_wildfire_flux.f \
        -o a.out

if ($status != 0) then
    echo "[ERROR] Compilation failed"
    exit 1
endif

echo "[INFO] Starting MOMENT with ${MPI_NP} MPI processes"

date > time_check
mpirun -np $MPI_NP ./a.out > log
if ($status != 0) then
    echo "[ERROR] Execution failed"
    exit 1
endif
date >> time_check

echo "${AHOME1} run complete"

rm -f $AHOME1/*.mod
rm -f $AHOME1/*.o
rm -f $AHOME1/*.out

cd $CFD_HOME
exit 0
