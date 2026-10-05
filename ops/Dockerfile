FROM python:3.13-slim
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-postgres.txt && useradd --uid 10001 --create-home pulsex
COPY app ./app
COPY web ./web
COPY templates ./templates
COPY run.py ./run.py
COPY tools ./tools
RUN mkdir -p /app/data/media && chown -R pulsex:pulsex /app
USER pulsex
ENV HOST=0.0.0.0 PORT=4310
EXPOSE 4310
CMD ["sh", "-c", "python tools/production_gate.py && python run.py"]
