FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ARG PULSEX_SOURCE_SHA=unrecorded
LABEL org.opencontainers.image.revision="${PULSEX_SOURCE_SHA}"
ENV PULSEX_BUILD_LABEL=git-${PULSEX_SOURCE_SHA}
WORKDIR /app
COPY requirements/locks/bootstrap.txt requirements/locks/postgres.txt ./requirements/locks/
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements/locks/bootstrap.txt && \
    python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements/locks/postgres.txt && \
    python -m pip check && useradd --uid 10001 --create-home pulsex
COPY app ./app
COPY web ./web
COPY templates ./templates
COPY run.py ./run.py
COPY tools ./tools
COPY ops ./ops
COPY VERSION ./VERSION
COPY artifacts/android ./artifacts/android
RUN mkdir -p /app/data/media && chown -R pulsex:pulsex /app
USER pulsex
ENV HOST=0.0.0.0 PORT=4310 PYTHONUTF8=1 PYTHONUNBUFFERED=1
EXPOSE 4310
# Do not start the service when gate/migration/bootstrap fails. exec forwards SIGTERM.
CMD ["sh","-c","python -m tools.production_gate && python -m tools.migrate_postgres && python -m tools.bootstrap_production && exec python run.py"]
