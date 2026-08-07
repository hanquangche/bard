import asyncio
import time
import traceback

import discord
import yt_dlp
from discord.ext import commands
import random

YTDL_OPTS = {
    "format": "bestaudio/best",
    "default_search": "ytsearch",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
}

# Flat extraction: titles + URLs for a whole playlist in ONE request,
# without resolving each video (that happens lazily, at play time)
YTDL_PLAYLIST_OPTS = {
    "extract_flat": "in_playlist",
    "quiet": True,
    "no_warnings": True,
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)
ytdl_playlist = yt_dlp.YoutubeDL(YTDL_PLAYLIST_OPTS)

STREAM_URL_TTL = 3600  # re-resolve stream URLs older than an hour


class Track:
    """A queued song. May be unresolved (playlist entry) until play time."""

    def __init__(self, query: str, requester: discord.Member,
                 *, title: str | None = None, duration: int = 0):
        self.query = query              # webpage URL or search string
        self.requester = requester
        self.title = title or query
        self.duration = duration or 0
        self.webpage_url = query if query.startswith("http") else ""
        self.stream_url: str | None = None
        self.resolved_at: float = 0.0

    async def resolve(self, loop) -> "Track":
        """Fetch metadata + a fresh stream URL."""
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(self.query, download=False)
        )
        if "entries" in data:
            data = data["entries"][0]
        self.title = data.get("title", self.title)
        self.duration = data.get("duration") or self.duration
        self.webpage_url = data.get("webpage_url", self.webpage_url)
        self.stream_url = data["url"]
        self.resolved_at = time.time()
        return self

    @property
    def needs_resolving(self) -> bool:
        return (self.stream_url is None
                or time.time() - self.resolved_at > STREAM_URL_TTL)

    @property
    def pretty_duration(self) -> str:
        if not self.duration:
            return "?:??"
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


