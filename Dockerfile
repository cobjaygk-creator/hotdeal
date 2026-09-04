FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chromium + its shared libs for the FMKorea anti-bot gate (Playwright).
# Set FMKOREA_BROWSER_ENABLED=0 to skip using it at runtime.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*
COPY . .

ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
