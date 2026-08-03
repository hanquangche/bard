# 🎵 Bard

A Rythm-style Discord music bot in Python. Streams from YouTube via
yt-dlp + FFmpeg. Queues, playlists, volume, loop modes.

## Commands

| Command | Description |
|---|---|
| `!play <url or search>` / `!p` | Play a song or queue a playlist |
| `!skip` / `!s` | Skip current track |
| `!queue` / `!q` | Show the queue |
| `!pause` / `!resume` | Pause / resume |
| `!volume <0-100>` | Set volume |
| `!loop [off\|track\|queue]` | Loop modes |
| `!nowplaying` / `!np` | Current track info |
| `!stop` | Stop, clear queue, leave |

## Setup

1. Install Python 3.11+ and FFmpeg
2. `python -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `cp .env.example .env` and add your bot token
   ([Discord Developer Portal](https://discord.com/developers/applications) →
   Bot → Reset Token; enable Message Content Intent)
5. `python bot.py`

## Docker

See `Dockerfile` — coming in the next commit.

*For personal use. Streaming YouTube audio via third-party clients is
against YouTube's ToS; run this in your own server at your own risk.*