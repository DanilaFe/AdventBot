import discord
from discord.ext import tasks
import os
import sqlite3
from collections import defaultdict
from aiohttp import ClientSession
import json

client = discord.Client()
conn = sqlite3.connect('data.db')
star_names = { '1': 'silver', '2': 'gold' }
aoc_session = os.getenv('AOC_SESSION')
bot_token = os.getenv('AOC_BOT_TOKEN')

@client.event
async def on_ready():
    print('We have logged in as {0.user}'.format(client))

@client.event
async def on_message(message):
    if message.content.startswith("!setup"):
        leaderboard = int(message.content[7:])
        conn.execute('''
            insert into guild(id, channel, leaderboard, last_sync)
            values (?, ?, ?, ?) on conflict(id) do
            update set channel=excluded.channel, leaderboard=excluded.leaderboard''',
            (message.guild.id, message.channel.id, leaderboard, None))
        conn.commit()
        await message.channel.send(
                'Updated {0.guild} to use channel {0.channel} and leaderboard {1}!'
                    .format(message, leaderboard))

def setup():
    '''
    Create all the necessary tables and all that.
    '''

    conn.execute('''
        CREATE TABLE IF NOT EXISTS
            guild(id int primary key, channel int, leaderboard int, last_sync text)
        ''')

def member_stars(member):
    '''
    Find the stars attributed to a single member
    in the JSON response. Takes a JSON object
    from the 'members' dict.
    '''

    star_list = []
    for day in member['completion_day_level']:
        stars = member['completion_day_level'][day]
        for (star, name) in star_names.items():
            if star not in stars: continue
            star_list.append(
                (member['name'], day, name, stars[star]['get_star_ts']))
    return star_list

def all_stars(json):
    '''
    Find all the stars in a given JSON response.
    The stars are not ordered in any way.
    '''

    return [star for m in json['members'].values() for star in member_stars(m)]

def stars_by_day(stars):
    '''
    Groups stars by day, then by type (silver/gold).
    Helpful when trying to figure out if a given star
    was "early" (first/second/third) for a particular puzzle.
    '''

    by_day = defaultdict(lambda: defaultdict(lambda: []))
    for star in stars:
        by_day[star[1]][star[2]].append(star)
    return by_day

def read_json(s):
    '''
    Try to parse a JSON response. If the argument
    is None (which it can be if we're pulling from a fresh database)
    fill it with just enough dummy enough to make the update
    algorithms work.
    '''

    if s is None: return {'members': {}}
    return json.loads(s)
    
def detect_early_stars(stars):
    '''
    Detects stars for each puzzle that are 'first', 'second', and 'third'.
    This helps make the announcements a little more interesting!
    '''

    by_day = stars_by_day(stars)
    early_stars = []
    for (day, names) in by_day.items():
        for (name, stars) in names.items():
            stars.sort(key=lambda star: int(star[3]))
            early_stars += list(zip(['first', 'second', 'third'], stars))
    return early_stars

def find_updates(old_json, new_json):
    '''
    Find interesting differences between the old JSON and the new JSON,
    both given as either strings or None.

    Interesting differences include member joins (for whom
    we do not print new stars, since they weren't on the learderboard
    when they won them), early stars (first/second/third) and other
    stars (anyone winning a star at any point).
    '''

    old_json = read_json(old_json)
    new_json = read_json(new_json)

    old_stars = all_stars(old_json)
    new_stars = all_stars(new_json)

    join = [new_json['members'][m] for m in new_json['members'] if m not in old_json['members']]
    early_stars = [ star for star in detect_early_stars(new_stars)
            if star[1] not in old_stars
                and star[1][0] not in join ]
    skip_stars = [early_star for (place, early_star) in early_stars]
    ann_stars = [ star for star in new_stars
            if star not in skip_stars
                and star not in old_stars
                and star[0] not in join ]
    return { 'join': join, 'early_stars': early_stars, 'ann_stars': ann_stars }

async def send_updates(id, channel, diff):
    '''
    Send updates via the Discord client given a diff
    produced by `find_updates`.
    '''

    announcements = []
    for user in diff['join']:
        full_text = "User {0} joined the leaderboard!".format(user)
        announcements.append(full_text)
    for (place, (user, day, star, ts)) in diff['early_stars']:
        full_text = "{0} won the {1} {2} star from day {3}!".format(user, place, star, day)
        announcements.append(full_text)
    for (user, day, star, ts) in diff['ann_stars']:
        full_text = "{0} won the {1} star from day {2}!".format(user, star, day)
        announcements.append(full_text)

    if len(announcements) != 0:
        channel = await client.fetch_channel(channel)
        await channel.send("\n".join(announcements))

@tasks.loop(minutes=1.0)
async def update_aoc():
    url_string = "https://adventofcode.com/2020/leaderboard/private/view/{0}.json"
    cookies = { 'session': aoc_session }

    async with ClientSession(cookies=cookies) as session:
        for (id, channel, leaderboard, json) in conn.execute('select * from guild'):
            async with session.get(url_string.format(leaderboard)) as resp:
                new_json = await resp.text()
                diff = find_updates(json, new_json)
                await send_updates(id, channel, diff)
                conn.execute('update guild set last_sync=? where id=?', (new_json, id))
                conn.commit()

setup()
update_aoc.start()
client.run(bot_token)
