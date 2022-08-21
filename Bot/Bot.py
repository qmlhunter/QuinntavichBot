import asyncio
import json
import economy
from re import U
from unicodedata import name
import discord.utils
from Birthday import calcAge, parsedate,birthAlert,dateDiffer
from discord.ext import tasks
import base64
from datetime import date
import aiohttp
from collections import defaultdict
import datetime
import json
import giphy_client
from giphy_client.rest import ApiException
from os import listdir, system
from discord.utils import get
from pprint import pprint
import random
import math
import os
import discord
import functools
from async_timeout import timeout
import itertools
import youtube_dl
from password_strength import PasswordStats
import time
from discord.ext import commands
import discord.ext

stats = PasswordStats('qwerty123')

bot = commands.Bot(command_prefix=commands.when_mentioned_or("*"),
description='Quinntavich, a bot for all your needs!')

datastore = defaultdict(list)
filename = 'Accounts.json'
littledict = defaultdict(list)


class MyClient(discord.Client):
    async def on_ready(self):
        
        print(f'Started watching...')
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('--------------------------------')
        
    


intents = discord.Intents.default()
intents.members = True

client = MyClient(intents=intents)

youtube_dl.utils.bug_reports_message = lambda: ''


class VoiceError(Exception):
    pass


class YTDLError(Exception):
    pass


