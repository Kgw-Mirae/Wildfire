#!/bin/bash
cd "$(dirname "$0")"

SECONDS=0

python ../apply_domain_config.py
if [ $? -ne 0 ]; then
    echo "apply_domain_config.py failed!"
    exit 1
fi

#echo "Running make tree  ..."
python 1_make_ascii.py
if [ $? -ne 0 ]; then
    echo "1_make_ascii.py failed!"
    exit 1
fi

#echo "Compiling 1_make__tree.f90 ..."
gfortran 1_make__tree.f90 -o make_tree.exe
if [ $? -ne 0 ]; then
    echo "Compilation of 1_make__tree.f90 failed!"
    exit 1
fi

echo "[Running] Extracting tree data ..."
./make_tree.exe
if [ $? -ne 0 ]; then
    echo "Execution of make_tree.exe failed!"
    exit 1
fi

#echo "Compiling 1_make__topo.f90 ..."
gfortran 1_make__topo.f90 -o make_topo.exe
if [ $? -ne 0 ]; then
    echo "Compilation of 1_make__topo.f90 failed!"
    exit 1
fi

echo "[Running] make tree topo ..."
./make_topo.exe
if [ $? -ne 0 ]; then
    echo "Execution of make_topo.exe failed!"
    exit 1
fi

echo "Sucessfully stop !"
echo "Total runtime: ${SECONDS} seconds"
