FROM python:3.12-slim

# External tools: FFmpeg (audio/video), LibreOffice (office documents), Ghostscript (PDF),
# fonts with Cyrillic support for document rendering.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg libreoffice-writer libreoffice-calc libreoffice-impress ghostscript \
        fonts-dejavu fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////app/data/formatbot.db \
    TEMP_DIR=/app/temp \
    LOG_DIR=/app/data/logs

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --create-home --uid 1000 formatbot \
    && mkdir -p /app/data /app/temp \
    && chown -R formatbot:formatbot /app/data /app/temp
USER formatbot

CMD ["python", "bot.py"]
