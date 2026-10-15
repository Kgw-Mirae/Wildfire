#!/bin/bash
cd "$(dirname "$0")"

SECONDS=0

python ../apply_domain_config.py
if [ $? -ne 0 ]; then
    echo "apply_domain_config.py failed!"
    exit 1
fi

# 0_make_ascii.py
echo "[Running] make ascii ..."
python 1_make_ascii.py
if [ $? -ne 0 ]; then
    echo "0_make_ascii.py failed!"
    exit 1
fi

# 1_make_topo.f90
#echo "Compiling 1_make_topo.f90 ..."
gfortran 1_make__topo.f90 -o a.out
if [ $? -ne 0 ]; then
    echo "Compilation failed!"
    exit 1
fi

# a.out
echo "[Running] make topo ..."
./a.out

# cp domain info
cp -f ./output/output_model_info.txt ../data/Domain/
python ../apply_domain_config.py
if [ $? -ne 0 ]; then
    echo "apply_domain_config.py failed after TOPO!"
    exit 1
fi

#if [ $? -eq 0 ]; then
#    echo "File successfully copied to ../../data/Domain/"
#else
#    echo "File copy failed!"
#fi

echo "Sucessfully stop !"
echo "Total runtime: ${SECONDS} seconds"
