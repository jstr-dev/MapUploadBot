"""Map upload discord bot"""

import discord 
import re 
import requests 
import os
import patoolib
import shutil
import bz2
import aiohttp
import aiofiles
import pwd
import grp

##################################### Settings #####################################
CLIENT_TOKEN = "DISCORD TOKEN" # Token of discord bot
MAPS_USER = "gmodserver" # Name of linux user that controls the gameserver
FASTDL_USER = "justa" # Name of linux user that controls the fastdl 
MAPS_LOCATION = "/home/gmodserver/serverfiles/garrysmod/maps/" # Location of maps folder on your server
FASTDL_LOCATION = "/var/www/html/fastdl/maps/" # Location of FastDL folder on your server
####################################################################################

VERSION_NUMBER = "1.0.0"
QUEUETYPE_GAMEBANANA = 1
QUEUETYPE_FASTDL = 2 

discord_client = discord.Bot(intents=discord.Intents.all())
queue = []
queue_inprogress = False 
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36"
}

mapsgroup = grp.getgrnam(MAPS_USER).gr_gid
mapsuser = pwd.getpwnam(MAPS_USER).pw_uid
webgroup = grp.getgrnam(FASTDL_USER).gr_gid
webuser = pwd.getpwnam(FASTDL_USER).pw_uid

def Cleanup() -> None:
    """Removes temporary directories and their contents used by the appplication"""
    if os.path.exists("downloaded"): shutil.rmtree("downloaded")
    if os.path.exists("extracted"): shutil.rmtree("extracted")

def CreateDirectories() -> None:
    """Creates temporary directories used by the application"""
    Cleanup()
    if not os.path.exists("downloaded"): os.mkdir("downloaded")
    if not os.path.exists("extracted"): os.mkdir("extracted")

def GetGamebananaID(url: str) -> int:
    """Extracts the ID from a gamebanana link."""
    try:
        return int(re.search("gamebanana.com/mods/([0-9]+)", url).group(1))
    except:
        raise Exception("Invalid Gamebanana URL.")


def GetGamebananaInfo(id: int):
    """Gets information from gamebanana about a mod"""

    response = requests.get(f"https://api.gamebanana.com/Core/Item/Data?itemtype=Mod&itemid={id}&fields=name,Files().aFiles()")
    if response.status_code != 200:
        raise Exception("Couldn't fetch data from Gamebanana API.")
    response = response.json()

    id = list(response[1])[0]
    mod_name = response[0]
    file_name = response[1][id]["_sFile"]
    file_size = response[1][id]["_nFilesize"]
    download_url = response[1][id]["_sDownloadUrl"]

    return mod_name, file_name, file_size, download_url

def FindRelevantFiles(directory: str) -> list:
    """Finds all relevant files in a directory, looks for .bsp and .nav files"""
    lst = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if (file.endswith(".bsp") or file.endswith(".nav")):
                lst.append(root + "/" + file)
    return lst 

def GetFastDLHasNav(map: str) -> bool:
    """Validates whether a map is on Avacado's fastdl and returns whether it has a nav file with it."""
    response = requests.head(f"https://main.fastdl.me/maps/{map}.bsp.bz2", headers=headers)
    if response.status_code != 302:
        raise Exception("Couldn't find map on Avacados's FastDL.")
    nav_response = requests.head(f"https://main.fastdl.me/maps/{map}.nav.bz2", headers=headers)
    return (nav_response.status_code == 200)

