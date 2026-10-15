# 개선 HYSPLIT(SPARK) Docker 적용안

검토 기준: Kgw-Mirae/Wildfire의 3267664 커밋 및 SPARK System User Manual 2026-10-12.
권장 브랜치: feat/hysplit-spark-docker

이 압축파일은 기존 저장소에 덮어 넣는 **추가 파일만** 담고 있습니다.
fire-spark 소스는 기존 저장소의 것을 사용합니다. CFD와 운영 API는 변경하지 않습니다.
GitHub 브랜치 생성은 연결 앱의 HTTP 403(Resource not accessible by integration)으로 실패했습니다.
따라서 원격 브랜치나 커밋이 생성된 상태가 아닙니다. 아래 명령으로 직접 생성하세요.

## 1. 현재 구성에서 바뀌는 부분

| 항목 | 현재 API 코드 | 개선 모델 |
|---|---|---|
| 입력 준비 | 날짜 고정 디렉터리의 CONTROL/EMITIMES 등 5개 복사 | spark_spread.py 또는 spark_daily.py가 작업별 생성 |
| 입력 경로 | HYSPLIT_TEMPLATE_SUBDIR 기본 2026/20260801 | /input의 GeoJSON 또는 FINN dayfile |
| 기상자료 | 기존 fire-spark-test/INPUT/gfs0p25 경로 | hysp.ini의 ARL_PATH 및 --met-file |
| 실행 | 기존 hysplit-model:1.0 기본 entrypoint | Python 제어기 -> 검증 -> hycs_std 또는 hycm_std |
| 결과 확인 | /work/results/cdump3 존재 확인 | hysp.run의 CDUMP + hysp.out의 NetCDF 및 상태 JSON |
| 요청 전달 | _prepare_hysplit(job_id) | request_data를 받아 입력·시간·실행 옵션 구성 필요 |

새 소스는 이미 Docker_Images/Hysplit/fire-spark 아래에 있습니다.
HYSPLIT 실행파일 및 bdyfiles는 저장소에 없습니다. 모델 제어 Python 코드만으로는 실제 계산이 불가능합니다.
이번 파일은 독립 컨테이너 검증용입니다. 이미지 이름만 바꿔 기존 API에 연결하면 동작하지 않습니다.

## 2. 브랜치 생성과 파일 배치

로컬 Wildfire 저장소 최상위에서 실행합니다. 커밋하지 않은 변경이 있다면 먼저 확인·보관하세요.

```bash
git status
git switch main
git pull --ff-only
git switch -c feat/hysplit-spark-docker
```

이 압축파일의 Docker_Images 폴더와 README 파일을 저장소 최상위에 복사합니다.
추가되는 파일:

- Docker_Images/Hysplit/Dockerfile
- Docker_Images/Hysplit/docker-entrypoint.py
- Docker_Images/Hysplit/requirements-docker.txt
- Docker_Images/Hysplit/.dockerignore
- Docker_Images/Hysplit/.gitignore
- README_HYSPLIT_DOCKER_KO.md

## 3. HYSPLIT 설치본 준비: 가장 먼저 확인할 사항

대상 서버에서 정상 실행 가능한 Linux HYSPLIT 설치본을 사용하세요.
가능하면 컨테이너와 동일한 OS·컴파일러·MPI 환경에서 빌드한 실행파일을 사용합니다.

```text
Docker_Images/Hysplit/hysplit-install/
  exec/hycs_std       # 직렬 실행; 기본 검증 모드에서 필요
  exec/hycm_std       # MPI 실행 시 필요
  bdyfiles/          # 설치본에 포함된 경계자료 전체
```

exec와 bdyfiles를 실제 설치본에서 복사합니다. 다른 경로를 가리키는 심볼릭 링크만 복사하지 마세요.
실행 권한도 유지해야 합니다. HYSPLIT 설치본 전체를 이 경로에 복사해도 됩니다.
이 디렉터리는 추가 .gitignore로 Git에서 제외되지만 Docker 빌드에는 포함됩니다.

```bash
test -x Docker_Images/Hysplit/hysplit-install/exec/hycs_std
ls -lh Docker_Images/Hysplit/hysplit-install/bdyfiles
ldd Docker_Images/Hysplit/hysplit-install/exec/hycs_std
ldd Docker_Images/Hysplit/hysplit-install/exec/hycm_std
```