class YTDLSource(discord.PCMVolumeTransformer):
    YTDL_OPTIONS = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
    }

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
    }

    ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data

        self.uploader = data.get('uploader')
        self.uploader_url = data.get('uploader_url')
        date = data.get('upload_date')
        self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]
        self.title = data.get('title')
        self.thumbnail = data.get('thumbnail')
        self.description = data.get('description')
        self.duration = self.parse_duration(int(data.get('duration')))
        self.tags = data.get('tags')
        self.url = data.get('webpage_url')
        self.views = data.get('view_count')
        self.likes = data.get('like_count')
        self.dislikes = data.get('dislike_count')
        self.stream_url = data.get('url')

    def __str__(self):
        return '**{0.title}** by **{0.uploader}**'.format(self)

    @classmethod
    async def create_source(cls, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(cls.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if data is None:
            raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
                raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        webpage_url = process_info['webpage_url']
        partial = functools.partial(cls.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            raise YTDLError('Couldn\'t fetch `{}`'.format(webpage_url))

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    raise YTDLError('Couldn\'t retrieve any matches for `{}`'.format(webpage_url))

        return cls(ctx, discord.FFmpegPCMAudio(info['url'], **cls.FFMPEG_OPTIONS), data=info)

    @staticmethod
    def parse_duration(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if days > 0:
            duration.append('{} days'.format(days))
        if hours > 0:
            duration.append('{} hours'.format(hours))
        if minutes > 0:
            duration.append('{} minutes'.format(minutes))
        if seconds > 0:
            duration.append('{} seconds'.format(seconds))

        return ', '.join(duration)


class Song:
    __slots__ = ('source', 'requester')

    def __init__(self, source: YTDLSource):
        self.source = source
        self.requester = source.requester

    def create_embed(self):
        embed = (discord.Embed(title='Now playing',
                               description='```css\n{0.source.title}\n```'.format(self),
                               color=discord.Color.blurple())
                 .add_field(name='Duration', value=self.source.duration)
                 .add_field(name='Requested by', value=self.requester.mention)
                 .add_field(name='Uploader', value='[{0.source.uploader}]({0.source.uploader_url})'.format(self))
                 .add_field(name='URL', value='[Click]({0.source.url})'.format(self))
                 .set_thumbnail(url=self.source.thumbnail))

        return embed


class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return self.qsize()

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]


class VoiceState:
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self._ctx = ctx

        self.current = None
        self.voice = None
        self.next = asyncio.Event()
        self.songs = SongQueue()

        self._loop = False
        self._volume = 0.5
        self.skip_votes = set()

        self.audio_player = bot.loop.create_task(self.audio_player_task())

    def __del__(self):
        self.audio_player.cancel()

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value

    @property
    def is_playing(self):
        return self.voice and self.current

    async def audio_player_task(self):
        while True:
            self.next.clear()

            if not self.loop:
                # Try to get the next song within 3 minutes.
                # If no song will be added to the queue in time,
                # the player will disconnect due to performance
                # reasons.
                try:
                    async with timeout(180):  # 3 minutes
                        self.current = await self.songs.get()
                except asyncio.TimeoutError:
                    self.bot.loop.create_task(self.stop())
                    return

            self.current.source.volume = self._volume
            self.voice.play(self.current.source, after=self.play_next_song)
            await self.current.source.channel.send(embed=self.current.create_embed())

            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            raise VoiceError(str(error))

        self.next.set()

    def skip(self):
        self.skip_votes.clear()

        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()

        if self.voice:
            await self.voice.disconnect()
            self.voice = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send('An error occurred: {}'.format(str(error)))

    @commands.command(name='join', invoke_without_subcommand=True)
    async def _join(self, ctx: commands.Context):
        """Joins a voice channel."""

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='summon')
    @commands.has_permissions(manage_guild=True)
    async def _summon(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """Summons the bot to a voice channel.
        If no channel was specified, it joins your channel.
        """

        if not channel and not ctx.author.voice:
            raise VoiceError('You are neither connected to a voice channel nor specified a channel to join.')

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='leave', aliases=['disconnect'])
    @commands.has_permissions(manage_guild=True)
    async def _leave(self, ctx: commands.Context):
        """Clears the queue and leaves the voice channel."""

        if not ctx.voice_state.voice:
            return await ctx.send('Not connected to any voice channel.')

        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name='volume')
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """Sets the volume of the player."""

        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        if 0 > volume > 100:
            return await ctx.send('Volume must be between 0 and 100')

        ctx.voice_state.volume = volume / 100
        await ctx.send('Volume of the player set to {}%'.format(volume))

    @commands.command(name='now', aliases=['current', 'playing'])
    async def _now(self, ctx: commands.Context):
        """Displays the currently playing song."""

        await ctx.send(embed=ctx.voice_state.current.create_embed())

   
           
    @commands.command(name='pause')
    async def _pause(self, ctx: commands.Context):
     SongPlaying = ctx.voice_client.is_playing()
     Paused = ctx.voice_client.is_paused()
     if Paused == False:
        ctx.voice_client.pause()
        await ctx.send("> **The song is now paused**")
        await ctx.message.add_reaction('⏯')
     else:
        if SongPlaying == False:
            await ctx.send("> **The song is already paused.**")
        else:
            await ctx.send("> **There is no song currently playing.**")
    @commands.command(name='resume')
    async def _resume(self, ctx: commands.Context):
     SongPlayinng = ctx.voice_client.is_playing()
     Pauseed = ctx.voice_client.is_paused()
     if Pauseed == True:
        ctx.voice_client.resume()
        await ctx.send("> **Resumed the song**")
        await ctx.message.add_reaction('⏯')
     else:
        if SongPlayinng == True:
            await ctx.send("> **The song is already playing.**")
        else:
            await ctx.send("> **There is no song currently playing.**")

    @commands.command(name='stop')
    @commands.has_permissions(manage_guild=True)
    async def _stop(self, ctx: commands.Context):
        """Stops playing song and clears the queue."""

        ctx.voice_state.songs.clear()

        if ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction('⏹')

    @commands.command(name='skip')
    async def _skip(self, ctx: commands.Context):
        """Vote to skip a song. The requester can automatically skip.
        3 skip votes are needed for the song to be skipped.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send('Not playing any music right now...')

        voter = ctx.message.author
        if voter == ctx.voice_state.current.requester:
            await ctx.message.add_reaction('⏭')
            ctx.voice_state.skip()

        elif voter.id not in ctx.voice_state.skip_votes:
            ctx.voice_state.skip_votes.add(voter.id)
            total_votes = len(ctx.voice_state.skip_votes)

            if total_votes >= 3:
                await ctx.message.add_reaction('⏭')
                ctx.voice_state.skip()
            else:
                await ctx.send('Skip vote added, currently at **{}/3**'.format(total_votes))

        else:
            await ctx.send('You have already voted to skip this song.')

    @commands.command(name='queue')
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """Shows the player's queue.
        You can optionally specify the page to show. Each page contains 10 elements.
        """

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ''
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [**{1.source.title}**]({1.source.url})\n'.format(i + 1, song)

        embed = (discord.Embed(description='**{} tracks:**\n\n{}'.format(len(ctx.voice_state.songs), queue))
                 .set_footer(text='Viewing page {}/{}'.format(page, pages)))
        await ctx.send(embed=embed)

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: commands.Context):
        """Shuffles the queue."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction('✅')

    @commands.command(name='remove')
    async def _remove(self, ctx: commands.Context, index: int):
        """Removes a song from the queue at a given index."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction('✅')

    @commands.command(name='loop')
    async def _loop(self, ctx: commands.Context):
        """Loops the currently playing song.
        Invoke this command again to unloop the song.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await ctx.message.add_reaction('✅')

    @commands.command(name='play')
    async def _play(self, ctx: commands.Context, *, search: str):
        """Plays a song.
        If there are songs in the queue, this will be queued until the
        other songs finished playing.
        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """

        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        async with ctx.typing():
            try:
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
            except YTDLError as e:
                await ctx.send('An error occurred while processing this request: {}'.format(str(e)))
            else:
                song = Song(source)

                await ctx.voice_state.songs.put(song)
                await ctx.send('Enqueued {}'.format(str(source)))

    @_join.before_invoke
    @_play.before_invoke
    async def ensure_voice_state(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError('You are not connected to any voice channel.')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError('Bot is already in a voice channel.')


bot = commands.Bot('music.', description='Quinntavich, A bot for all your needs.')
bot.add_cog(Music(bot))
class Misc(commands.Cog):
    def __init__(self, client):
        self.client = client
bot = commands.Bot(command_prefix=commands.when_mentioned_or("*"),
description='Quinntavich, a bot for all your needs!')

intents = discord.Intents.default()
intents.members = True

@bot.command(pass_context=True)
@commands.has_permissions(administrator=True)
async def spam(ctx):
  description = '''Spams annoying messages!'''
  message = """
  @everyone QUINNTAVICH IS BENDING THE SPACE TIME CONTINUUM! THIS SERVER WILL BE PWNED TILL I GET SHUT DOWN! :D 

@everyone QUINNTAVICH IS SHATTERING THE SPACE TIME CONTINUUM! THIS SERVER WILL BE PWNED TILL I GET SHUT DOWN! :D

@everyone QUINNTAVICH IS SHATTERING THE SPACE TIME CONTINUUM! THIS SERVER WILL BE PWNED TILL I GET SHUT DOWN! :D 

@everyone QUINNTAVICH IS SHATTERING THE SPACE TIME CONTINUUM! THIS SERVER WILL BE PWNED TILL I GET SHUT DOWN! :D 

@everyone QUINNTAVICH IS SHATTERING THE SPACE TIME CONTINUUM! THIS SERVER WILL BE PWNED TILL I GET SHUT DOWN! :D 

@everyone QUINNTAVICH IS SHATTERING THE SPACE TIME CONTINUUM! THIS SERVER WILL BE PWNED TILL I GET SHUT DOWN! :D
  """
  while True:
    time.sleep(random.randint(1,2))
    await ctx.send(message)
  
  loop()
for fn in os.listdir("CHANGE ME TO COGS DESTINATION!!!"):
	if fn.endswith(".py"):
		bot.load_extension(f"cogs.{fn[:-3]}")
@bot.command() 
async def add(ctx, *nums):
    description = '''Add numbers'''
    operation = " + ".join(nums)
    await ctx.send(f"```> {operation} = {eval(operation)} ```")

@bot.command() 
async def sub(ctx, *nums): 
    description = '''Subtract numbers'''
    operation = " - ".join(nums)
    await ctx.send(f"```> {operation} = {eval(operation)} ```")

@bot.command() 
async def multiply(ctx, *nums): 
        description = '''Multiply numbers'''
        operation = " * ".join(nums)
        await ctx.send(f"```> {operation} = {eval(operation)} ```")

@bot.command() 
async def div(ctx, *nums): 
    description = '''Divide numbers'''
    operation = " / ".join(nums)
    await ctx.send(f"```> {operation} = {eval(operation)} ```")


@bot.command()
async def choose(ctx, *choices: str):
    description='For when you wanna settle the score some other way'
    await ctx.send(random.choice(choices))

@bot.command(pass_context=True)
@commands.has_permissions(kick_members = True)
async def kick(ctx, member : discord.Member, *, reason=None):
    description = '''Kicks members'''
    await member.kick(reason=reason)
    await ctx.send("Kicked lol")
    channel = bot.get_channel(627286906995998740)
    await channel.send("\n \n "+str(ctx.message.author)+" banned "+str(member)+". \n **Reason:** "+str(reason)+("\n\n **In the Server:** ")+str(ctx.message.guild))
@bot.command()
async def meme(ctx,*,q="Meme"):
    description = '''Displays a random meme gif'''

    api_key = 'APIKEY'
    api_instance = giphy_client.DefaultApi()

    try:

        api_response = api_instance.gifs_search_get(api_key, q,)
        lst = list(api_response.data)
        giff = random.choice(lst)
        emb = discord.Embed(title=q)
        emb.set_image(url=f'https://media.giphy.com/media/{giff.id}/giphy.gif')
        await ctx.send(embed=emb)
    except ApiException as e:
        print("Exception when calling Api")
@bot.command()
async def gif(ctx,*,q="Random"):
    description = '''Displays a random gif!'''

    api_key = 'APIKEY'
    api_instance = giphy_client.DefaultApi()

    try:

        api_response = api_instance.gifs_search_get(api_key, q,)
        lst = list(api_response.data)
        giff = random.choice(lst)
        emb = discord.Embed(title=q)
        emb.set_image(url=f'https://media.giphy.com/media/{giff.id}/giphy.gif')
        await ctx.send(embed=emb)
    except ApiException as e:
        print("Exception when calling Api")
@bot.command()
async def website(ctx):
    await ctx.send ("https://www.quinnhunter.ca")
@bot.command()
async def insult(ctx, member: discord.Member):
  description = '''Insults someone! (Example usage: Insult @Jerry)'''
  insult_messages = [

    
        f'{ctx.message.author.mention} called {member.mention} an anorak',
        f'{ctx.message.author.mention} called {member.mention} an ape',
        f'{ctx.message.author.mention} called {member.mention} an arse',
        f'{ctx.message.author.mention} said {member.mention} has arsebreath',
        f'{ctx.message.author.mention} called {member.mention} an arseface',
        f'{ctx.message.author.mention} called {member.mention} an arsehole',
        f'{ctx.message.author.mention} called {member.mention} an arse-licker',
        f'{ctx.message.author.mention} called {member.mention} an ass',
        f'{ctx.message.author.mention} called {member.mention} an assaholic',
        f'{ctx.message.author.mention} called {member.mention} an ass bag',
        f'{ctx.message.author.mention} called {member.mention} an ass clown',
        f'{ctx.message.author.mention} called {member.mention} an assface',
        f'{ctx.message.author.mention} called {member.mention} an assegg',
        f'{ctx.message.author.mention} called {member.mention} an asseater',
        f'{ctx.message.author.mention} called {member.mention} an asshat',
        f'{ctx.message.author.mention} called {member.mention} an asshole',
        f'{ctx.message.author.mention} called {member.mention} an ass-kisser',
        f'{ctx.message.author.mention} called {member.mention} an ass licker',
        f'{ctx.message.author.mention} called {member.mention} an assmonkey',
        f'{ctx.message.author.mention} called {member.mention} an assmouth',
        f'{ctx.message.author.mention} called {member.mention} an assmunch',
        f'{ctx.message.author.mention} called {member.mention} an ass-nugget',
        f'{ctx.message.author.mention} called {member.mention} an ass sucker',
        f'{ctx.message.author.mention} called {member.mention} an asstard',
        f'{ctx.message.author.mention} called {member.mention} an asswagon',
        f'{ctx.message.author.mention} called {member.mention} an assweed',
        f'{ctx.message.author.mention} called {member.mention} an asswipe',
        f'{ctx.message.author.mention} called {member.mention} a baby',
        f'{ctx.message.author.mention} called {member.mention} a backwoodsman',
        f'{ctx.message.author.mention} called {member.mention} a badass',
        f'{ctx.message.author.mention} called {member.mention} a badgerfucker',
        f'{ctx.message.author.mention} called {member.mention} a bag of dicks',
        f'{ctx.message.author.mention} called {member.mention} a bag',
        f'{ctx.message.author.mention} called {member.mention} a ballkicker',
        f'{ctx.message.author.mention} called {member.mention} a ballsack',
        f'{ctx.message.author.mention} called {member.mention} a bandit',
        f'{ctx.message.author.mention} called {member.mention} a bangsat',
        f'{ctx.message.author.mention} called {member.mention} a barbarian',
        f'{ctx.message.author.mention} called {member.mention} a bastard',
        f'{ctx.message.author.mention} called {member.mention} a bawtboy',
        f'{ctx.message.author.mention} called {member.mention} a bean head',
        f'{ctx.message.author.mention} called {member.mention} a beast',
        f'{ctx.message.author.mention} called {member.mention} a bedwetter',
        f'{ctx.message.author.mention} called {member.mention} a beetlehead',
        f'{ctx.message.author.mention} called {member.mention} a beggar',
        f'{ctx.message.author.mention} called {member.mention} a beginner',
        f'{ctx.message.author.mention} called {member.mention} a beldame',
        f'{ctx.message.author.mention} called {member.mention} a bell-end',
        f'{ctx.message.author.mention} called {member.mention} a berk',
        f'{ctx.message.author.mention} called {member.mention} a bespawler',
        f'{ctx.message.author.mention} called {member.mention} a beta',
        f'{ctx.message.author.mention} called {member.mention} a beta cuck',
        f'{ctx.message.author.mention} called {member.mention} a bimbo',
        f'{ctx.message.author.mention} called {member.mention} a birdbrain',
        f'{ctx.message.author.mention} called {member.mention} a birdfucker',
        f'{ctx.message.author.mention} called {member.mention} a bitch',
        f'{ctx.message.author.mention} called {member.mention} a bitchzilla',
        f'{ctx.message.author.mention} called {member.mention} a biznatch',
        f'{ctx.message.author.mention} called {member.mention} a blaggard',
        f'{ctx.message.author.mention} called {member.mention} a blockhead',
        f'{ctx.message.author.mention} called {member.mention} a blubber gut',
        f'{ctx.message.author.mention} called {member.mention} a bluntie',
        f'{ctx.message.author.mention} called {member.mention} a bogeyman',
        f'{ctx.message.author.mention} called {member.mention} a bonehead',
        f'{ctx.message.author.mention} called {member.mention} a boob',
        f'{ctx.message.author.mention} called {member.mention} a booby',
        f'{ctx.message.author.mention} called {member.mention} a boomer',
        f'{ctx.message.author.mention} called {member.mention} a bootlicker',
        f'{ctx.message.author.mention} called {member.mention} a boozer',
        f'{ctx.message.author.mention} called {member.mention} a bot',
        f'{ctx.message.author.mention} called {member.mention} a bozo',
        f'{ctx.message.author.mention} called {member.mention} a brainlet',
        f'{ctx.message.author.mention} called {member.mention} a Brandon',
        f'{ctx.message.author.mention} called {member.mention} a brickhead',
        f'{ctx.message.author.mention} called {member.mention} a buffoon',
        f'{ctx.message.author.mention} called {member.mention} a bugger',
        f'{ctx.message.author.mention} called {member.mention} a bum',
        f'{ctx.message.author.mention} called {member.mention} a bumbo',
        f'{ctx.message.author.mention} called {member.mention} a bum chum',
        f'{ctx.message.author.mention} called {member.mention} a bunghole',
        f'{ctx.message.author.mention} called {member.mention} a burden',
        f'{ctx.message.author.mention} called {member.mention} a buttass',
        f'{ctx.message.author.mention} called {member.mention} a buttface',
        f'{ctx.message.author.mention} called {member.mention} a butthead',
        f'{ctx.message.author.mention} called {member.mention} a butthole',
        f'{ctx.message.author.mention} called {member.mention} a buttkisser',
        f'{ctx.message.author.mention} called {member.mention} a butt knuckler',
        f'{ctx.message.author.mention} called {member.mention} a buttlicker',
        f'{ctx.message.author.mention} called {member.mention} a butt lord',
        f'{ctx.message.author.mention} called {member.mention} a buttmunch',
        f'{ctx.message.author.mention} called {member.mention} a butt nugget',
        f'{ctx.message.author.mention} called {member.mention} a butt sniffer',
        f'{ctx.message.author.mention} called {member.mention} a butt tickler',
        f'{ctx.message.author.mention} called {member.mention} a cactus fucker',
        f'{ctx.message.author.mention} called {member.mention} a cad',
        f'{ctx.message.author.mention} called {member.mention} a carny',
        f'{ctx.message.author.mention} called {member.mention} a caveman',
        f'{ctx.message.author.mention} called {member.mention} a chatty stranger',
        f'{ctx.message.author.mention} called {member.mention} a chauvinist',
        f'{ctx.message.author.mention} called {member.mention} a chav',
        f'{ctx.message.author.mention} called {member.mention} a cheater',
        f'{ctx.message.author.mention} called {member.mention} a chicken',
        f'{ctx.message.author.mention} called {member.mention} a chicken shit',
        f'{ctx.message.author.mention} called {member.mention} a choad',
        f'{ctx.message.author.mention} called {member.mention} a chomo',
        f'{ctx.message.author.mention} called {member.mention} a chump',
        f'{ctx.message.author.mention} called {member.mention} a clod',
        f'{ctx.message.author.mention} called {member.mention} a clown',
        f'{ctx.message.author.mention} called {member.mention} a cock',
        f'{ctx.message.author.mention} called {member.mention} a cretin',
        f'{ctx.message.author.mention} called {member.mention} a crook',
        f'{ctx.message.author.mention} called {member.mention} a crybaby',
        f'{ctx.message.author.mention} called {member.mention} a dimmadumbass',
        f'{ctx.message.author.mention} called {member.mention} a dimwit',
        f'{ctx.message.author.mention} called {member.mention} a ding-head',
        f'{ctx.message.author.mention} called {member.mention} a dingleberry',
        f'{ctx.message.author.mention} called {member.mention} a dingus',
        f'{ctx.message.author.mention} called {member.mention} a dinosaur',
        f'{ctx.message.author.mention} called {member.mention} a dipshit',
        f'{ctx.message.author.mention} called {member.mention} a dirtbag',
        f'{ctx.message.author.mention} called {member.mention} a dirthead',
        f'{ctx.message.author.mention} called {member.mention} a dirtwad' ,
        f'{ctx.message.author.mention} called {member.mention} a dodo',
        f'{ctx.message.author.mention} called {member.mention} a dog',
        f'{ctx.message.author.mention} called {member.mention} a dogbolt',
        f'{ctx.message.author.mention} called {member.mention} a dogbreath',
        f'{ctx.message.author.mention} called {member.mention} a dolt',
        f'{ctx.message.author.mention} called {member.mention} a donkey',
        f'{ctx.message.author.mention} called {member.mention} a donkey dick',
        f'{ctx.message.author.mention} called {member.mention} a doofus',
        f'{ctx.message.author.mention} called {member.mention} a dope',
        f'{ctx.message.author.mention} called {member.mention} a dotterel',
        f'{ctx.message.author.mention} called {member.mention} a douche',
        f'{ctx.message.author.mention} called {member.mention} a douche bag',
        f'{ctx.message.author.mention} called {member.mention} a doucheburger',
        f'{ctx.message.author.mention} called {member.mention} a douche canoe',
        f'{ctx.message.author.mention} called {member.mention} a douchelord',
        f'{ctx.message.author.mention} called {member.mention} a douche nark',
        f'{ctx.message.author.mention} called {member.mention} a douche nozzle',
        f'{ctx.message.author.mention} called {member.mention} a douchewad',
        f'{ctx.message.author.mention} called {member.mention} a douchewagon',
        f'{ctx.message.author.mention} called {member.mention} a dracula',
        f'{ctx.message.author.mention} called {member.mention} a dreamer',
        f'{ctx.message.author.mention} called {member.mention} a drug dealer',
        f'{ctx.message.author.mention} called {member.mention} a drunkard',
        f'{ctx.message.author.mention} called {member.mention} a dumbarse',
        f'{ctx.message.author.mention} called {member.mention} a dumbass',
        f'{ctx.message.author.mention} called {member.mention} a dumbbell',
        f'{ctx.message.author.mention} called {member.mention} a dumb blonde',
        f'{ctx.message.author.mention} called {member.mention} a dumbo',
        f'{ctx.message.author.mention} called {member.mention} a dummy',
        f'{ctx.message.author.mention} called {member.mention} a dunce',
        f'{ctx.message.author.mention} called {member.mention} a duncebucket',
        f'{ctx.message.author.mention} called {member.mention} a dweeb',
        f'{ctx.message.author.mention} called {member.mention} a dweebling',
        f'{ctx.message.author.mention} called {member.mention} an edgelord',
        f'{ctx.message.author.mention} called {member.mention} an egghead',
        f'{ctx.message.author.mention} called {member.mention} an egotist',
        f'{ctx.message.author.mention} called {member.mention} an envirotard',
        f'{ctx.message.author.mention} called {member.mention} an evildoer',
        f'{ctx.message.author.mention} called {member.mention} a fart',
        f'{ctx.message.author.mention} called {member.mention} a fartface',
        f'{ctx.message.author.mention} called {member.mention} a fartknocker',
        f'{ctx.message.author.mention} called {member.mention} a fartman',
        f'{ctx.message.author.mention} called {member.mention} a fart sucker',
        f'{ctx.message.author.mention} called {member.mention} a fatass',
        f'{ctx.message.author.mention} called {member.mention} a fatso',
        f'{ctx.message.author.mention} called {member.mention} a fatty',
        f'{ctx.message.author.mention} called {member.mention} a fellow',
        f'{ctx.message.author.mention} called {member.mention} a fembot',
        f'{ctx.message.author.mention} called {member.mention} a fetus',
        f'{ctx.message.author.mention} called {member.mention} a fibber',
        f'{ctx.message.author.mention} called {member.mention} a fink',
        f'{ctx.message.author.mention} called {member.mention} a first time skier',
        f'{ctx.message.author.mention} called {member.mention} a fish',
        f'{ctx.message.author.mention} called {member.mention} a fishwife',
        f'{ctx.message.author.mention} called {member.mention} a fixer',
        f'{ctx.message.author.mention} called {member.mention} a flake',
        f'{ctx.message.author.mention} called {member.mention} a flat-earther',
        f'{ctx.message.author.mention} called {member.mention} a fleabag',
        f'{ctx.message.author.mention} called {member.mention} a flip-flopper',
        f'{ctx.message.author.mention} called {member.mention} a fool',
        f'{ctx.message.author.mention} called {member.mention} a foreskin ripper',
        f'{ctx.message.author.mention} called {member.mention} a foul mouth',
        f'{ctx.message.author.mention} called {member.mention} a four eyes',
        f'{ctx.message.author.mention} called {member.mention} a fraggle',
        f'{ctx.message.author.mention} called {member.mention} a fruitcake',
        f'{ctx.message.author.mention} called {member.mention} a frump',
        f'{ctx.message.author.mention} called {member.mention} a fugly',
        f'{ctx.message.author.mention} called {member.mention} a funpire',
        f'{ctx.message.author.mention} called {member.mention} a furry',
        f'{ctx.message.author.mention} called {member.mention} a gangster',
        f'{ctx.message.author.mention} called {member.mention} a gaper',
        f'{ctx.message.author.mention} called {member.mention} a garbage',
        f'{ctx.message.author.mention} called {member.mention} a gawk',
        f'{ctx.message.author.mention} called {member.mention} a gaywad',
        f'{ctx.message.author.mention} called {member.mention} a geebag',
        f'{ctx.message.author.mention} called {member.mention} a geek',
        f'{ctx.message.author.mention} called {member.mention} a gimp',
        f'{ctx.message.author.mention} called {member.mention} a git',
        f'{ctx.message.author.mention} called {member.mention} a goblin',
        f'{ctx.message.author.mention} called {member.mention} a gobshite',
        f'{ctx.message.author.mention} called {member.mention} a gold digger',
        f'{ctx.message.author.mention} called {member.mention} a goof',
        f'{ctx.message.author.mention} called {member.mention} a goon',
        f'{ctx.message.author.mention} called {member.mention} a goose',
        f'{ctx.message.author.mention} called {member.mention} a GoPro Kid',
        f'{ctx.message.author.mention} called {member.mention} a gorilla',
        f'{ctx.message.author.mention} called {member.mention} an idiot',
        f'{ctx.message.author.mention} called {member.mention} an idiotist',
        f'{ctx.message.author.mention} called {member.mention} an idiot sandwich',
        f'{ctx.message.author.mention} called {member.mention} a pansy',
        f'{ctx.message.author.mention} called {member.mention} a pariah',
        f'{ctx.message.author.mention} called {member.mention} a peasant',
        f'{ctx.message.author.mention} called {member.mention} a pedophile',
        f'{ctx.message.author.mention} called {member.mention} a Rumple-Foreskin',
        f'{ctx.message.author.mention} called {member.mention} a runt',
        f'{ctx.message.author.mention} called {member.mention} a sadist',
        f'{ctx.message.author.mention} called {member.mention} a saggy fuck',
        f'{ctx.message.author.mention} called {member.mention} a saprophyte',
        f'{ctx.message.author.mention} called {member.mention} a sausage-masseuse',
        f'{ctx.message.author.mention} called {member.mention} a scaredy-cat',
        f'{ctx.message.author.mention} called {member.mention} a scobberlotcher',
        f'{ctx.message.author.mention} called {member.mention} a scoozie',
        f'{ctx.message.author.mention} called {member.mention} a scoundrel',
        f'{ctx.message.author.mention} called {member.mention} a screw up',
        f'{ctx.message.author.mention} called {member.mention} a scrote',
        f'{ctx.message.author.mention} called {member.mention} a scrotum-sucker',
        f'{ctx.message.author.mention} called {member.mention} a scumbag',
        f'{ctx.message.author.mention} called {member.mention} a scumbreath',
        f'{ctx.message.author.mention} called {member.mention} a scumbutt',
        f'{ctx.message.author.mention} called {member.mention} a scumface',
        f'{ctx.message.author.mention} called {member.mention} a scumfuck',
        f'{ctx.message.author.mention} called {member.mention} a scumhead',
        f'{ctx.message.author.mention} called {member.mention} a scumlord',
        f'{ctx.message.author.mention} called {member.mention} a scumwad',
        f'{ctx.message.author.mention} called {member.mention} a scuzzbag',
        f'{ctx.message.author.mention} called {member.mention} a serf',
        f'{ctx.message.author.mention} called {member.mention} a sewer rat',
        f'{ctx.message.author.mention} called {member.mention} a shark',
        f'{ctx.message.author.mention} called {member.mention} a sheepfucker',
        f'{ctx.message.author.mention} called {member.mention} a sheepshagger',
        f'{ctx.message.author.mention} called {member.mention} a shill',
        f'{ctx.message.author.mention} called {member.mention} a shitass',
        f'{ctx.message.author.mention} called {member.mention} a shitbag',
        f'{ctx.message.author.mention} called {member.mention} a shitball',
        f'{ctx.message.author.mention} called {member.mention} a shitbird',
        f'{ctx.message.author.mention} called {member.mention} a shitbrain',
        f'{ctx.message.author.mention} called {member.mention} a shitbreath',
        f'{ctx.message.author.mention} called {member.mention} a shitbucket',
        f'{ctx.message.author.mention} called {member.mention} a shitbum',
        f'{ctx.message.author.mention} called {member.mention} a windfucker',
        f'{ctx.message.author.mention} called {member.mention} a window licker',
        f'{ctx.message.author.mention} called {member.mention} a windsucker',
        f'{ctx.message.author.mention} called {member.mention} a wino',
        f'{ctx.message.author.mention} called {member.mention} a witch',
        f'{ctx.message.author.mention} called {member.mention} a womanizer',
        f'{ctx.message.author.mention} called {member.mention} a zitface',
        f'{ctx.message.author.mention} called {member.mention} a zoophile',
        f'{ctx.message.author.mention} called {member.mention} a zounderkite',

  ]
  await ctx.send(random.choice(insult_messages))
@bot.command()
async def kill(ctx, member: discord.Member):
    description = '''Kill someone! (Example usage: *kill @Jerry)'''
    kill_messages = [
        
        f'{ctx.message.author.mention} killed {member.mention} with a steel baseball bat', 
        
        f'{ctx.message.author.mention} killed {member.mention} with a huge non stick frying pan'
        
        f'{ctx.message.author.mention} killed {member.mention} with a poisoned potato', 
       
        f'{ctx.message.author.mention} killed {member.mention} by beating them to death with a sock mace',
        f'{ctx.message.author.mention} killed {member.mention} by shoving their face into a paper shredder', 
       
        f'{ctx.message.author.mention} killed {member.mention} with poison gas',
        
        f'{ctx.message.author.mention} killed {member.mention} by hurting their feelings till they died',
        f'{ctx.message.author.mention} killed {member.mention} by pointing out their flaws making their self esteem go downhill until they die of sad',
       
        f'{ctx.message.author.mention} killed {member.mention} with EMOTIONAL DAMAGE', 
        
        f'{ctx.message.author.mention} killed {member.mention} via showing them a meme so cursed they have an aneurysm and die', 
      
        f'{ctx.message.author.mention} killed {member.mention} by uttering something so stupid their brain exploded due to {ctx.message.author.mention}s stupidity', 
       
        f'{ctx.message.author.mention} killed {member.mention} via stab', 
      
        f'{ctx.message.author.mention} killed {member.mention} by hacking into a government facility and launching a missile to their coordinates',
      
        f'{ctx.message.author.mention} killed {member.mention} by putting acid in their underwear',
      
        f'{ctx.message.author.mention} killed {member.mention} by hacking their pc and putting questionable things into their search history causing their mom to kill them',

        f'{ctx.message.author.mention} killed {member.mention} by stuffing their pillow with glass shards',
        
        f'{ctx.message.author.mention} killed {member.mention} by feeding them bleach',
    ]  
    await ctx.send(random.choice(kill_messages))
@bot.command()  
async def info(ctx, user: discord.Member):  
    description = '''Show another user's ID! (Example usage: *info @Jerry)'''
    await ctx.send(f'{user.mention}\'s id: `{user.id}`') 

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('You didnt type the command correctly...  :skull:')
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You dont pass all the requirements :skull:")

        
@bot.command()
async def about(ctx):
    description='About the bot'
    
    await ctx.send('My name is Quinntavich! I was developed by Quinn es Perezoso#2903! If you mess with me youll get wrecked so dont even try.')
@bot.command()
@commands.has_permissions(ban_members = True)
async def ban(ctx, member : discord.Member, *, reason = None):
    description = '''Ban people! With the necessary permissions of course'''
    await member.ban(reason = reason)
    
@bot.command(pass_context=True)
@commands.has_permissions(manage_guild=True)
async def nickname(ctx, member: discord.Member, nick):
    await member.edit(nick=nick)
    await ctx.send(f'Nickname was changed for {member.mention} ')

@bot.command()
@commands.has_permissions(administrator = True)
async def unban(ctx, *, member, description='Unban members!'):
    description = '''Unban members!'''
    banned_users = await ctx.guild.bans()
    member_name, member_discriminator = member.split("#")

    for ban_entry in banned_users:
        user = ban_entry.user

        if (user.name, user.discriminator) == (member_name, member_discriminator):
            await ctx.guild.unban(user)
            await ctx.send(f'Unbanned {user.mention}')
            return
@bot.command(aliases=['setbirth','setbirthday'])
async def setbday(ctx,*,arg):
    description ='Add your birthday to the database!'
    message = ctx.message
    Truth = True
    date = parsedate((arg))
    age = calcAge(datetime.date(date[-1],date[-3],date[-2]))
    if os.path.exists(filename):
       
        with open(filename,'r') as jsonFile:
            l = (json.load(jsonFile))
        if str(message.guild.id) in l:
            for i in l[str(message.guild.id)]:
                for j in i:
                    if str(message.author) in i:
                 
                        i[str(message.author)] = {arg:age}
                  
                        Truth = False
                        break
            if Truth:
                l[str(message.guild.id)].append({str(message.author):{arg:age}})
        else:
            l[str(message.guild.id)]=[{str(message.author):{arg:age}}]
        with open(filename, 'w') as f:
            json.dump(l,f, sort_keys=True,indent=4)
        await ctx.send(f'{message.author.display_name}s birthday is now in the Database')

    else:
        datastore[str(message.guild.id)]=[({str(message.author):{arg:age}})]

        with open(filename, 'w') as f:
            json.dump(datastore,f, indent=4)
        await ctx.send(f'``{message.author.display_name}``s birthday is now ``in`` the Database')
 
@bot.command(aliases=['adventure','explore'])
async def adv(ctx):
    await ctx.send("Work in progress.. :skull:")
    

@bot.command( aliases = ['birth','born'])
async def birthday(ctx, *arg:discord.Member):
     description = '''Tells you your birthday'''
     message = ctx.message
     truth = False
     if os.path.exists(filename):
         with open(filename,'r') as jsonFile:
             loading = (json.load(jsonFile))
         for i in arg:
             for j in loading[str(message.guild.id)]:
                 if str(i) in j:
                     truth = True
                     for k in j:
                         for h in j[str(k)].keys():
                             await ctx.send('``'+str(i.display_name)+'``\'s'+' birthday is on ``'+ str(h)+'``')
             if not truth:
                 await ctx.send('this person is not in the database. please put your birthday for example : ``.mybday March 2, 1998`` ')

@bot.command(aliases=['age','old'])
async def howold(ctx):
    description = '''Tells you your age!''' 
    message = ctx.message
    birth = 0
    if os.path.exists(filename):
        with open(filename,'r') as jsonFile:
            loading = (json.load(jsonFile))
        for j in loading[str(message.guild.id)]:
            if str(message.author) in j:
                for k in j:
                    for h in j[str(k)].values():
                        birth=h

        await ctx.send(f'Your age is ``{birth}``')



@bot.command( aliases =['length','difference', 'dif','far'])
async def agedifference(ctx, arg:discord.Member):
    description = '''Calculates age differences between users! (Example usage: *agedifference @Jerry)'''
    other = arg
    msg = ctx.message
    yourBirth = ''
    otherBirth = ''
    l =[]
    server = str(msg.guild.id)
    if os.path.exists(filename):
        with open(filename,'r') as jsonFile:
            loading = (json.load(jsonFile))

        for j in loading[str(msg.guild.id)]:
            if str(other) in j:
                for k in j:
                    for i in j[str(k)].keys():
                        otherBirth = i

        for j in loading[str(msg.guild.id)]:
            if str(msg.author) in j:
                for k in j:
                    for i in j[str(k)].keys():
                        yourBirth = i
        birthDiff = dateDiffer(yourBirth, otherBirth)
        if birthDiff < 0 :
            await ctx.send(f'I am ``{abs(birthDiff)}``  days older than ``{other.display_name}``')
        else:
            await ctx.send(f'`{other.display_name}`  is ``{abs(birthDiff)}`` days older than me')




@tasks.loop(hours=13)
async def bdayReminder():
    if os.path.exists(filename):
        with open(filename,'r') as jsonFile:
            loading = (json.load(jsonFile))
        for server in loading:
            for obj in loading[server]:
                for user in obj:
                  
                    for birth in obj[user]:
                   
                        if birthAlert(str(birth)):
                         
                            id = int(server)
                            channels = bot.get_guild(id).text_channels
                            age = 0
                            com = 0
                            max = ''
                        
                         
                            for i in range(len(loading[server])):
                                if user in loading[server][i]:
                                   
                                    date = parsedate((birth))
                                    age = calcAge(datetime.date(date[-1],date[-3],date[-2]))
                                    loading[server][i][user][birth] = age
                            with open(filename, 'w') as f:
                                json.dump(loading,f, indent=4)
                            for channel in channels:
                                messages = await channel.history(limit=None).flatten()
                                if com < len(messages):
                                    max = channel.name
                                    com = len(messages)
                                   
                            for channel in channels:
                            
                                if channel.name.lower() == max:
                                    await channel.send(f'@here Happy ``{age}`` birthday to ``{user}``! ')
                                    
@bdayReminder.before_loop
async def test():
    print(f'Logged in as Quinntavich (ID: ???)')
    await bot.wait_until_ready()
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="You"))

