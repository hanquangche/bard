#!/bin/bash
# Weekly refresh: pull latest code, rebuild without cache so pip
# actually fetches the newest yt-dlp, restart the bot.
set -e
cd /home/hche/bard

echo "=== Update run: $(date) ==="
git pull
docker compose build --no-cache
docker compose up -d
docker image prune -f          # old image layers pile up otherwise
echo "=== Done: $(date) ==="