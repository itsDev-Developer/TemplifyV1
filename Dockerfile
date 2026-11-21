FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# CJK + Cyrillic/Latin fallback fonts for titles that Poppins can't draw
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# run unprivileged; /app/data is the SQLite + backups directory (mount a disk here to persist it)
RUN useradd --system --uid 10001 --home /app app && mkdir -p /app/data && chown -R app:app /app
USER app
ENV DATA_DIR=/app/data
VOLUME /app/data
# Render injects $PORT; the bot binds it (see bot/config.py)
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/ready'%os.getenv('PORT','8080'))" || exit 1
CMD ["python", "-m", "bot.main"]
