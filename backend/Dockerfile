FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ALPHAFORGE_DB_PATH=/data/alphaforge.db \
    ALPHAFORGE_WORKER_URL=http://lean-worker:8081 \
    ALPHAFORGE_UNIVERSE_CONFIG=/app/configs/universe_whitelist_v1.0.json

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY lean_worker/config/universe_whitelist_v1.0.json ./configs/universe_whitelist_v1.0.json
RUN mkdir -p /data

EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health')"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