실행파일이 Intel Fortran/Intel MPI로 빌드됐다면 libifcore, libimf 등 추가 런타임이 필요할 수 있습니다.
제공 Dockerfile의 libgfortran5만으로 해결된다고 가정하면 안 됩니다.
MPI도 MPICH/Open MPI/Intel MPI를 혼용하지 마세요. MPI_FLAVOR는 설치할 런타임 선택일 뿐
기존 바이너리와의 호환성을 보장하지 않습니다. 라이브러리 버전·아키텍처까지 맞춰야 합니다.
현재 Dockerfile은 직렬 실행을 기본으로 합니다. hycm_std만 있다면 먼저 MPI 빌드 환경을 확정하세요.

## 4. 이미지 빌드

```bash
docker build -t hysplit-spark:2.0-dev Docker_Images/Hysplit
```

Python 3.11 + numpy, pyproj, netCDF4, rasterio, psutil을 설치합니다.
프로그램, 라이브러리, 템플릿, HYSPLIT 설치본만 이미지에 넣고 대용량 입력·결과는 마운트합니다.
기존 소스의 개발자 전용 절대경로 hysp.ini는 복사하지 않습니다.
런타임에서 /work/hysp.ini를 JSON 형식으로 만들며 HYSPLIT_PATH=/opt/hysplit,
ARL_PATH=/met, ARL_DOWN=0으로 설정합니다. spark.ini와 hysp.in도 작업 루트에 준비합니다.
기존 /work 설정은 보존하므로 이후 환경변수를 바꿨다면 /work의 JSON 설정을 직접 수정하거나
새 작업 디렉터리를 사용하세요. --root 대신 SPARK_WORK_ROOT를 사용합니다.

빌드 직후 **컨테이너 내부에서** 라이브러리를 확인하세요.

```bash
docker run --rm --entrypoint sh hysplit-spark:2.0-dev -c \
  'ldd /opt/hysplit/exec/hycs_std; /opt/hysplit/exec/hycs_std' 
```

위 실행은 CONTROL이 없으므로 정상 모델 계산이 아니라 실행파일 로딩 점검입니다.
ldd의 not found, GLIBC/Fortran 런타임 오류가 있으면 베이스 이미지/런타임부터 수정하세요.
MPI를 검증할 때는 비루트 사용자로 실행하고 /work 쓰기 권한을 보장하세요.

## 5. 먼저 SPREAD 단독 컨테이너를 검증

기존 API가 GeoJSON 화선을 받으므로 1차 연결 대상으로 SPREAD를 권장합니다.
FINN은 별도 일별 배경 연기 시뮬레이션으로 검증합니다.

아래는 저장소의 2025-04-28 예제를 사용하는 Bash 예시입니다.
SPARK_ARL_HOST는 **GRIB2가 아닌 HYSPLIT ARL 자료**의 실제 경로로 바꾸세요.
기본 gdas1 자동 탐색이 가능한 내부 파일 배치가 필요합니다. 직접 지정하려면 각 시뮬레이션 명령에
--met-file /met/실제파일1 /met/실제파일2 를 추가하세요. 기상자료 종류에 맞춰 --arl도 지정합니다.

```bash
SPARK_JOB_HOST="$PWD/spark-test/20250428"
SPARK_INPUT_HOST="$PWD/Docker_Images/Hysplit/fire-spark/hysp.data/fire-spread/geojson/2025/20250428"
SPARK_ARL_HOST="/실제/ARL/자료경로"
mkdir -p "$SPARK_JOB_HOST"

spark_run() {
  docker run --rm --init \
    --user "$(id -u):$(id -g)" \
    -v "$SPARK_JOB_HOST:/work" \
    -v "$SPARK_INPUT_HOST:/input:ro" \
    -v "$SPARK_ARL_HOST:/met:ro" \
    hysplit-spark:2.0-dev "$@"
}

spark_run spread 20250428 --input /input --input-timezone Asia/Seoul --dry-run
spark_run spread 20250428 --input /input --input-timezone Asia/Seoul --prepare-only
spark_run spread 20250428 --input /input --input-timezone Asia/Seoul --check-only
spark_run spread 20250428 --input /input --input-timezone Asia/Seoul
```

dry-run은 입력 목록·설정 계획만 확인하며 실행파일 로딩, ARL 무결성, 실제 계산 성공을 보증하지 않습니다.
예제는 기본 72시간 수송이므로 2025-04-28 00 UTC부터 2025-05-01 00 UTC까지의 기상자료가 필요합니다.
짧은 검증에 --duration을 사용하면 prepare/check/run 모두 같은 값을 사용하세요.
기존 캐시·준비 파일과 요청이 달라졌다면 새 /work를 사용하거나 의도적으로 --renew 하세요.

