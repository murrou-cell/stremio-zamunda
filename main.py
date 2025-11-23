import logging
import threading
import time
from zamunda_api.zamunda import Zamunda 
from manifest import manifest
from omdb import Omdb
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from fastapi.responses import HTMLResponse
import re
logger = logging.getLogger("uvicorn")
zamunda = Zamunda()
omdb = Omdb(logger)
app = FastAPI()

cache = {}

def is_single_episode(name, season, episode):
    tag = f"S{int(season):02d}E{int(episode):02d}".lower()
    return tag in name.lower()

def is_full_season(name, season):
    s = int(season)
    # хвърля True ако името съдържа S01 или Season 1
    # но не съдържа S01E01, S01E02 и т.н.
    if re.search(rf"\bS{s:02d}\b", name, re.IGNORECASE) or re.search(rf"\bSeason {s}\b", name, re.IGNORECASE):
        # проверка за епизод, ако има → не е пълен сезон
        if not re.search(r"S\d\dE\d\d", name, re.IGNORECASE):
            return True
    return False


def find_episode_in_files(torrent, season, episode):
    tag = f"S{int(season):02d}E{int(episode):02d}".lower()
    video_ext = (".mkv", ".mp4", ".avi", ".mov", ".flv")

    for index, (filename, size) in enumerate(torrent["files"]):
        lower = filename.lower()
        if not lower.endswith(video_ext):
            continue
        if tag in lower:
            return index, size
    return None

def buildStream(torrent,bgAudio, fileIdx = None, fileSize = None):
    torentIsBgAudio = torrent['bg_audio']
    if bgAudio and not torentIsBgAudio:
        return None
    if fileSize is not None:
        sizeString = f"💾{bytesToHumanReadable(fileSize)}/{torrent['size']}"
    else:
        sizeString = f"💾{torrent['size']}"

    if fileIdx is not None: # bingeGroup
        bingeGroup = f"zamunda-{'bg' if torrent['bg_audio'] else 'nonbg'}-binge"
    else:
        bingeGroup = f"zamunda-{'bg' if torrent['bg_audio'] else 'nonbg'}"

    result = {
        "name": f"Zamunda.net\n {'🇧🇬🔊' if torrent['bg_audio'] else ''} {sizeString} - 👤{torrent['seeders']}",
        "infoHash": torrent["infohash"],
        "description": f"{torrent['name']}",
        "behaviorHints": {"bingeGroup": bingeGroup}
    }
    if fileIdx is not None:
        result["fileIdx"] = fileIdx
    return result

def bytesToHumanReadable(num):
    for unit in ['B','KB','MB','GB','TB']:
        if num < 1024.0:
            return f"{num:.2f}{unit}"
        num /= 1024.0
    return f"{num:.2f}PB"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

#redirect to manifest.json
@app.get("/")
def redirect_to_manifest():
    return HTMLResponse('<script>window.location.href = "/manifest.json";</script>')

app.get("/")(redirect_to_manifest)

@app.get("/manifest.json")
def get_manifest():
    return manifest

@app.get("/{configuration}/manifest.json")
def get_manifest_with_config(configuration: str):
    newManifest = manifest.copy()
    newManifest.pop("behaviorHints")
    return newManifest

