FROM python:3.13-slim

# FFmpeg is the only system dependency; opus comes with it
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first so this layer caches — code changes
# won't re-trigger a pip install on every rebuild
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Don't run as root inside the container
RUN useradd -m botuser
USER botuser

CMD ["python", "bot.py"]