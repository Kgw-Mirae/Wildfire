FROM python:3.11-slim-bookworm

# Use mpich/openmpi only for a hycm_std built against that same MPI runtime.
ARG MPI_FLAVOR=none
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates tzdata libgfortran5 libgomp1 \
    && case "$MPI_FLAVOR" in \
         none) ;; \
         mpich) apt-get install -y --no-install-recommends mpich ;; \
         openmpi) apt-get install -y --no-install-recommends openmpi-bin ;; \
         *) echo 'MPI_FLAVOR must be none, mpich or openmpi' >&2; exit 2 ;; \
       esac \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt /tmp/requirements-docker.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-docker.txt
COPY fire-spark/spark_daily.py fire-spark/spark_spread.py fire-spark/spark_product.py /opt/fire-spark/
COPY fire-spark/hysp.lib/ /opt/fire-spark/hysp.lib/
COPY fire-spark/hysp.in/ /opt/fire-spark/hysp.in/
COPY fire-spark/spark.ini /opt/fire-spark/spark.ini

# Supply an authorized Linux installation locally; it is absent from the repo.
COPY hysplit-install/ /opt/hysplit/
RUN test -d /opt/hysplit/bdyfiles \
    && (test -x /opt/hysplit/exec/hycs_std || test -x /opt/hysplit/exec/hycm_std)
COPY docker-entrypoint.py /usr/local/bin/spark-entrypoint.py
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=UTC OMP_NUM_THREADS=1
WORKDIR /work
ENTRYPOINT ["python", "/usr/local/bin/spark-entrypoint.py"]
CMD ["spread", "--help"]