bdayReminder.start()
    

@bot.command()
async def ping(ctx, Discord: discord.member):
    description = '''Ping a user! (Yes! It's useless!''' 
    await ctx.send("Yo {member.mention}! You're getting pinged by {ctx.message.author.mention}!")
@bot.command()
async def joined(ctx, member: discord.Member):
    description = '''Says when a member joined the server. (Yes! It's useless)''' 
    await ctx.send(f"``` {member.name} joined in {member.joined_at} ```")
@bot.command()
async def revenge(ctx, member: discord.Member):
  description = '''Get revenge on someone!!!'''
  revenge_messages = [

    
        f'{ctx.message.author.mention} called {member.mention} an anorak',
        f'{ctx.message.author.mention} called {member.mention} an ape',
        f'{ctx.message.author.mention} called {member.mention} an arse',
        f'{ctx.message.author.mention} said {member.mention} has arsebreath',
        f'{ctx.message.author.mention} called {member.mention} an arseface',
        f'{ctx.message.author.mention} called {member.mention} an arsehole',
        f'{ctx.message.author.mention} called {member.mention} an arse-licker',
        f'{ctx.message.author.mention} called {member.mention} an ass',
        f'{ctx.message.author.mention} called {member.mention} an assaholic',
        f'{ctx.message.author.mention} called {member.mention} an ass bag',
        f'{ctx.message.author.mention} called {member.mention} an ass clown',
        f'{ctx.message.author.mention} called {member.mention} an assface',
        f'{ctx.message.author.mention} called {member.mention} an assegg',
        f'{ctx.message.author.mention} called {member.mention} an asseater',
        f'{ctx.message.author.mention} called {member.mention} an asshat',
        f'{ctx.message.author.mention} called {member.mention} an asshole',
        f'{ctx.message.author.mention} called {member.mention} an ass-kisser',
        f'{ctx.message.author.mention} called {member.mention} an ass licker',
        f'{ctx.message.author.mention} called {member.mention} an assmonkey',
        f'{ctx.message.author.mention} called {member.mention} an assmouth',
        f'{ctx.message.author.mention} called {member.mention} an assmunch',
        f'{ctx.message.author.mention} called {member.mention} an ass-nugget',
        f'{ctx.message.author.mention} called {member.mention} an ass sucker',
        f'{ctx.message.author.mention} called {member.mention} an asstard',
        f'{ctx.message.author.mention} called {member.mention} an asswagon',
        f'{ctx.message.author.mention} called {member.mention} an assweed',
        f'{ctx.message.author.mention} called {member.mention} an asswipe',
        f'{ctx.message.author.mention} called {member.mention} a baby',
        f'{ctx.message.author.mention} called {member.mention} a backwoodsman',
        f'{ctx.message.author.mention} called {member.mention} a badass',
        f'{ctx.message.author.mention} called {member.mention} a badgerfucker',
        f'{ctx.message.author.mention} called {member.mention} a bag of dicks',
        f'{ctx.message.author.mention} called {member.mention} a bag',
        f'{ctx.message.author.mention} called {member.mention} a ballkicker',
        f'{ctx.message.author.mention} called {member.mention} a ballsack',
        f'{ctx.message.author.mention} called {member.mention} a bandit',
        f'{ctx.message.author.mention} called {member.mention} a bangsat',
        f'{ctx.message.author.mention} called {member.mention} a barbarian',
        f'{ctx.message.author.mention} called {member.mention} a bastard',
        f'{ctx.message.author.mention} called {member.mention} a bawtboy',
        f'{ctx.message.author.mention} called {member.mention} a bean head',
        f'{ctx.message.author.mention} called {member.mention} a beast',
        f'{ctx.message.author.mention} called {member.mention} a bedwetter',
        f'{ctx.message.author.mention} called {member.mention} a beetlehead',
        f'{ctx.message.author.mention} called {member.mention} a beggar',
        f'{ctx.message.author.mention} called {member.mention} a beginner',
        f'{ctx.message.author.mention} called {member.mention} a beldame',
        f'{ctx.message.author.mention} called {member.mention} a bell-end',
        f'{ctx.message.author.mention} called {member.mention} a berk',
        f'{ctx.message.author.mention} called {member.mention} a bespawler',
        f'{ctx.message.author.mention} called {member.mention} a beta',
        f'{ctx.message.author.mention} called {member.mention} a beta cuck',
        f'{ctx.message.author.mention} called {member.mention} a bimbo',
        f'{ctx.message.author.mention} called {member.mention} a birdbrain',
        f'{ctx.message.author.mention} called {member.mention} a birdfucker',
        f'{ctx.message.author.mention} called {member.mention} a bitch',
        f'{ctx.message.author.mention} called {member.mention} a bitchzilla',
        f'{ctx.message.author.mention} called {member.mention} a biznatch',
        f'{ctx.message.author.mention} called {member.mention} a blaggard',
        f'{ctx.message.author.mention} called {member.mention} a blockhead',
        f'{ctx.message.author.mention} called {member.mention} a blubber gut',
        f'{ctx.message.author.mention} called {member.mention} a bluntie',
        f'{ctx.message.author.mention} called {member.mention} a bogeyman',
        f'{ctx.message.author.mention} called {member.mention} a bonehead',
        f'{ctx.message.author.mention} called {member.mention} a boob',
        f'{ctx.message.author.mention} called {member.mention} a booby',
        f'{ctx.message.author.mention} called {member.mention} a boomer',
        f'{ctx.message.author.mention} called {member.mention} a bootlicker',
        f'{ctx.message.author.mention} called {member.mention} a boozer',
        f'{ctx.message.author.mention} called {member.mention} a bot',
        f'{ctx.message.author.mention} called {member.mention} a bozo',
        f'{ctx.message.author.mention} called {member.mention} a brainlet',
        f'{ctx.message.author.mention} called {member.mention} a Brandon',
        f'{ctx.message.author.mention} called {member.mention} a brickhead',
        f'{ctx.message.author.mention} called {member.mention} a buffoon',
        f'{ctx.message.author.mention} called {member.mention} a bugger',
        f'{ctx.message.author.mention} called {member.mention} a bum',
        f'{ctx.message.author.mention} called {member.mention} a bumbo',
        f'{ctx.message.author.mention} called {member.mention} a bum chum',
        f'{ctx.message.author.mention} called {member.mention} a bunghole',
        f'{ctx.message.author.mention} called {member.mention} a burden',
        f'{ctx.message.author.mention} called {member.mention} a buttass',
        f'{ctx.message.author.mention} called {member.mention} a buttface',
        f'{ctx.message.author.mention} called {member.mention} a butthead',
        f'{ctx.message.author.mention} called {member.mention} a butthole',
        f'{ctx.message.author.mention} called {member.mention} a buttkisser',
        f'{ctx.message.author.mention} called {member.mention} a butt knuckler',
        f'{ctx.message.author.mention} called {member.mention} a buttlicker',
        f'{ctx.message.author.mention} called {member.mention} a butt lord',
        f'{ctx.message.author.mention} called {member.mention} a buttmunch',
        f'{ctx.message.author.mention} called {member.mention} a butt nugget',
        f'{ctx.message.author.mention} called {member.mention} a butt sniffer',
        f'{ctx.message.author.mention} called {member.mention} a butt tickler',
        f'{ctx.message.author.mention} called {member.mention} a cactus fucker',
        f'{ctx.message.author.mention} called {member.mention} a cad',
        f'{ctx.message.author.mention} called {member.mention} a carny',
        f'{ctx.message.author.mention} called {member.mention} a caveman',
        f'{ctx.message.author.mention} called {member.mention} a chatty stranger',
        f'{ctx.message.author.mention} called {member.mention} a chauvinist',
        f'{ctx.message.author.mention} called {member.mention} a chav',
        f'{ctx.message.author.mention} called {member.mention} a cheater',
        f'{ctx.message.author.mention} called {member.mention} a chicken',
        f'{ctx.message.author.mention} called {member.mention} a chicken shit',
        f'{ctx.message.author.mention} called {member.mention} a choad',
        f'{ctx.message.author.mention} called {member.mention} a chomo',
        f'{ctx.message.author.mention} called {member.mention} a chump',
        f'{ctx.message.author.mention} called {member.mention} a clod',
        f'{ctx.message.author.mention} called {member.mention} a clown',
        f'{ctx.message.author.mention} called {member.mention} a cock',
        f'{ctx.message.author.mention} called {member.mention} a cretin',
        f'{ctx.message.author.mention} called {member.mention} a crook',
        f'{ctx.message.author.mention} called {member.mention} a crybaby',
        f'{ctx.message.author.mention} called {member.mention} a dimmadumbass',
        f'{ctx.message.author.mention} called {member.mention} a dimwit',
        f'{ctx.message.author.mention} called {member.mention} a ding-head',
        f'{ctx.message.author.mention} called {member.mention} a dingleberry',
        f'{ctx.message.author.mention} called {member.mention} a dingus',
        f'{ctx.message.author.mention} called {member.mention} a dinosaur',
        f'{ctx.message.author.mention} called {member.mention} a dipshit',
        f'{ctx.message.author.mention} called {member.mention} a dirtbag',
        f'{ctx.message.author.mention} called {member.mention} a dirthead',
        f'{ctx.message.author.mention} called {member.mention} a dirtwad' ,
        f'{ctx.message.author.mention} called {member.mention} a dodo',
        f'{ctx.message.author.mention} called {member.mention} a dog',
        f'{ctx.message.author.mention} called {member.mention} a dogbolt',
        f'{ctx.message.author.mention} called {member.mention} a dogbreath',
        f'{ctx.message.author.mention} called {member.mention} a dolt',
        f'{ctx.message.author.mention} called {member.mention} a donkey',
        f'{ctx.message.author.mention} called {member.mention} a donkey dick',
        f'{ctx.message.author.mention} called {member.mention} a doofus',
        f'{ctx.message.author.mention} called {member.mention} a dope',
        f'{ctx.message.author.mention} called {member.mention} a dotterel',
        f'{ctx.message.author.mention} called {member.mention} a douche',
        f'{ctx.message.author.mention} called {member.mention} a douche bag',
        f'{ctx.message.author.mention} called {member.mention} a doucheburger',
        f'{ctx.message.author.mention} called {member.mention} a douche canoe',
        f'{ctx.message.author.mention} called {member.mention} a douchelord',
        f'{ctx.message.author.mention} called {member.mention} a douche nark',
        f'{ctx.message.author.mention} called {member.mention} a douche nozzle',
        f'{ctx.message.author.mention} called {member.mention} a douchewad',
        f'{ctx.message.author.mention} called {member.mention} a douchewagon',
        f'{ctx.message.author.mention} called {member.mention} a dracula',
        f'{ctx.message.author.mention} called {member.mention} a dreamer',
        f'{ctx.message.author.mention} called {member.mention} a drug dealer',
        f'{ctx.message.author.mention} called {member.mention} a drunkard',
        f'{ctx.message.author.mention} called {member.mention} a dumbarse',
        f'{ctx.message.author.mention} called {member.mention} a dumbass',
        f'{ctx.message.author.mention} called {member.mention} a dumbbell',
        f'{ctx.message.author.mention} called {member.mention} a dumb blonde',
        f'{ctx.message.author.mention} called {member.mention} a dumbo',
        f'{ctx.message.author.mention} called {member.mention} a dummy',
        f'{ctx.message.author.mention} called {member.mention} a dunce',
        f'{ctx.message.author.mention} called {member.mention} a duncebucket',
        f'{ctx.message.author.mention} called {member.mention} a dweeb',
        f'{ctx.message.author.mention} called {member.mention} a dweebling',
        f'{ctx.message.author.mention} called {member.mention} an edgelord',
        f'{ctx.message.author.mention} called {member.mention} an egghead',
        f'{ctx.message.author.mention} called {member.mention} an egotist',
        f'{ctx.message.author.mention} called {member.mention} an envirotard',
        f'{ctx.message.author.mention} called {member.mention} an evildoer',
        f'{ctx.message.author.mention} called {member.mention} a fart',
        f'{ctx.message.author.mention} called {member.mention} a fartface',
        f'{ctx.message.author.mention} called {member.mention} a fartknocker',
        f'{ctx.message.author.mention} called {member.mention} a fartman',
        f'{ctx.message.author.mention} called {member.mention} a fart sucker',
        f'{ctx.message.author.mention} called {member.mention} a fatass',
        f'{ctx.message.author.mention} called {member.mention} a fatso',
        f'{ctx.message.author.mention} called {member.mention} a fatty',
        f'{ctx.message.author.mention} called {member.mention} a fellow',
        f'{ctx.message.author.mention} called {member.mention} a fembot',
        f'{ctx.message.author.mention} called {member.mention} a fetus',
        f'{ctx.message.author.mention} called {member.mention} a fibber',
        f'{ctx.message.author.mention} called {member.mention} a fink',
        f'{ctx.message.author.mention} called {member.mention} a first time skier',
        f'{ctx.message.author.mention} called {member.mention} a fish',
        f'{ctx.message.author.mention} called {member.mention} a fishwife',
        f'{ctx.message.author.mention} called {member.mention} a fixer',
        f'{ctx.message.author.mention} called {member.mention} a flake',
        f'{ctx.message.author.mention} called {member.mention} a flat-earther',
        f'{ctx.message.author.mention} called {member.mention} a fleabag',
        f'{ctx.message.author.mention} called {member.mention} a flip-flopper',
        f'{ctx.message.author.mention} called {member.mention} a fool',
        f'{ctx.message.author.mention} called {member.mention} a foreskin ripper',
        f'{ctx.message.author.mention} called {member.mention} a foul mouth',
        f'{ctx.message.author.mention} called {member.mention} a four eyes',
        f'{ctx.message.author.mention} called {member.mention} a fraggle',
        f'{ctx.message.author.mention} called {member.mention} a fruitcake',
        f'{ctx.message.author.mention} called {member.mention} a frump',
        f'{ctx.message.author.mention} called {member.mention} a fugly',
        f'{ctx.message.author.mention} called {member.mention} a funpire',
        f'{ctx.message.author.mention} called {member.mention} a furry',
        f'{ctx.message.author.mention} called {member.mention} a gangster',
        f'{ctx.message.author.mention} called {member.mention} a gaper',
        f'{ctx.message.author.mention} called {member.mention} a garbage',
        f'{ctx.message.author.mention} called {member.mention} a gawk',
        f'{ctx.message.author.mention} called {member.mention} a gaywad',
        f'{ctx.message.author.mention} called {member.mention} a geebag',
        f'{ctx.message.author.mention} called {member.mention} a geek',
        f'{ctx.message.author.mention} called {member.mention} a gimp',
        f'{ctx.message.author.mention} called {member.mention} a git',
        f'{ctx.message.author.mention} called {member.mention} a goblin',
        f'{ctx.message.author.mention} called {member.mention} a gobshite',
        f'{ctx.message.author.mention} called {member.mention} a gold digger',
        f'{ctx.message.author.mention} called {member.mention} a goof',
        f'{ctx.message.author.mention} called {member.mention} a goon',
        f'{ctx.message.author.mention} called {member.mention} a goose',
        f'{ctx.message.author.mention} called {member.mention} a GoPro Kid',
        f'{ctx.message.author.mention} called {member.mention} a gorilla',
        f'{ctx.message.author.mention} called {member.mention} an idiot',
        f'{ctx.message.author.mention} called {member.mention} an idiotist',
        f'{ctx.message.author.mention} called {member.mention} an idiot sandwich',
        f'{ctx.message.author.mention} called {member.mention} a pansy',
        f'{ctx.message.author.mention} called {member.mention} a pariah',
        f'{ctx.message.author.mention} called {member.mention} a peasant',
        f'{ctx.message.author.mention} called {member.mention} a pedophile',
        f'{ctx.message.author.mention} called {member.mention} a Rumple-Foreskin',
        f'{ctx.message.author.mention} called {member.mention} a runt',
        f'{ctx.message.author.mention} called {member.mention} a sadist',
        f'{ctx.message.author.mention} called {member.mention} a saggy fuck',
        f'{ctx.message.author.mention} called {member.mention} a saprophyte',
        f'{ctx.message.author.mention} called {member.mention} a sausage-masseuse',
        f'{ctx.message.author.mention} called {member.mention} a scaredy-cat',
        f'{ctx.message.author.mention} called {member.mention} a scobberlotcher',
        f'{ctx.message.author.mention} called {member.mention} a scoozie',
        f'{ctx.message.author.mention} called {member.mention} a scoundrel',
        f'{ctx.message.author.mention} called {member.mention} a screw up',
        f'{ctx.message.author.mention} called {member.mention} a scrote',
        f'{ctx.message.author.mention} called {member.mention} a scrotum-sucker',
        f'{ctx.message.author.mention} called {member.mention} a scumbag',
        f'{ctx.message.author.mention} called {member.mention} a scumbreath',
        f'{ctx.message.author.mention} called {member.mention} a scumbutt',
        f'{ctx.message.author.mention} called {member.mention} a scumface',
        f'{ctx.message.author.mention} called {member.mention} a scumfuck',
        f'{ctx.message.author.mention} called {member.mention} a scumhead',
        f'{ctx.message.author.mention} called {member.mention} a scumlord',
        f'{ctx.message.author.mention} called {member.mention} a scumwad',
        f'{ctx.message.author.mention} called {member.mention} a scuzzbag',
        f'{ctx.message.author.mention} called {member.mention} a serf',
        f'{ctx.message.author.mention} called {member.mention} a sewer rat',
        f'{ctx.message.author.mention} called {member.mention} a shark',
        f'{ctx.message.author.mention} called {member.mention} a sheepfucker',
        f'{ctx.message.author.mention} called {member.mention} a sheepshagger',
        f'{ctx.message.author.mention} called {member.mention} a shill',
        f'{ctx.message.author.mention} called {member.mention} a shitass',
        f'{ctx.message.author.mention} called {member.mention} a shitbag',
        f'{ctx.message.author.mention} called {member.mention} a shitball',
        f'{ctx.message.author.mention} called {member.mention} a shitbird',
        f'{ctx.message.author.mention} called {member.mention} a shitbrain',
        f'{ctx.message.author.mention} called {member.mention} a shitbreath',
        f'{ctx.message.author.mention} called {member.mention} a shitbucket',
        f'{ctx.message.author.mention} called {member.mention} a shitbum',
        f'{ctx.message.author.mention} called {member.mention} a windfucker',
        f'{ctx.message.author.mention} called {member.mention} a window licker',
        f'{ctx.message.author.mention} called {member.mention} a windsucker',
        f'{ctx.message.author.mention} called {member.mention} a wino',
        f'{ctx.message.author.mention} called {member.mention} a witch',
        f'{ctx.message.author.mention} called {member.mention} a womanizer',
        f'{ctx.message.author.mention} called {member.mention} a zitface',
        f'{ctx.message.author.mention} called {member.mention} a zoophile',
        f'{ctx.message.author.mention} called {member.mention} a zounderkite',

  ]
  await ctx.send(random.choice(revenge_messages))  

    # on_guild_join is modified from CreeperBot
            