class GuildPlayer:
    """Per-server queue + player loop + settings."""

    IDLE_TIMEOUT = 1800   # seconds of empty queue before auto-leave

    def __init__(self, ctx: commands.Context, cog: "Music"):
        self.bot = ctx.bot
        self.cog = cog
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self.next_song = asyncio.Event()
        self.current: Track | None = None
        self.volume = 0.5               # 50% default — be kind to ears
        self.loop_mode = "off"          # off | track | queue
        self.skip_requested = False
        self.task = self.bot.loop.create_task(self.player_loop())

    def now_playing_embed(self) -> discord.Embed:
        t = self.current
        embed = discord.Embed(
            title="Now playing",
            description=f"**[{t.title}]({t.webpage_url})**",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Duration", value=t.pretty_duration)
        embed.add_field(name="Requested by", value=t.requester.display_name)
        embed.add_field(name="Volume", value=f"{int(self.volume * 100)}%")
        if self.loop_mode != "off":
            embed.set_footer(text=f"🔁 Loop: {self.loop_mode}")
        return embed

    async def player_loop(self):
        try:
            while True:
                self.next_song.clear()

                # loop-track: replay current unless the user skipped past it
                if (self.loop_mode == "track" and self.current
                        and not self.skip_requested):
                    track = self.current
                else:
                    try:
                        track = await asyncio.wait_for(
                            self.queue.get(), timeout=self.IDLE_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        await self.channel.send(
                            "👋 Nothing queued for a while — leaving the voice "
                            "channel. `!play` me back anytime!"
                        )
                        await self.destroy()
                        return
                self.skip_requested = False

                if track.needs_resolving:
                    try:
                        await track.resolve(self.bot.loop)
                    except Exception as e:
                        await self.channel.send(
                            f"⚠️ Couldn't play **{track.title}** — skipping. ({e})"
                        )
                        continue

                # raise RuntimeError("test crash") # uncomment to test error handling

                vc = self.guild.voice_client
                if vc is None:
                    await self.destroy()
                    return

                replaying = track is self.current
                self.current = track
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTS),
                    volume=self.volume,
                )
                vc.play(
                    source,
                    after=lambda _: self.bot.loop.call_soon_threadsafe(
                        self.next_song.set
                    ),
                )
                if not replaying:  # don't spam the embed on every loop-track repeat
                    await self.channel.send(embed=self.now_playing_embed())

                await self.next_song.wait()

                # loop-queue: finished songs go to the back of the line
                if self.loop_mode == "queue" and not self.skip_requested:
                    await self.queue.put(track)
                if self.loop_mode != "track" or self.skip_requested:
                    if self.loop_mode == "queue" and self.skip_requested:
                        await self.queue.put(track)   # skipped songs still requeue
                    self.current = None
        except asyncio.CancelledError:
            raise
        except Exception:
            traceback.print_exc()
            await self.channel.send(
                "💥 The player hit an unexpected error and reset — "
                "`!play` to start fresh."
            )
            await self.destroy()
            

    async def destroy(self):
        """Disconnect and deregister this player. Safe to call from anywhere."""
        self.cog.players.pop(self.guild.id, None)
        vc = self.guild.voice_client
        if vc:
            await vc.disconnect()
        if self.task is not asyncio.current_task():
            self.task.cancel()


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildPlayer] = {}

    def get_player(self, ctx: commands.Context) -> GuildPlayer:
        if ctx.guild.id not in self.players:
            self.players[ctx.guild.id] = GuildPlayer(ctx, self)
        return self.players[ctx.guild.id]

    async def cog_command_error(self, ctx: commands.Context,
                                error: commands.CommandError):
        """Surface command errors in Discord; player-loop errors are separate."""
        if isinstance(error, commands.CommandNotFound):
            return  # typo noise — no response wanted
        if isinstance(error, commands.BadArgument):
            await ctx.send(
                f"That needs a number — e.g. `!{ctx.invoked_with} 3`"
            )
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"Usage: `!{ctx.invoked_with} {ctx.command.signature}`"
            )
            return
        # CommandInvokeError wraps the real exception — unwrap for the log
        orig = getattr(error, "original", error)
        await ctx.send("💥 Something went wrong with that command.")
        traceback.print_exception(orig)  # visible in docker compose logs

    @commands.command()
    async def join(self, ctx: commands.Context):
        if ctx.author.voice is None:
            return await ctx.send("You're not in a voice channel!")
        channel = ctx.author.voice.channel
        if ctx.voice_client is None:
            await channel.connect()
        else:
            await ctx.voice_client.move_to(channel)

    @commands.command(aliases=["p"])
    async def play(self, ctx: commands.Context, *, query: str):
        """Play a URL, search terms, or a whole playlist URL."""
        if ctx.voice_client is None:
            await ctx.invoke(self.join)
            if ctx.voice_client is None:
                return
        player = self.get_player(ctx)

        is_playlist = "list=" in query and query.startswith("http")
        async with ctx.typing():
            if is_playlist:
                data = await self.bot.loop.run_in_executor(
                    None,
                    lambda: ytdl_playlist.extract_info(query, download=False),
                )
                entries = [e for e in data.get("entries", []) if e]
                for e in entries:
                    await player.queue.put(Track(
                        e["url"], ctx.author,
                        title=e.get("title"), duration=e.get("duration") or 0,
                    ))
                await ctx.send(
                    f"📃 Queued **{len(entries)}** tracks from "
                    f"**{data.get('title', 'playlist')}**"
                )
            else:
                track = await Track(query, ctx.author).resolve(self.bot.loop)
                await player.queue.put(track)
                if player.current is not None:
                    await ctx.send(
                        f"➕ Queued **{track.title}** "
                        f"(position {player.queue.qsize()})"
                    )

    @commands.command(aliases=["vol"])
    async def volume(self, ctx: commands.Context, level: int):
        """Set volume 0–100, e.g. !volume 30"""
        if not 0 <= level <= 100:
            return await ctx.send("Volume must be 0–100.")
        player = self.get_player(ctx)
        player.volume = level / 100
        vc = ctx.voice_client
        if vc and vc.source:
            vc.source.volume = player.volume     # applies instantly
        await ctx.send(f"🔊 Volume set to {level}%")

    @commands.command(name="loop")
    async def loop_(self, ctx: commands.Context, mode: str = None):
        """!loop track | queue | off  (or bare !loop to cycle)"""
        player = self.get_player(ctx)
        modes = ["off", "track", "queue"]
        if mode is None:
            mode = modes[(modes.index(player.loop_mode) + 1) % 3]
        if mode not in modes:
            return await ctx.send("Use `!loop off`, `!loop track`, or `!loop queue`.")
        player.loop_mode = mode
        icons = {"off": "➡️", "track": "🔂", "queue": "🔁"}
        await ctx.send(f"{icons[mode]} Loop mode: **{mode}**")

    @commands.command(aliases=["np"])
    async def nowplaying(self, ctx: commands.Context):
        player = self.get_player(ctx)
        if player.current is None:
            return await ctx.send("Nothing playing.")
        await ctx.send(embed=player.now_playing_embed())

    @commands.command()
    async def pause(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ Paused.")

    @commands.command()
    async def resume(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Resumed.")

    @commands.command(aliases=["s"])
    async def skip(self, ctx: commands.Context):
        vc = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            self.get_player(ctx).skip_requested = True
            vc.stop()
            await ctx.send("⏭️ Skipped.")

    @commands.command(aliases=["q"])
    async def queue(self, ctx: commands.Context):
        player = self.get_player(ctx)
        if player.current is None and player.queue.empty():
            return await ctx.send("Queue is empty.")
        lines = []
        if player.current:
            lines.append(f"▶️ **{player.current.title}**")
        for i, track in enumerate(list(player.queue._queue), start=1):
            if i > 14:
                lines.append(f"…and {player.queue.qsize() - 14} more")
                break
            lines.append(f"{i}. {track.title} [{track.pretty_duration}]")
        await ctx.send("\n".join(lines))

    @commands.command(aliases=["rm"])
    async def remove(self, ctx: commands.Context, position: int = None):
        """Remove the queued track at a position, e.g. !remove 3 (see !queue)"""
        player = self.get_player(ctx)
        dq = player.queue._queue
        if not dq:
            return await ctx.send("Queue is empty — nothing to remove.")
        if position is None or not 1 <= position <= len(dq):
            return await ctx.send(
                f"Pick a position between 1 and {len(dq)} — `!queue` shows the numbers."
            )
        index = position - 1   # 1-based display → 0-based deque, converted once
        # Direct deque mutation is safe (invariant 5): no await between the
        # bounds check above and the deletion, so the player loop can't run.
        removed = dq[index]
        del dq[index]
        await ctx.send(f"🗑️ Removed **{removed.title}**.")

    @commands.command()
    async def shuffle(self, ctx: commands.Context):
        """Shuffle the pending queue (doesn't touch the current track)."""
        player = self.get_player(ctx)
        dq = player.queue._queue
        if len(dq) < 2:
            return await ctx.send("Nothing to shuffle — queue up at least 2 tracks.")
        # Direct deque mutation is safe (invariant 5): no await between the
        # length check and the shuffle, so the player loop can't run.
        random.shuffle(dq)
        await ctx.send(f"🔀 Shuffled **{len(dq)}** tracks.")

    @commands.command()
    async def stop(self, ctx: commands.Context):
        player = self.players.pop(ctx.guild.id, None)
        if player:
            await player.destroy()
        elif ctx.voice_client:
            await ctx.voice_client.disconnect()
        await ctx.send("⏹️ Stopped and cleared the queue. Bye!")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))