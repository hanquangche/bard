# 🎵 Bard
 
A Rythm-style Discord music bot in Python. Streams audio from YouTube via
yt-dlp + FFmpeg — no downloads, no disk usage. Queues, playlists, volume,
loop modes. Runs as a Docker container.
 
## Commands
 
| Command | Description |
|---|---|
| `!play <url or search>` / `!p` | Play a song, search YouTube, or queue a whole playlist |
| `!skip` / `!s` | Skip the current track |
| `!queue` / `!q` | Show the queue |
| `!pause` / `!resume` | Pause / resume playback |
| `!volume <0-100>` / `!vol` | Set the volume (applies instantly) |
| `!loop [off\|track\|queue]` | Cycle or set loop mode |
| `!nowplaying` / `!np` | Show the current track embed |
| `!join` | Summon the bot to your voice channel |
| `!stop` | Stop, clear the queue, and leave |
 
## Setup (local development)
 
1. Install Python 3.11+ and FFmpeg
2. `python -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `cp .env.example .env` and add your bot token
   ([Discord Developer Portal](https://discord.com/developers/applications) →
   Bot → Reset Token; enable **Message Content Intent**)
5. `python bot.py`
## Docker
 
The image bundles Python and FFmpeg, runs as a non-root user, and reads the
token from `.env` at runtime — the token is never baked into the image.
 
### Run with docker compose
 
```bash
cp .env.example .env    # then add your DISCORD_TOKEN
docker compose up -d --build
```
 
`restart: unless-stopped` in `docker-compose.yml` means the bot survives
crashes and host reboots automatically. The bot makes outbound connections
only, so no ports are exposed.
 
### Managing the container
 
```bash
docker compose logs -f     # watch bot output live
docker compose restart     # restart the bot
docker compose down        # stop the bot
```
 
### Deploying updates
 
The entire update workflow, run on the server:
 
```bash
git pull && docker compose up -d --build
```
 
### Troubleshooting
 
- **Build fails with `Temporary failure resolving 'deb.debian.org'`** — the
  host uses a systemd-resolved stub (`127.0.0.53`) that containers can't
  reach. Fix by giving Docker explicit DNS in `/etc/docker/daemon.json`:
```json
  { "dns": ["1.1.1.1", "8.8.8.8"] }
```
 
  then `sudo systemctl restart docker`.
 
- **`permission denied` on `docker.sock`** — add yourself to the docker
  group (`sudo usermod -aG docker $USER`) and re-login (or `newgrp docker`).
- **Songs suddenly stop resolving** — YouTube changed something and yt-dlp
  needs updating. Bump `yt-dlp` in `requirements.txt`, then rebuild:
  `docker compose up -d --build`.
## Next steps (v2 roadmap)
 
**Quick wins**
- Idle timeout: auto-leave after ~5 minutes of empty queue — saves the
  awkward bot sitting alone in a voice channel
- `!remove <n>` to pluck songs out of the queue
- `!shuffle`
**Maintenance automation**
- A scheduled rebuild (even just a weekly cron running
  `git pull && docker compose up -d --build`) so yt-dlp stays fresh before
  YouTube breaks it — this will happen eventually, and now we know exactly
  what "songs suddenly won't resolve" means.
**Bigger swings**
- Search results as a pick-list (Rythm's `!play` showing 5 options)
- Spotify link support (resolve the track name via Spotify, then search
  YouTube for the audio)
- Persisting queues to disk so a restart doesn't wipe them
None of it is urgent — the bot as it stands will happily serve for months.
 
---
 
*For personal use. Streaming YouTube audio via third-party clients is
against YouTube's ToS; run this in your own server at your own risk.*