@app.get("/configure", response_class=HTMLResponse)
def config_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Configuration Page</title>
        <script>
            function generateStremioLink() {
                const omdbKey = document.getElementById('omdb_key').value;
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                const bgAudio = document.getElementById('bg_audio').checked ? "on" : "off";

                // Create a configuration string
                let configurationValue = [
                    ['omdb_key', omdbKey],
                    ['username', username],
                    ['password', password],
                    ['bg_audio', bgAudio]
                ].filter(([_, value]) => value.length).map(([key, value]) => key + '=' + encodeURIComponent(value)).join('|');
                
                // Construct the Stremio URL
                const location = window.location.host + '/' + configurationValue + '/manifest.json';
                const installLink = 'stremio://' + location;
                
                // Set the window location to the generated Stremio URL
                window.location.href = installLink;
            }
        </script>
    </head>
    <body>
        <h1>Конфигурация:</h1>
        <form action="javascript:void(0);" onsubmit="generateStremioLink()">
            <label for="omdb_key">OMDB API Key (<a target="blank" href="https://www.omdbapi.com/apikey.aspx">тук<a/>):</label><br>
            <input type="text" id="omdb_key" name="omdb_key" required><br>
            <label for="username">Zamunda потребителско име:</label><br>
            <input type="text" id="username" name="username" required><br>
            <label for="password">Zamunda парола:</label><br>
            <input type="password" id="password" name="password" required><br><br>
            <label for="bg_audio">Само торенти с българско аудио:</label>
            <input type="checkbox" id="bg_audio" name="bg_audio"><br><br>
            <input type="submit" value="Инсталиране">
        </form>
    </body>
    </html>
    """
    
@app.get("/{configuration}/stream/{type}/{id}")
def get_stream(configuration:str, type: str, id: str):
    configuration = configuration.split("|")
    omdbKey = None
    username = None
    password = None
    bgAudio = False
    for config in configuration:
        key,value = config.split("=")
        if key == "omdb_key":
            omdbKey = value
        elif key == "username":
            username = value
        elif key == "password":
            password = value
        elif key == "bg_audio":
            bgAudio = value == "on"

    id = id.replace(".json","")
    if omdbKey is None or username is None or password is None:
        return {"error": "Invalid configuration"}
    else:
        cacheKey = f"{omdbKey}-{username}-{password}-{type}-{id}-{bgAudio}"
        if cacheKey in cache and cache[cacheKey]['timestamp'] > time.time() - 60*60:
            logger.info("Using cache")
            return cache[cacheKey]['data']
        
    if type == "movie":
        title = omdb.get_title(id,omdbKey)
        if title is None:
            return {"error": "Could not find movie"}
        zamundaData = zamunda.search(title,username,password,True)
        if zamundaData is None:
            return {"error": "Could not find movie"}
        streams = []
        for torrent in zamundaData:
            streams.append(buildStream(torrent,bgAudio))
        cache[cacheKey] = {"timestamp": time.time(), "data": {"streams": streams}}
        logger.info(f"Founds {len(streams)} streams")
        return {"streams": streams}
    
    elif type == "series":
        imdbId,season,episode = id.split(":")
        title = omdb.get_title(imdbId,omdbKey)
        if title is None:
            return {"error": "Could not find series"}

        # 1) Първо търсим конкретния епизод "S00E00" формат
        search_title = f"{title} S{int(season):02d}E{int(episode):02d}"
        zamundaData = zamunda.search(search_title, username, password, True, False)

        # 2) После търсим и целия сезон по "S00" i "Season 0" формата
        search_season = f"{title} S{int(season):02d}"
        seasonData = zamunda.search(search_season, username, password, True, True)
        search_season_alt = f"{title} Season {int(season)}"
        seasonDataAlt = zamunda.search(search_season_alt, username, password, True, True)

        # комбинираме резултатите без дублиране
        allResults = []
        seen = set()

        for t in (zamundaData or []):
            if t["infohash"] not in seen:
                allResults.append(t)
                seen.add(t["infohash"])

        for t in (seasonData or []):
            if t["infohash"] not in seen:
                allResults.append(t)
                seen.add(t["infohash"])

        for t in (seasonDataAlt or []):
            if t["infohash"] not in seen:
                allResults.append(t)
                seen.add(t["infohash"])

        if not allResults:
            return {"streams": []}

        streams = []

        for torrent in allResults:
            name = torrent["name"]

            # CASE A: единичен епизод
            if is_single_episode(name, season, episode):
                s = buildStream(torrent, bgAudio)
                if s:
                    streams.append(s)
                continue

            # CASE B: сезонен пакет → трябва да намерим епизода вътре
            if is_full_season(name, season):
                idx, size = find_episode_in_files(torrent, season, episode)
                if idx is not None:
                    s = buildStream(torrent, bgAudio, fileIdx=idx, fileSize=size)
                    if s:
                        streams.append(s)
                continue

        cache[cacheKey] = {"timestamp": time.time(), "data": {"streams": streams}}
        logger.info(f"Found {len(streams)} streams")
        return {"streams": streams}
    else:
        return {"error": "Invalid type"}

#clear cache every 5 minutes
def clear_expired_cache():
    while True:
        time.sleep(60*5)
        for key in list(cache.keys()):
            if cache[key]['timestamp'] < time.time() - 60*60:
                cache.pop(key)
        logger.info(f"Cleared cache for {len(cache)} items")

if __name__ == "__main__":
    threading.Thread(target=clear_expired_cache).start()
    uvicorn.run(app, host="0.0.0.0", port=7000)


    
