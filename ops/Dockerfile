FROM python:3.12-slim
WORKDIR /app
COPY requirements*.txt ./
RUN python -m pip install --no-cache-dir -r requirements-postgres.txt && useradd --uid 10001 --create-home pulsex
COPY app ./app
COPY web ./web
COPY templates ./templates
COPY run.py ./run.py
COPY tools ./tools
COPY ops ./ops
COPY VERSION ./VERSION
RUN mkdir -p /app/data/media && chown -R pulsex:pulsex /app
USER pulsex
ENV HOST=0.0.0.0 PORT=4310 PYTHONUTF8=1 PYTHONUNBUFFERED=1
EXPOSE 4310
# Do not start the service when gate/migration/bootstrap fails. exec forwards SIGTERM.
CMD ["sh","-c","python -m tools.production_gate && python -m tools.migrate_postgres && python -m tools.bootstrap_production && exec python run.py"]