예상 결과(기본 gdas1 선택 시):

```text
/work/hysp.run/SPARK-test/gdas1-spread/2025/20250428/
  CONTROL, SETUP.CFG, ASCDATA.CFG, EMITIMES
  cdump3, MESSAGE, log, spark_spread.status.json
```

기상자료 fallback을 사용하면 gfs0p25.f-spread 등 다른 실험명으로 바뀝니다.
상태 JSON의 experiment/meteorological_files와 실제 경로를 읽고 후처리 source를 결정하세요.
무조건 gdas1-spread로 후처리를 실행하면 결과를 찾지 못할 수 있습니다.

## 6. CDUMP를 NetCDF로 변환

위 Bash 함수와 같은 /work를 사용하고, 실제 실험명이 gdas1-spread인 경우:

```bash
spark_run product 20250428 --source gdas1-spread --lookback 0 --dry-run
spark_run product 20250428 --source gdas1-spread --lookback 0
spark_run product 20250428 --source gdas1-spread --lookback 0 --status --json
```

결과:

```text
/work/hysp.out/SPARK-test/gdas1-spread/2025/20250428/
  spark.gdas1-spread.20250428.epsg5179.nc
  spark.gdas1-spread.20250428.epsg3857.nc
  product.json
  spark_product.status.json
```

--lookback 0은 이번 단일 실행 검증용입니다. 운영 기본값 4는 T-4~T의 5개 실행일을 조회합니다.
과거 실행을 조회하려면 그 실행 결과가 같은 작업 루트 안에서 제공돼야 합니다.
작업별 격리는 유지하되 필요한 과거 CDUMP를 선별 복사/읽기전용 스테이징하는 별도 정책이 필요합니다.
일별 product는 UTC 00~23시 24개 필드이며 임의 시작시각의 전체 예측기간 파일이 아닙니다.
여러 예측일이 필요하면 목표 UTC 날짜마다 product를 생성하고 요청 시간대로 잘라 제공하는 후처리를 설계하세요.
짧은 수송시간은 해당 일 전체를 덮지 못할 수 있으므로 시간 coverage도 확인해야 합니다.

## 7. MPI는 직렬 기준 결과 확인 후 적용

MPICH와 호환되는 실행파일을 준비한 경우에만:

```bash
docker build --build-arg MPI_FLAVOR=mpich \
  -t hysplit-spark:2.0-mpich-dev Docker_Images/Hysplit
```

위 spark_run 함수의 이미지명을 바꾸고 docker run에
-e SPARK_CPU_MODE=mpi -e MPI_NP=6 을 추가해 **새 작업 루트**로 검증합니다.
또는 spread 명령에 --cpu-mode mpi --cpu-n 6을 지정합니다.
Open MPI 바이너리라면 MPI_FLAVOR=openmpi를 선택합니다.
Intel MPI 바이너리는 이 Dockerfile의 선택지로 제공하지 않으며 전용 런타임 구성이 필요합니다.
CPU 할당량과 MPI rank 수를 일치시키고 공유메모리/stack 설정을 실제 서버에서 검증하세요.

## 8. API 연동 후속 변경: docker_runner.py

현재 파일: model-api/api-worker/app/docker_runner.py

1. _prepare_hysplit(job_id, request_data)로 바꾸고 호출부에서도 request_data를 넘깁니다.
2. _extract_input과 기존 화선 허용 경로 검증을 재사용해 이번 요청의 GeoJSON을 작업별 /input에 준비합니다.
3. 고정 HYSPLIT_TEMPLATE_SUBDIR/5개 입력파일 복사를 SPARK 준비 단계로 대체합니다.
   새 모델은 CONC.CFG를 반드시 복사하는 구조가 아닙니다.
4. Docker host 기준 JOB_HOST_ROOT/<job_id>/hysplit/work를 /work에 마운트합니다.
   worker의 /jobs 경로와 Docker daemon 호스트의 경로를 혼동하지 마세요.
5. ARL 호스트 경로를 /met:ro로, 이번 작업 입력을 /input:ro로 마운트합니다.
6. HYSPLIT 전용 run_kwargs에 command=["spread", run_start, "--input", "/input", ...]를 전달합니다.
   별도 job orchestrator를 작성하면 시뮬레이션 성공 후 product까지 같은 작업 루트에서 실행하게 합니다.
   이 패키지의 entrypoint는 한 번에 한 제어기만 실행합니다.
7. 기존 expected_result_worker_path=/results/cdump3 검사를 교체합니다.
   새 hysp.run/.../cdump3, 시뮬레이션 status, 필요한 NetCDF와 product status/coverage를 함께 검증합니다.
