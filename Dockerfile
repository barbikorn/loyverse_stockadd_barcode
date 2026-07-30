# syntax=docker/dockerfile:1
FROM python:3.11-slim

# ป้องกัน .pyc และ buffer output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ติดตั้ง system deps สำหรับ python-barcode (Pillow)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 \
    && rm -rf /var/lib/apt/lists/*

# ติดตั้ง Python dependencies ก่อน (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอก source code
COPY . .

# Output directories
VOLUME ["/app/output"]

# Web UI (Flask app served by gunicorn)
EXPOSE 5000

# 1 worker, long timeout: a sync run is synchronous and may call the Loyverse
# API many times for a large sheet.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "600", "loyverse.web.app:app"]