@bot.command()
async def pingbot(ctx):
    description = '''Bot's ping will be shown''' 
    ping_ = bot.latency
    ping =  round(ping_ * 1000)
    await ctx.send(f"my ping is {ping}ms")

@bot.command()
async def starwars(ctx,*,q="Starwars"):
    description = '''Gets a starwars gif''' 

    api_key = 'APIKEY'
    api_instance = giphy_client.DefaultApi()

    try:

        api_response = api_instance.gifs_search_get(api_key, q,)
        lst = list(api_response.data)
        giff = random.choice(lst)
        emb = discord.Embed(title=q)
        emb.set_image(url=f'https://media.giphy.com/media/{giff.id}/giphy.gif')
        await ctx.send(embed=emb)
    except ApiException as e:
        print("Exception when calling Api")
        
please_wait_emb = discord.Embed(title="Please Wait", description="``` Processing Your Request ```", color=0xff0000)
please_wait_emb.set_author(name="Quinntavich Bot")
please_wait_emb.set_thumbnail(url="https://c.tenor.com/I6kN-6X7nhAAAAAj/loading-buffering.gif")


@bot.command()
async def pwdstrength(ctx, *, passwordhere):
  loading_message = await ctx.send(embed=please_wait_emb)
  try:
    stats = PasswordStats(f'{passwordhere}')
    embed=discord.Embed(title="Password Strength Checker", color=0x00ff00)
    embed.add_field(name="Strenth:", value=f"{stats.strength()}", inline=False)
    embed.set_footer(text=f"Requested by {ctx.author.name}")
    await loading_message.delete()
    await ctx.send(embed=embed)
  
  except Exception as e:
    embed3=discord.Embed(title=":red_square: Error!", description="The command was unable to run successfully! ", color=0xff0000)
    embed3.set_author(name="Quinntavich Bot", icon_url="https://cdn.discordapp.com/attachments/877796755234783273/879295069834850324/Avatar.png")
    embed3.set_thumbnail(url="https://cdn.discordapp.com/attachments/877796755234783273/879298565380386846/sign-red-error-icon-1.png")
    embed3.add_field(name="Error:", value=f"{e}", inline=False)
    embed3.set_footer(text=f"Requested by {ctx.author.name}")
    await loading_message.delete()
    await ctx.send(embed=embed3)

