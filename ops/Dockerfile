FROM python:3.13-slim
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-postgres.txt && useradd --uid 10001 --create-home pulsex
COPY app ./app
COPY web ./web
COPY templates ./templates
COPY run.py ./run.py
COPY tools ./tools
COPY ops ./ops
RUN mkdir -p /app/data/media && chown -R pulsex:pulsex /app
USER pulsex
ENV HOST=0.0.0.0 PORT=4310
EXPOSE 4310
CMD ["sh", "-c", "python tools/production_gate.py && python tools/migrate_postgres.py && python tools/bootstrap_production.py && python run.py"]
