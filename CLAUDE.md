# Bard — Discord Music Bot

A Rythm-style Discord music bot in Python. Streams YouTube audio via
yt-dlp + FFmpeg (no downloads). Prefix commands (`!play` etc.). Runs as a
Docker container on a Proxmox VM in production; currently at v1.0.0 with
v2 features in progress.

## Architecture

- `bot.py` — entry point. Loads cogs, reads `DISCORD_TOKEN` from `.env`
  (python-dotenv). Message Content intent is required and enabled.
- `cogs/music.py` — everything music. Three layers:
  - **`Track`** — one song. May be *unresolved* (title/URL only, from flat
    playlist extraction) until just before playback. `resolve()` fetches
    metadata + a fresh stream URL; `needs_resolving` also triggers
    re-resolution when a stream URL is older than `STREAM_URL_TTL`
    (YouTube stream URLs expire).
  - **`GuildPlayer`** — one per Discord server, created on demand, held in
    `Music.players` (dict keyed by guild id). Owns the `asyncio.Queue`,
    volume, loop mode, and the player-loop task.
  - **`Music` (cog)** — all commands. `get_player(ctx)` is the only
    constructor path for players.

## Core invariants — do not break these

1. **Every exit path from `player_loop` calls `destroy()`** (idle timeout,
   crash handler, voice-client-gone, and `!stop` from outside). `destroy()`
   is idempotent and deregisters the player from `Music.players`. A
   registered player whose loop is dead = zombie that eats `!play` commands
   silently. If you add a new exit path, it must destroy.
2. **Never block the event loop.** All yt-dlp calls go through
   `run_in_executor`. Anything network- or CPU-heavy does likewise.
3. **The `after=` callback runs on an FFmpeg thread**, so it must use
   `call_soon_threadsafe` to set `next_song`. Do not touch asyncio objects
   directly from that callback.
4. **Playlist entries resolve lazily** (flat extraction at queue time, full
   resolution at play time). Do not "fix" this by resolving upfront — it
   exists both for speed and because stream URLs expire.
5. **Direct mutation of `queue._queue` (a deque) is deliberate** and safe
   here because asyncio is cooperative and we never `await` mid-mutation.
   Keep such mutations await-free and commented.
6. **Loop-track replays must not re-send the now-playing embed**
   (`replaying` flag) and `!skip` must break out of loop-track
   (`skip_requested` flag).

## Conventions

- Python 3.13, discord.py with `commands.Cog`, 4-space indents
- Commands are short, lowercase, with Rythm-style aliases (`!p`, `!s`,
  `!q`, `!np`, `!vol`, `!rm`)
- User-facing numbering is 1-based (matching `!queue` display); convert to
  0-based exactly once at the boundary
- User-visible messages use a leading emoji and bold track titles
- Errors must be *visible*: user-facing message in the channel, full
  traceback to stderr (so it shows in `docker compose logs`)
- Secrets live in `.env` only — never in code, never in the image
  (`.dockerignore` excludes it; token enters via compose `env_file`)

## Dev workflow

- **Local iteration:** `python bot.py` (venv, no Docker) — fast loop
- **Containerised check:** `docker compose up -d --build` — the `--build`
  is mandatory after code changes; the image snapshots code at build time
- **Deploy to prod (Proxmox VM):** `git pull && docker compose up -d --build`
- **Rollback:** `git checkout v1.0.0 && docker compose up -d --build`
- Production and dev must not run simultaneously with the same token (both
  respond to commands). Stop one, or use the separate dev bot token.
- Testing conventions: shrink `IDLE_TIMEOUT` to ~10s when testing idle
  behaviour (restore to 300 before commit); test error paths by fault
  injection (temporary `raise RuntimeError("test crash")` in the player
  loop — always delete before commit)

## Known quirks / deferred issues

- A *paused* bot never idle-times-out (loop waits on `next_song`, not the
  queue). Known, deferred — the eventual fix is a `voice_state_update`
  listener that also handles "everyone left the channel".
- yt-dlp breaks periodically when YouTube changes things. The fix is
  always: bump yt-dlp, rebuild. Not a code bug.
- `!queue` reads `queue._queue` directly for display — accepted internal
  access (see invariant 5).

## v2 roadmap (in rough order)

- [x] Idle timeout (auto-leave after 5 min empty queue)
- [x] `!remove <n>` + `!shuffle`
- [ ] Cog-level `cog_command_error` handler (errors visible in Discord)
- [ ] Cron auto-rebuild on the VM (keeps yt-dlp fresh)
- [ ] Search pick-list (top-5 results, user chooses)
- [ ] Spotify link support (resolve via Spotify API → search YouTube)
- [ ] Queue persistence across restarts