please_wait_emb = discord.Embed(title="Please Wait", description="``` Processing Your Request ```", color=0x00ff00)
please_wait_emb.set_author(name="Quinntavich Bot")
please_wait_emb.set_thumbnail(url="https://c.tenor.com/I6kN-6X7nhAAAAAj/loading-buffering.gif")


filepwdlist1 = open("c:/Users/Quinn H/Desktop/QuinntavichBot/10-million-password-list-top-1000000.txt", "r")
lines = filepwdlist1.readlines() 


@bot.command()
async def pwdcheck(ctx, *, password):
    loading_message = await ctx.send(embed=please_wait_emb)

    try:
        if password + "\n" in lines: 
            embed=discord.Embed(title="Password Checker!", color=0xff0000)
            embed.set_author(name="Quinntavich Bot", icon_url="https://cdn.discordapp.com/attachments/881007500588089404/881046764206039070/unknown.png")
            embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/877796755234783273/879311068097290320/PngItem_1526969.png")
            embed.add_field(name=f"Your Password", value=f"{password}", inline=False)
            embed.add_field(name=f"Safety", value=f"Not Safe. This password is in the list of most common 10 million passwords!", inline=False)
            embed.set_footer(text=f"Requested by {ctx.author.name}")
            await loading_message.delete()
            await ctx.send(embed=embed)
        else:
            embed=discord.Embed(title="Password Checker!", color=0x00FF00)
            embed.set_author(name="Quinntavich Bot", icon_url="https://cdn.discordapp.com/attachments/881007500588089404/881046764206039070/unknown.png")
            embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/877796755234783273/879311068097290320/PngItem_1526969.png")
            embed.add_field(name=f"Your Password", value=f"{password}", inline=False)
            embed.add_field(name=f"Safety", value=f"Safe. This password is not in the list of most common 10 million passwords!", inline=False)
            embed.set_footer(text=f"Requested by {ctx.author.name}")
            await loading_message.delete()
            await ctx.send(embed=embed)

    except Exception as e:
        embed2=discord.Embed(title=":red_square: Error!", description="This command has failed because bot is crust. The problem will hopefully be fixed soon. :skull:", color=0xff0000)
        embed2.set_author(name="Quinntavich Bot", icon_url="https://cdn.discordapp.com/attachments/881007500588089404/881046764206039070/unknown.png")
        embed2.set_thumbnail(url="https://cdn.discordapp.com/attachments/877796755234783273/879298565380386846/sign-red-error-icon-1.png")
        embed2.add_field(name="Error:", value=f"{e}", inline=False)
        embed2.set_footer(text=f"Requested by {ctx.author.name}")
        await loading_message.delete()
        await ctx.send(embed=embed2)
        
@bot.command()
async def botcool(ctx):
    description = '''Is the bot cool?''' 
    await ctx.send('Yes, the bot is cool.')
@bot.command()
async def cool(ctx, member: discord.Member):
    description = '''Are they cool???!!!'''
    cool_messages = [
        f'Yes! {member.mention} is cool!',
        f'Nahh, {member.mention} kinda sucks ngl',
        
    ]

    
    await ctx.send(random.choice(cool_messages)) 
     
        


@starwars.error
async def starwars_error(ctx, error):
    if isinstance(error, discord.ext.commands.errors.MissingRequiredArgument):
        await ctx.send("This command has failed because bot is crust. The problem will hopefully be fixed soon. :skull:")

@spam.error
async def hello_error(ctx, error):
        if isinstance(error, discord.ext.commands.errors.MissingRequiredArgument):
                await ctx.send("This command has failed because bot is crust. The problem will hopefully be fixed soon. :skull:")
bot.run('BOTKEY')

