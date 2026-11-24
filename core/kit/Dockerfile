# Build/wheel availability NOT_RUN locally. Pin the built image ID for all resumes.
ARG PYTHON_IMAGE=python:3.14.7-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 MPLCONFIGDIR=/tmp/matplotlib XDG_CACHE_HOME=/tmp/kaze-cache
COPY kit/requirements-linux.txt /tmp/requirements-linux.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: -r /tmp/requirements-linux.txt && python -m pip check
COPY . /engine
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin kaze
USER 10001:10001
WORKDIR /engine
ENTRYPOINT ["python","-B","/engine/kit/serverctl.py"]
CMD ["doctor"]
