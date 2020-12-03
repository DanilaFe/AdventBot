import discord
from discord.ext import tasks
import os
import sqlite3
from aiohttp import ClientSession
import json

client = discord.Client()
conn = sqlite3.connect('data.db')

def setup():
    conn.execute('''
        CREATE TABLE IF NOT EXISTS
            guild(id int primary key, channel int, leaderboard int, last_sync text)
        ''')

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

def gather_stars(member):
    star_list = []
    for day in member['completion_day_level']:
        stars = member['completion_day_level'][day]
        if "1" in stars:
            star_list.append((member['name'], int(day), 1, stars['1']['get_star_ts']))
        if "2" in stars:
            star_list.append((member['name'], int(day), 2, stars["2"]['get_star_ts']))
    return star_list

def perform_member_diff(old_member, new_member):
    old_stars = gather_stars(old_member)
    new_stars = gather_stars(new_member)
    return [star for star in new_stars if star not in old_stars]

def perform_diff(old_json, new_json):
    if old_json is None:
        old_json = {'members': {}}
    else:
        old_json = json.loads(old_json)
    new_json = json.loads(new_json)
    diff = { 'join': [], 'new_stars': [] }
    for new_member in new_json['members'].keys():
        if new_member not in old_json['members']:
            diff['join'].append(new_json['members'][new_member]['name'])
            continue
        member_diff = perform_member_diff(old_json['members'][new_member], new_json['members'][new_member])
        diff['new_stars'] += member_diff
    return diff

async def send_diff(id, channel, diff):
    announcements = []
    for user in diff['join']:
        full_text = "User {0} joined the leaderboard!".format(user)
        announcements.append(full_text)
    for (user, day, star, ts) in diff['new_stars']:
        star_name = "silver" if star == 1 else "gold"
        full_text = "{0} won the {1} star from day {2}!".format(user, star_name, day)
        announcements.append(full_text)

    if len(announcements) != 0:
        channel = await client.fetch_channel(channel)
        await channel.send("\n".join(announcements))

@tasks.loop(minutes=1.0)
async def update_aoc():
    url_string = "https://adventofcode.com/2020/leaderboard/private/view/{0}.json"
    cookies = { 'session': os.getenv("AOC_SESSION") }

    async with ClientSession(cookies=cookies) as session:
        for (id, channel, leaderboard, json) in conn.execute('select * from guild'):
            async with session.get(url_string.format(leaderboard)) as resp:
                new_json = await resp.text()
                diff = perform_diff(json, new_json)
                await send_diff(id, channel, diff)
                conn.execute('update guild set last_sync=? where id=?', (new_json, id))
                conn.commit()

setup()
update_aoc.start()
client.run(os.environ['AOC_BOT_TOKEN'])