async def ProcessQueue() -> None:
    """Attempts to process queue items"""
    global queue_inprogress

    if (queue_inprogress): return 
    if (len(queue) == 0): return  

    queue_inprogress = True 

    package = queue.pop()
    channel = package.get("channel")
    user = package.get("mention")
    data = package.get("data")
    queuetype = package.get("type")
    
    if (queuetype == QUEUETYPE_GAMEBANANA):
        await channel.send(f"Processing Gamebanana request **{data[0]}** by {user.mention}")

        await channel.send(f"Downloading {data[1]}...")
        async with aiohttp.ClientSession() as session:
            async with session.get(data[3]) as response:
                filepath = "downloaded/" + data[1]
                map_file = await aiofiles.open(filepath, mode="wb")
                await map_file.write(await response.read())
                await map_file.close()

                await channel.send(f"{data[1]} downloaded, extracting...")
                filename, fileext = os.path.splitext(data[1])
                extractedpath = f"extracted/{filename}"
                os.mkdir(extractedpath)
                patoolib.extract_archive(filepath, outdir=extractedpath)
                files = FindRelevantFiles(extractedpath)
                await channel.send(f"Extraction complete, {len(files)} relevant file(s) found: " + ', '.join(os.path.basename(x) for x in files))

                await channel.send(f"Compressing map(s) for FastDL...")
                for file in files:
                    filedata = open(file, "rb")
                    compressed_data = bz2.compress(filedata.read())
                    filedata.close()
                    fastdl = open(FASTDL_LOCATION + os.path.basename(file) + ".bz2", "wb")
                    fastdl.write(compressed_data)
                    fastdl.close()
                    os.rename(file, MAPS_LOCATION + os.path.basename(file))
                    os.chown(MAPS_LOCATION + os.path.basename(file), mapsgroup, mapsuser)
                    os.chown(FASTDL_LOCATION + os.path.basename(file) + ".bz2", webgroup, webuser)

                os.remove(filepath)
                shutil.rmtree(extractedpath)
                await channel.send(f"Gamebanana request **{data[0]}** completed {user.mention}")
    elif (queuetype == QUEUETYPE_FASTDL):
        await channel.send(f"Processing Avacado's FastDL request **{data[0]}** by {user.mention}")

        download = [data[0] + ".bsp.bz2"]
        if data[1]: download.append(data[0] + ".nav.bz2")

        for f in download:
            await channel.send(f"Downloading {f}...")

            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://main.fastdl.me/maps/{f}") as response:
                    filepath = "downloaded/" + f
                    map_file = await aiofiles.open(filepath, mode="wb")
                    await map_file.write(await response.read())
                    await map_file.close()

                    await channel.send(f"{f} downloaded, extracting...")
                    filename, fileext = os.path.splitext(f)
                    mappath = MAPS_LOCATION + f.replace(".bz2", "")
                    if os.path.exists(mappath): os.remove(mappath)
                    patoolib.extract_archive(filepath, outdir=MAPS_LOCATION)
                    os.chown(mappath, mapsgroup, mapsuser)
                    await channel.send(f"Extraction complete")

                    fastdlpath = FASTDL_LOCATION + os.path.basename(f)
                    if os.path.exists(fastdlpath): os.remove(fastdlpath)
                    os.rename(filepath, fastdlpath)
                    os.chown(fastdlpath, webgroup, webuser)

        await channel.send(f"Avacado's FastDL request **{data[0]}** completed {user.mention}")

    queue_inprogress = False
    await ProcessQueue()

@discord_client.slash_command(description="Attempts to add a map to the gameserver.")
async def addmap(
    ctx,
    method: discord.Option(str, choices=["gamebanana", "avocado"], description="Method to use"),
    query: discord.Option(str)
    ) -> None:
    """Slash command to add a map to a gameserver."""

    if not discord.utils.get(ctx.guild.roles, name="justabotuser") in ctx.author.roles:
        await ctx.respond("You do not have permission for this command.", ephemeral=True)
        return 

    try:
        if (method == "gamebanana"):
            id = GetGamebananaID(query)
            mod_name, file_name, file_size, download_url = GetGamebananaInfo(id)
            queue.append({"type": QUEUETYPE_GAMEBANANA, "data": [mod_name, file_name, file_size, download_url], "channel": ctx.channel, "mention": ctx.author})

            await ctx.respond(f"Gamebanana request **{mod_name}** added to the queue.")
        elif (method == "avocado"):
            hasnav = GetFastDLHasNav(query)
            queue.append({"type": QUEUETYPE_FASTDL, "data": [query, hasnav], "channel": ctx.channel, "mention": ctx.author})

            await ctx.respond(f"Avocado's FastDL request **{query}** added to the queue.")
    except Exception as e:
        await ctx.respond(e, ephemeral=True)
        return 

    await ProcessQueue()

CreateDirectories()
discord_client.run(CLIENT_TOKEN)