8. 최종 result_path는 API가 내려줄 산출물 디렉터리로 설정하고 result/download와 callback을 같이 점검합니다.
9. 취소 시 Python 제어기뿐 아니라 MPI 자식 프로세스도 종료됐는지 확인합니다.
   기존 Docker init/stop/kill/cleanup 흐름과 작업 라벨을 유지합니다.
10. 두 worker 서버에 같은 이미지 태그를 배포하고 단일/동시 요청·큐·취소·콜백을 검증합니다.

주의: 단순 exit code=0만으로 SUCCEEDED를 판단하지 마세요.
제어기는 no_input/no_emission/missing_finn 등에도 정상 종료할 수 있습니다.
partial NetCDF도 존재할 수 있습니다. no-emission의 정상 무발생과 입력 누락을 별도로 판정하고,
기존 API 상태 체계에 맞춰 실패/성공 및 품질 메타데이터 정책을 정해야 합니다.

### 시간 계약을 먼저 확정해야 합니다

- base_time은 timezone-aware로 읽고 UTC로 변환합니다.
- 제어기 시작시간은 YYYYMMDD 또는 YYYYMMDDHH만 받으며 분 단위는 직접 지원하지 않습니다.
- 11:33 KST를 02 UTC로 내리는 경우, 요청 구간·배출 구간을 어떻게 맞출지 결정해야 합니다.
  단순 floor 후 duration만 전달하면 종료시각도 33분 당겨집니다.
- 날짜 단위 SPREAD 배출 준비와 임의 시각 예측 요청의 의미가 같은지도 확인해야 합니다.
- run 경로가 YYYYMMDD 단위이므로 같은 날 여러 시각 요청을 공유 루트에서 실행하면 충돌합니다.
  /work는 job_id마다 격리하세요.
- GeoJSON 파일명 시간대는 Asia/Seoul, 제어기 날짜와 산출물 시간은 UTC입니다.
  자정을 넘는 화선은 관련 스냅샷을 --input으로 명시하고 필요한 UTC 날짜별로 처리합니다.

### 입력과 과학 설정 확인

- RDAPS/KIM .gb2를 ARL_PATH에 넣는 것으로 HYSPLIT 기상자료가 되지는 않습니다.
  ARL 변환 과정 또는 기존 GFS ARL 자료를 사용해야 합니다.
- GeoJSON은 명시적 EPSG:5179 및 feature Intensity가 필요합니다.
- SPREAD 기본 rate=3,000,000 g/h, heat=5,000,000 W는 예시 상수입니다.
  Intensity가 배출량을 직접 비례 조절한다고 해석하면 안 됩니다.
- FINN과 SPREAD는 같은 화재를 중복 표현할 수 있으므로 1차 운영은 별도 산출물로 검증합니다.
- AOD는 경험식 proxy입니다. 위성 관측 AOD와 같은 물리량으로 제공하지 마세요.
- emission_domain(K09 기본)과 product --bbox는 별도 설정입니다.

## 9. 커밋과 서버 반영 순서

```bash
git add Docker_Images/Hysplit/Dockerfile \
  Docker_Images/Hysplit/docker-entrypoint.py \
  Docker_Images/Hysplit/requirements-docker.txt \
  Docker_Images/Hysplit/.dockerignore Docker_Images/Hysplit/.gitignore \
  README_HYSPLIT_DOCKER_KO.md
git commit -m "Add SPARK HYSPLIT Docker starter and migration guide"
git push -u origin feat/hysplit-spark-docker
```

순서: 브랜치 파일 적용 -> 실제 HYSPLIT 런타임 확인 -> 독립 SPREAD prepare/check/run ->
NetCDF/coverage 확인 -> API 연동 구현 -> 두 worker 통합 검증 -> 운영 태그 적용.
현재 단계에서 운영 .env의 HYSPLIT_IMAGE만 바꾸지 마세요.

## 10. 이번 검증 범위

Python entrypoint 문법과 작업 루트 초기화/기존 설정 보존, 저장소 제어기의 dry-run/CLI 연결을 점검합니다.
최종 실행 결과는 함께 전달되는 VALIDATION.txt를 참고하세요.
현재 Work 환경에는 Docker 실행도구, HYSPLIT 실행파일, ARL 자료가 없어 이미지 빌드,
MPI 실행, CDUMP 계산 및 NetCDF 생성은 검증하지 못했습니다.
따라서 제공물은 운영 완료 이미지가 아닌 대상 서버에서 검증할 Docker 시작 구성입니다.
