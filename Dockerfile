FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/outputs /usr/local/share/fonts \
    && cp /app/fonts/*.ttf /usr/local/share/fonts/ 2>/dev/null || true \
    && fc-cache -f 2>/dev/null || true

EXPOSE 7860

CMD ["gunicorn", "--bind", "0.0.0.0:7860", \
     "--timeout", "1800", \
     "--workers", "1", \
     "--worker-class", "gevent", \
     "--worker-connections", "50", \
     "app:app"]
