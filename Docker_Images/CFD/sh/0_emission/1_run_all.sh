#!/bin/bash
cd "$(dirname "$0")"

SECONDS=0

python ../apply_domain_config.py
if [ $? -ne 0 ]; then
    echo "apply_domain_config.py failed!"
    exit 1
fi

python 1_make_ascii.py
if [ $? -ne 0 ]; then
    echo "1_make_ascii.py failed!"
    exit 1
fi

mkdir -p ./cut

gfortran 1_make__landcover.f90 -o make_landcover.exe
if [ $? -ne 0 ]; then
    echo "Compilation of 1_make__landcover.f90 failed!"
    exit 1
fi

echo "[Running] make landcover ..."
./make_landcover.exe
if [ $? -ne 0 ]; then
    echo "Execution of make_landcover.exe failed!"
    exit 1
fi

mkdir -p ./emis_result

gfortran 1_make_er.f90 -o make_er.exe
if [ $? -ne 0 ]; then
    echo "Compilation of 2_make_er.f90 failed!"
    exit 1
fi

echo "[Running] make emission rate ..."
./make_er.exe
if [ $? -ne 0 ]; then
    echo "Execution of make_er.exe failed!"
    exit 1
fi

echo "Sucessfully stop !"
echo "Total runtime: ${SECONDS} seconds"
