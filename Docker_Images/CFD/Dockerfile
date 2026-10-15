FROM rockylinux:9

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# CRB와 EPEL 활성화 후 CFD 실행에 필요한 패키지 설치
RUN dnf install -y dnf-plugins-core && \
    dnf config-manager --set-enabled crb && \
    dnf install -y epel-release && \
    dnf install -y \
        python3 \
        python3-pip \
        wget \
        tar \
        gcc \
        gcc-gfortran \
        make \
        openmpi \
        openmpi-devel \
        tcsh \
        ksh \
        perl \
        netcdf \
        netcdf-devel \
        netcdf-fortran \
        netcdf-fortran-devel \
        pkgconf-pkg-config && \
    dnf clean all && \
    rm -rf /var/cache/dnf

RUN dnf install -y util-linux procps-ng

RUN ln -sf /usr/bin/python3 /usr/local/bin/python

RUN python3 -m pip install --no-cache-dir \
        numpy \
        pandas \
        geopandas \
        xarray \
        netCDF4 \
        h5netcdf \
        h5py \
        rasterio

WORKDIR /app

# 공통자료와 실행 코드만 명시적으로 복사
COPY file/ /app/file/
COPY sh/ /app/sh/
COPY wgrib2 /usr/local/bin/wgrib2

RUN chmod 755 /app/sh/run_cfd_job.sh

# 호스트에서 컴파일된 NetCDF 실행파일을 이미지에 포함하지 않음
RUN rm -f \
    /app/sh/3_postproc/post_nc \
    /app/sh/3_postproc/.post_nc.container-build

RUN chmod +x /usr/local/bin/wgrib2 && \
    chmod +x /app/sh/01_run_pre.sh && \
    chmod +x /app/sh/02_run_model.sh && \
    mkdir -p \
        /app/sh/data/Goejson \
        /app/sh/data/RDAPS-KIM \
        /app/sh/3_postproc/results

ENV PATH="/usr/lib64/openmpi/bin:${PATH}"
ENV LD_LIBRARY_PATH="/usr/lib64/openmpi/lib"

# 우선 기존 방식으로 테스트하기 위한 설정
ENV OMPI_ALLOW_RUN_AS_ROOT=1
ENV OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1

# 이미지 빌드 단계에서 필수 프로그램 확인
RUN command -v python3 && \
    command -v gfortran && \
    command -v mpif90 && \
    command -v csh && \
    command -v nf-config && \
    command -v wgrib2 && \
    python3 -c "import numpy, pandas, geopandas, rasterio"

WORKDIR /app/sh

CMD ["bash"]
