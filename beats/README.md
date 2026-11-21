# <img src="brand/siansa-beats-icon.svg" alt="" width="40" height="40" align="top"> Siansa Beats

The companion service for the Siansa app (what it does for the app: [the repository's front page](../README.md)). It
reads the songs of the libraries you choose on Navidrome, Emby or Jellyfin and finds every beat and downbeat in each
with [Beat This!](https://github.com/CPJKU/beat_this) (CPJKU, 2024), with each song's loudness, fades, key, genres
and how it sounds. Its page shows it all: each song's tempo and bars next to the file's BPM tag, so misread songs
stand out, and you can play any song with a click on each beat to hear whether they're right.

It runs in its own container, reads your music servers without changing anything, and keeps what it finds in its own
database. Nothing is written to your music files or the servers. The Siansa app talks to it directly (Settings ›
Services › Siansa Beats) for each song's loudness, fades, key and beat grid, the genres and their descriptions, and
what songs sound like: the [app's API](#the-apps-api-v1). It needs no other service.

| | |
|---|---|
| **Reads** | The libraries chosen on its page (all of them, or leaving some out, as compilations) of Navidrome, Emby and Jellyfin, several of them and several users of one: each song's original file, BPM tag and genre. A song two servers have is analysed once. |
| **Finds** | Every beat and downbeat (Beat This!, the `final0` model, on the CPU or an NVIDIA GPU), and from them the tempo of the whole song and of each end (the first and last 30 seconds), how steady it is, the beats a bar and the first downbeat. Each song's loudness (EBU R128) and how it fades in and out, and its key. |
| **Keeps** | `/data/beats.db` (SQLite) in the container's volume. Each song is downloaded to `/data` while it's read, then deleted. |
| **Shows** | A page at port 8090: what it's doing, a table of every song with what the readings say together, and a page per song with its beats, a player with clicks on the beats, and its tempo along the song. |

## Set it up

You need Docker on a machine that can reach your music server (Navidrome, Emby or Jellyfin), about 3 GB of disk
for the image, and 2–3 GB of memory free while it works. An NVIDIA GPU makes it many times faster; it isn't needed.

1. **Start it.** One file, with nothing to fill in. The image is public, so no login is needed:

   ```
   mkdir -p ~/siansa-beats && cd ~/siansa-beats
   curl -fsSLO https://raw.githubusercontent.com/echovaultstudio/siansa-beats/main/beats/docker-compose.yml
   docker compose up -d
   ```

   With an NVIDIA GPU (and NVIDIA's container toolkit), get `docker-compose.gpu.yml` from the same place too and
   start it with `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`. On TrueNAS:
   [below](#on-truenas-with-a-gpu).

2. **Open http://\<the server\>:8090.** The Overview's **Get started** card walks through the rest, and ticks each
   step as it's done:

   - **Add your music server** (Setup › Music servers): its address, user name and password, as you sign in to
     Siansa.
   - **Choose what to analyse** (Libraries): switch on the libraries you want and press **Start analysis**. Try one
     small library first: a song takes a few seconds on a GPU, much longer on a CPU. Compilations or audiobooks can
     be left off.
   - **Connect the Siansa app**: in the app, Settings › Connections › Siansa Beats, with the address and key shown
     under Setup › Connect the Siansa app.

3. **Optional.** A password for the page and a key for the app (Setup › Access); the model, the CPU cores and the
   log's detail in a `.env` next to the compose file ([Settings](#settings), `.env.example` lists them).

To update later: `docker compose pull && docker compose up -d`. What's been analysed is kept. To watch it work:
`docker compose logs -f`.

### Good to know

**How energetic a song is (0.35).** Beside a song's energy (how loud its frames are), every song with a
sound gets its **arousal**: about 1 (calm) to 9, from Essentia's emoMusic model (MTG, UPF; CC BY-NC-SA 4.0), which
reads the vector already kept for the song. So the whole library is scored once in seconds, with no song read again,
and new songs as they come. In a trial on the owner's library (164 songs, five measures, judged by ear) it matched
what he heard far better than loudness, which once on one scale barely tells songs apart. `/api/v1/sound/songs`
gives it as `arousal`. Energies kept from before 0.35 on an older scale (about 0.05 to 0.4) are given on today's
(`energy_source`: `converted`).

**What a song is like (0.51).** Every song with a sound also gets Essentia's trained traits (MTG, UPF; CC BY-NC-SA
4.0), from eleven small models that read the same kept vector, so the whole library is scored once in seconds with no
song read again, and new songs as they come. Each is a share from 0 to 1: `voice` (0 instrumental, 1 sung), `female`
(of the voice: 0 a man's, 1 a woman's; only worth reading where `voice` is high), `acoustic`, `aggressive`,
`electronic`, `happy`, `party`, `relaxed`, `sad`, `danceable`, and MIREX's five mood groups (`mirex_passionate`,
`mirex_cheerful`, `mirex_bittersweet`, `mirex_humorous`, `mirex_intense`, adding up to 1). Beside the energy's
`arousal` there's now its `valence` too: how positive a song feels, about 1 (dark) to 9 (bright). Their makers
measured the models right for 84 to 98 songs in 100 on their own collections (MIREX's five groups: 67); a song's page
shows what they said, to check on songs you know. `/api/v1/sound/songs` gives them as `traits` and `valence`;
`/api/v1/capabilities` counts them under `traits`. AudioMuse-AI's feelings stay as `other_features`.

**Mixes made from your listening (0.53).** The app's mixes for the time of day were a fixed list by the clock
("sunshine mixes in Finland at 6:40 am, it's winter and dark outside"). Siansa Beats now makes them itself
(`beats/mixes.py`), from what it keeps: when each listen was (the week in ten parts: early morning, morning, afternoon,
evening and night, on weekdays and at the weekend), what the songs sound like (the songs played in a part fall into a
few kinds that sound alike; each kind is a mix of some of them and of songs like them that weren't played for 45
days), and where the sun is (from the date and the time zone's city, or a latitude and longitude from the app: no
weather service). A recent listen counts for more, and one from this time of year in earlier years for a little more.
In the dark the calmer kinds come first; the less is known of a part of the week, the more the hour and the light
count. A mix is named by its sound ("Calm Indie Rock"), never by the weather, and is the same all day. Beside them:
the listener's all-time kinds ("Made for you"), On repeat, Rediscover and New for you. With too little listening a
part borrows from that time on other days, then from all the listening, then from the library. Skips aren't counted:
the app sends finished listens only. The page has **Mixes** in its menu (any part of the week can be looked at), and
the app reads the same from `GET /api/v1/mixes?user=&tz=&at=&lat=&lon=&part=&days=&size=` (`features.mixes` in the
capabilities). The app's own mixes stay as they are.

**Mix names by AI, and mixes made ahead (0.54).** On Setup, **AI for mix names** takes the same AI services as the
Siansa app (OpenRouter, OpenAI, Anthropic, Google Gemini, Mistral, Groq, Ollama, or any other with an OpenAI-style
API; `beats/ai.py`): the mixes of a kind of music are then named by it, like a streaming service's editors would
("Velvet Undertow"), from their genres, energy, mood and three artists only, never the listening. Names that promise
weather or a time of day are thrown away, and the names are kept for the day; until they come a mix shows its sound's
name (`named` on each mix says which). The key is kept encrypted and never shown. And every minute, the mixes of now and
of ten minutes on are made for each listener the app asks for, the way it asked (time zone, place, server): when the
part of the day or the light changes, the app finds the next ones ready. Mixes are kept until the part of the day, the
light or the date changes, or the library or the listening grows by much, not made again at every listen.

**What's in a mix, and how long it's kept (0.55).** Each mix has a short line on its sound (`about`: "Wiry guitars and
restless drums"), from the AI with its name, else from its sound ("Calm ambient, mostly instrumental"); the artists it's
like stay in `why`, for the mix's own page. Every mix given out is kept, by a `key` no other mix has, for 7 days, or as
long as **Keep mixes for** on the Mixes page says (1 to 90 days), so a mix played from the app's recent plays still plays
days later: `GET /api/v1/mixes/kept?user=&key=` gives it back.

**What goes into the mixes (0.56).** Every choice the mixes made by themselves can be changed, per listener, on the
Mixes page (**What goes into your mixes**) or from the Siansa app: which shelves and mixes are made and how many, songs
in a mix, how many of them you know, songs by one artist, how long a song you played stays out, genres and artists to
leave out, whether the part of the day, weekends, the dark and this time of year count, how far back listening counts,
On repeat's and Rediscover's spans, and AI names (`beats/mix_settings.py`, `GET`/`POST /api/v1/mixes/settings`). Left
as they come, the mixes are made as before. After a change, **Make the mixes again** (on the Mixes page, and in the
app's Mix settings) makes them again now, a new pick from the same songs and settings, as many times as wanted that day
(0.60.4; `POST /api/v1/mixes/again` with the `user`; a new day starts afresh).

**Names that match the app, and never the same twice (0.60.5).** The switches on the Mixes page say which row of the
app's Home each mix is in: For now, Made for you, and More of you (On repeat, Rediscover, New for you). No two mixes shown
together share a name: the AI is told the names the listener's other mixes already have, and an AI name that's taken
anyway gives way to the mix's own name from its sound (with a number if that's taken too).

**Vocals done is done (0.61.1).** Songs whose vocals can't be found yet (no voice score, or no beats here) kept the
Overview saying "looking for the next song…" and "46 to go" when every other song was done. They're now counted apart
("✓ all done · 46 can't be done yet"), the Now card doesn't show Vocals for them, and it looks again every ten minutes.

**Names with more to them (0.61.0).** A page no longer says "Hushed" four times. Each mix's name takes a first word
none of the page's other names have, from a bigger choice of words for its sound ("Smoky", "Restless", "Kinetic"…),
and a row takes turns: named for the moment, for its sound, or for who's in it ("Loathe, Spiritbox & more"). The mixes
of now, which are made again when the part of the day, the light or the weather changes, can say the moment: the
weather when the app sends it (`weather=rain`, one word, never where you are; only when its Weather is on), the dark,
a Friday or the weekend's day, the part of the day or the season ("Rainy Folk", "Dark-morning Metalcore", "Sunday
Piano"). The mixes for all day never do. Names from the AI service are as before.

**As many mixes as you ask for (0.60.6).** For now looked for at most four groups, whatever its count said, and kinds of
music that sound alike were joined to fewer mixes than asked. Now For now and Made for you make as many as their counts
say, where you've played songs enough (about 40 a mix): kinds that sound alike stay apart, and the biggest is halved if
need be.

**The app's plans, by the AI here (0.57).** The Siansa app asks the AI set up on Setup for its own playlists too: the
title, sound search, line and sound words to steer by of its vibes, Today's mix, Flow's words and the mood radios
(`POST /api/v1/plan` with the app's `brief`; `features.plans` in the capabilities says whether it can). The app then
needs no AI service of its own, and switches its own off. Only what the app writes in the brief is sent: the moment,
the time slot or the listener's words, recent plays and the sound words the search knows, never a name.

**Where the vocals are, for DJ blends (0.60).** So a blend never lets two singers be heard at once, Beats pulls
the voice out of each song's first and last 96 seconds (the whole song when it's short) with Hybrid Demucs, and marks
bar by bar where someone sings. The app gets, with each song's profile (`/api/v1/profiles`): `vocals`
(`separated`, or `none` for a song the voice model calls instrumental), where the first vocals start and the last
end (`intro_vocal_ms`, `outro_vocal_ms`), the bars from each lock to them (`intro_vocal_free_bars`,
`outro_vocal_free_bars`), every sung stretch (`vocal_sections_ms`) and what was heard (`vocal_heard_ms`). A frame
counts as sung when the vocal stem is within 18 dB of the song's loud vocals, over -48 dBFS and at least 6 % of the
music's energy there; breaths are filled and blips dropped; a bar is sung when a quarter of it is. It runs when
nothing else is analysed, a few seconds a song on a GPU (much longer on a CPU), and lets the model go after 10
minutes idle. **Setup › Vocals for DJ blends › Only songs with vocals** (ticked by default) separates only the songs
the voice model scores 0.3 or more as sung, and keeps the rest as instrumental without reading them; unticked, every
song is separated (also those kept as instrumental before). Each library has a **Vocals** pill under Libraries to
leave its songs out (a library of podcasts or DJ sets, say; 0.60.1). The Overview has a **Vocals** card like the
others, with the model and how many songs are done, and says in **Now** which song's vocals are being found (0.60.2).
**Only vocals** (under Libraries, and in the Setup box) pauses the rest of the analysis and finds the vocals now; the
rest carries on by itself once every song's vocals are found, or with **Carry on**. **Start over › Vocals again**
finds every song's vocals again, the vocals known staying in use until each song is done. A song whose beats have no steady
bars to mark the vocals on is kept as failed ("No steady bars to mark the vocals on"), so it doesn't hold up the rest
(0.60.3: such songs, newest first, were asked for again every round ahead of all the others). Songs that can't be
done yet (their beats or voice not known) are stepped past, and looked at again once the list has been gone through.
The Overview's **Now** has one bar for whatever is being worked on: the kind of analysis and how far it is, the song
and its step (for vocals: getting the file, separating the voice, marking the bars), or why the vocals wait.

**Voice and mood on the page (0.52).** The Overview has a card for it (songs scored of the songs with a sound), and
the menu a page: how many songs are sung by a woman, by a man or instrumental, as one bar; each mood, danceable,
acoustic and electronic with its songs against the whole library; and MIREX's five groups by plain names, each song
in the group it fits best. A line opens its songs, the most sure first, 50 at a time; "Least sure" and "Not sure"
(shares from 40 to 60 %, on both sides of the line) show the ones most likely wrong, to check by ear. A song's page
links to the lists it is in.

**Memory (0.34).** The models are loaded by the first song and let go again after 10 minutes without a song to
analyse (the Activity list says so, with the memory held before and after); the next song loads them again in a few
seconds. What a song needed is handed back to the system when it's done. The log says how much memory is held at the
start and each time the models go, and `/api/status` has it as `memory_mb`. On a GPU, the GPU's own libraries stay
with the service once a model has used it (CUDA keeps them until the service restarts), so it rests higher there
than on the CPU.

## On TrueNAS with a GPU

Beat This! runs much faster on an NVIDIA GPU. The **cuda** image (`ghcr.io/echovaultstudio/siansa-beats:cuda`) has
the GPU build of PyTorch; with `BEATS_DEVICE=auto` (the default) it uses the GPU when the container is given one,
and the CPU when it isn't. The page's first pill says which, with the GPU's name.

1. **The NVIDIA driver on TrueNAS** (once): Apps › Configuration › Settings › tick **Install NVIDIA Drivers**,
   Save. `nvidia-smi` in System › Shell should then list the card. (Driver 525 or newer; TrueNAS's is.)
2. **Know your libraries**, as in step 1 above.
3. **Install it:** Apps › Discover Apps › ⋮ › **Install via YAML**. Name it `siansa-beats`, paste
   [`truenas.yml`](truenas.yml) (or [raw](https://raw.githubusercontent.com/echovaultstudio/siansa-beats/main/beats/truenas.yml)), fill in the values marked `<…>` (Navidrome's address, user and password),
   and Save.
4. Open **http://\<TrueNAS\>:8090**. After the first song, the pill says **Model final0 · GPU** and the card's name.
   If it says CPU and a warning appears at the top, the container didn't get the GPU: check step 1, and that
   `deploy: … driver: nvidia` is in the YAML.

**Its icon on TrueNAS (optional).** An app installed from YAML shows TrueNAS's own icon, and the YAML has no place
for one: TrueNAS keeps it in a file of its own. To give Siansa Beats its icon:

1. System › Shell, then `sudo -i`.
2. `vim /mnt/.ix-apps/app_configs/siansa-beats/metadata.yaml` (the folder is the name you gave the app).
3. Press `i`, and under `host_mounts: []`, in line with it (two spaces in), add:
   `icon: https://siansa.app/beats-icon.svg`
4. Press `Esc`, type `:wq`, Enter.
5. In Apps, open Siansa Beats' **Edit**, and **Save** without changing anything: the icon shows from then on.

TrueNAS writes that file again when the app is edited or updated; if the icon goes, add the line again.

On another Docker server with an NVIDIA GPU and NVIDIA's container toolkit:
`docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`.

- `BEATS_DEVICE`: `auto` (the default), `cpu`, `cuda`, or `cuda:1` for the second GPU.
- `BEATS_FLOAT16=1`: half precision on the GPU. Faster and lighter on memory, but its readings can differ slightly
  from the full precision the model was tested in; compare a few songs before keeping it on.
- The song is decoded on the CPU either way (ffmpeg); only the model runs on the GPU. The GPU's memory is handed
  back after each song.
- GitHub's runners have no GPU, so the cuda image is tested there on the CPU. Its first run on a GPU is on your
  TrueNAS: the Activity list says where the model loaded and how long each song took.

## Use it

The page shows one page at a time, picked from the menu on the left (on a phone, behind the ☰ button; on a wide
screen the ☰ folds the menu away and back, and the choice is remembered), in five groups.
The button at the top right says whether everything works (a green dot, "All working"); tap it for your music
servers, the models and how the app connects. A grey dot there is something not in use (a model not loaded yet):
nothing to look at, and it doesn't count against "All working". With a password set, **Sign out** is there too.
Each page has its own address (`#songs`, `#loudness`…), so Back and bookmarks work:

| Group | Page | What's on it |
|---|---|---|
| Analysis | **Overview** | What's being done now, and a card for each thing analysed (beats, loudness and key, genres, sound, voice and mood, vocals): how far it is and what measures it; **Check what's new** reads the libraries for songs added since (nothing already analysed is touched) |
| | **Libraries** | A row for each library: a switch to analyse it and what it gets (beats, loudness, sound, genres, vocals); Start analysis (with its checks), Only vocals, a progress bar for each thing measured, tidying up, and **Start over**: one kind of analysis again for every song, or all of it, each asked about first |
| | **Songs** | Every song (cards on a phone), and a song's page (its beats, loudness, fades, key and genres) when one is open |
| Your listening | **Listening** | This month beside the last, how you listen over all your history (My profile), and any month or year (Time machine), with charts |
| Used by the Siansa app | **Loudness** | How loud the songs are and how they start and end: for levelling the volume and timing fades |
| | **Keys** | Each song's musical key: for blends in key |
| | **Genres** | The genres heard from each song's sound, how often they agree with the tags, the genre descriptions, and every genre by songs |
| | **Similar music** | How many songs have been heard, and a song to try: the albums and artists like it |
| Service | **Activity** | What was done, newest first |
| | **Setup** | The music servers, access (the page's password, the app's key), the models, and how to connect the app |
| Troubleshooting | **Log** | The service's log, with Debug details |
| | **Bad blends** | The song changes marked as bad in Siansa Dev: a testing tool |
| | **Debug report** | The one file to send when asking for help |

### Several music servers, and several users of one

Siansa Beats reads **Navidrome, Emby and Jellyfin**, as many as you have (0.23.0). Add each under
**Setup › Music servers**: its kind, a name, its address, a user name and password. **Edit** changes one (its name, or
with its password its address, user or sign-in). It's only kept once it answers and takes the login (**Test** asks
without adding, and says why when it can't). Then tick its libraries under **Libraries**: they're read in the
background, and the page shows which library is being read and how far.

- The address can be pasted as the browser shows it (`http://nas:8096/web/index.html#!/home`): it's cut back to the
  server's own, and an Emby that answers under `/emby` only is found there.
- An Emby or Jellyfin user without a password: leave the password empty.
- When a test fails, the page and the log say why: nothing at that port, not that kind of server (Jellyfin chosen
  for an Emby), an untrusted certificate, or the user name or password refused.

- **A song two servers have is analysed once.** When a server's library is read, each song is looked for among the
  songs already here: by its file (the same path, or paths that end alike, as each server has the music folder under
  its own path: `/music/Artist/Album/01 Song.flac` and `/mnt/media/music/Artist/Album/01 Song.flac`), then by its tags
  (title, artists and album), then by title and album when the lengths agree. Lengths more than 3 seconds apart never
  match. A song that can't be placed for sure is analysed as a new one: never guessed. Activity says how many were
  found and by what ("4,012 already analysed from another server (4,012 by their file)"). So pointing Emby or Jellyfin
  at the folder Navidrome has costs a read of the library, not days of analysis.
- **Navidrome's real paths** come from its own API (the one its web page uses), with the same user and password: the
  path in the Subsonic API is made up from the tags unless the player is set to report real paths. A read asks for the
  paths of the songs that have none kept, and for every song's once a week (0.46; asking for all of them at every
  read took most of a read on a big library).
- **Another user of the same server** is added the same way (same kind and address, another user name): it sees the
  libraries that user may, and its songs are the first user's by their ids.
- **The menu's Music server switch** (shown once there are two) picks whose songs the pages show: the overview's
  numbers, the libraries, the table, the genres and the loudness are that server's alone.
- **The default server** is read first and is the one the Siansa app is answered for when it doesn't name one (an app
  from before 0.23). **Make default** changes it.
- **Removing a server** forgets the songs only it had; songs another server has too stay, analysed.
- No password is kept as it's typed (see "Secrets" below), and none is ever shown, logged or put in the debug
  report. Emby's and Jellyfin's token is sent in a header, never in an address. Nothing is ever written to a server.
- What songs sound like (below) is answered for each server in its own ids.
- **Similar albums and artists are found among that server's own music** (0.44.1): a Kids login beside the main one
  gets the Kids library's albums, not the main one's. The Siansa app names the login the songs belong to.
- **Listening** says, beside a listener's name, which music server's login it is (or where its listens came from),
  so two listeners of one name can be told apart.

### What songs sound like

Siansa asks for songs like a song, a path from one song to another, a blend of songs, mood radios, "your sound",
similar albums and artists, and each song's tempo, key, moods and energy. Siansa Beats answers all of them itself.

**It hears every song itself.** Each song's sound is worked out here while it's analysed (two vectors, its moods and
tags, six feelings, its energy); songs analysed before that could be done are caught up on one at a time while
nothing else is running. Nothing is asked of any other service, and nothing needs setting up. A song's tempo is
always the one Beat This! finds here, and its key this service's own measure.

**Music found by describing it.** "Chill relaxed mellow grooves", Siansa's mood radios, its vibes and their sliders,
cards made from a sound: the image holds a text model (500 MB; loaded at the first search, about 600 MB of memory
while in use, let go after 10 minutes without one) and a catalogue of 109 concepts (genre, instrument, vocals, mood,
production, tempo, era) a search can be steered by.

**Your listening history (0.29).** The **Listening** page is a time machine: all time, a year or one of its
months, with the listens, hours, artists, songs and albums of that time, the most played of each, the days or
months as bars (press one to go there), when in the day and the week you listen, records, the artists heard for
the first time, what's playing now and the last listens. Days and hours are your browser's clock's.

**Three ways to look (0.59).** Listening opens on **This month**: its plays, hours, artists, albums, songs and new
artists in coloured boxes beside last month's (the plays against last month's by the same day), the days as bars
with last month's as a dashed line, the top artists, albums and songs (a small picture for each number one, then
the next ones with a bar of their plays), a listening clock, the weekdays, genres, music by decade, who was new and
records. **My profile** is all of your history: your top artists over time (their plays added up month by month, or
their share), your top 40 artists as bubbles, a listening fingerprint (consistency, discovery, variety,
concentration and replay, the last twelve months over the twelve before), when you listen by weekday and hour,
genres over time, new artists month by month and music by decade. **Time machine** is any year or month: the same
boxes and top lists, with a graph to choose (when, the clock, the week, genres or decades). Every chart says what's
under the pointer. The genres are the analysis's (else the file's genre tag); the decades the files' years.

- **Pictures (0.30):** the favourites of a time (top artist, album and song), the number one of each list, the
  lists' rows, what's playing and the last listens show the cover or the artist's picture. An animated cover
  shows as a still, its first frame (0.34.1). They're the music
  server's own, asked through a song of that album or artist in the library and kept in the data folder (`art/`);
  nothing is looked up on the internet. Music that isn't on the server shows a tile in its own colour with the
  name's first letters. Navidrome's stand-in picture (its blue disc, its star) is never shown as a picture.
- **An artist's own page (0.31):** press an artist anywhere on Listening (a row, the favourite, what's playing, the
  last listens, the new artists) for everything about them: plays, hours, their share and rank, songs, albums, days,
  their busiest year, year by year, around the clock, first and last listen, their most played songs, their albums
  and the last listens of them. Its address (`#artist=<name>`) can be kept or shared.
- **Every artist of a song (0.47):** a listen of a song by several artists ("Fred V & Grafix feat. Amy J Pryce")
  counts for each of them, as the music server lists the song's artists (your tags), not for the line they're
  written in; its album is its first artist's. The artists come with the next library read (**Check what's new**
  on Overview does one), and listens kept before are split then too; a listen of music that isn't on the server
  is split when a song here is credited the same way, else left as written. Last.fm is told the first artist.
- **Kept in memory (0.47):** a listener's listens are read once and the numbers worked out from there, with all
  time's ready after a start, so a period opens at once also with a long history. It's about 35 MB for 69,000
  listens, and let go when Listening wasn't opened for 30 minutes; **Settings › Memory** changes that (not at all,
  30 minutes, 4 hours, always). The database stays the only copy that counts.
- **Settings (0.47):** a part of the page for who the listeners are, files and Last.fm. **Listeners** lists every
  name with a history; two that are one person's are joined there (**Join into…**, a listen both have is kept
  once, and it can't be undone).
- **From the app:** turn on **Scrobble to Siansa Beats** in Siansa (Settings › Scrobbling). Each listen is kept
  under the name the app scrobbles as (your music server's user name), so two people have a history each; the page
  has a listener switch when there's more than one. A name is the same whatever its capitals (0.46.1: "Max" typed on
  the TV is the phone's "max"), so one person's listens stay together and go on to their Last.fm; listens kept
  apart before are joined at the start.
- **From a file:** an export of Koito (its own JSON), of Last.fm (the JSON or CSV of an export tool, e.g.
  lastfm.ghan.nl/export) or of ListenBrainz. Choose the file and whose listens they are. A listen that's here
  already (the same listener, second, artist and title) is kept once, so a file can be brought in again and two
  services' exports of the same years don't count double. A listen is linked to the song here by artist and title.
  Last.fm's exports don't say how long a song is: the hours then use the song's length from the library or another
  listen, else 3½ minutes, and the page says for how many.
- **On to Last.fm:** per listener, with their own Last.fm API account (key and shared secret) and one sign-in. New
  listens from the app are sent on in the background, and again later when Last.fm can't be reached; listens from a
  file never are, nor ones older than two weeks (Last.fm turns those away). The key, secret and session are kept
  encrypted, the password not at all. Turn the app's own Last.fm scrobbling off then, so nothing is sent twice.
  The app's hearts go on too, as loved tracks (0.29.2).
- **A history brought in without a name** (the "whose listens" box left empty) is offered to the app's listener once
  the app sends something: **Make them max's** joins them (a listen both have is kept once), and sending on to
  Last.fm, if it was connected on the unnamed one, moves along, with the app's listens since then.
- **On a phone** the page shows one part at a time (Overview, Top, When, History, Settings; the bar stays in view), long
  lists show their first lines with **Show all**, the Setup cards open by their heading, and **↑ Top** goes back up.

**Songs gone from the server are forgotten (0.27).** When a library is read again (every few hours, or **Read
again**), a song that's no longer on the server goes from here with its analysis, unless another server still has
it. A library that suddenly lists far fewer songs (more than 25 songs and 10% missing at once) is left alone, with a
warning: that's more often a server still scanning or a disk not mounted than a clear-out.

Similar songs are the nearest by cosine distance between their vectors, at most three by one artist and never the
same recording twice. Whose work the models and methods are is said under [Credits](#credits).

1. On **Libraries**, tick the libraries to analyse and press **Start analysis**. It checks everything first (below),
   then reads their songs from Navidrome, queues the new ones and works through them a song at a time; the top shows the song
   and the step (downloading, decoding, loading the model, analysing), and **Activity** what's been done, with the
   time each step took. The first song takes longer while the model loads.
2. **The table**, a row a song:
   - **Tag**: the file's BPM tag.
   - **Beat This!**: the song's tempo, with intro / outro below (the tempo each end holds for most of its 30
     seconds, or **–** when it has no steady beat, as a beatless intro). It's the tempo the song spends most of its time at,
     so a breakdown, a half-time intro or a tempo change doesn't drag it off (the song's page also shows one
     straight line through every beat, as 0.2 gave it). **Bar**: beats a bar, and the share of
     bars that agree. **Steady**: how evenly the beats fall, and the share on a straight grid (a drum machine is
     near 100 %).
   - **Notes**: what the readings say together: whether they agree, or how they relate (**4/3**, **double**,
     **half**…; a misreading is nearly always one of those). An intro or outro at another tempo than the rest of
     the song is noted, not flagged. Genres are only shown: their tags are partly guessed, so they never change a
     reading or a note.
   - **Worth a listen** shows only the songs where readings really disagree (a warning). **Done** shows the songs analysed, **Failed** those that failed.
3. **Tap a song** to open it:
   - play it: **Clicks on the beats** ticks on every beat, higher on each downbeat. If the clicks sit on the kick
     drum, the beats are right; if they drift or fall between, they're not;
   - the clicks come **from the steady grid** when the song is at one tempo: one even grid at the song's tempo,
     lined up with the model's beats, that carries on through breakdowns and quiet intros (as DJ software does).
     Its bars come from a vote of the model's downbeats and then follow every 4 beats, so the phrase can't wander.
     A track off a mixed CD, where the DJ rode the pitch (its tempo creeps, 123.4 to 124.0 BPM, say), gets a grid
     that **follows the drift** instead: its local tempo read every 16 beats and joined smoothly, up to 4 % apart
     (more is a real tempo change, and gets no grid). Its row says "The grid follows a drifting tempo (0.8 %)", each
     end then carries the tempo it plays at there, and the CSV has `grid_drift`. A song whose even grid holds takes
     the following one only when clearly more of its beats sit on it;
     Pick **the model's beats** to hear what Beat This! heard; the other set shows as small ticks along the bottom
     of the beat view;
   - **bars and phrases come from the sound too.** While a song is analysed, Siansa Beats measures how loud its sub
     bass, bass, mids and highs are along it (kept small in the database, so it's worked out again without
     downloading the song). In dance music a new section (the bass coming in, the drop, the hats stopping) starts
     on beat 1 of a bar and at the start of a phrase. So the big changes check the model's downbeats: when three or
     more agree on another beat, the bars move there (**Bars moved** in the notes, worth a listen). And the bar of
     every 8 they land on is where the **phrases** start: a green mark in the beat view, ticks along the top of the
     chart, and a third, higher click. When fewer than half the big changes fall on one bar of 8, the song says
     **No clear phrases** rather than guessing;
   - a song is counted at the tempo the model heard: drum & bass heard at 87 stays at 87. The Siansa app counts half
     and double as the same tempo and doubles anything under 100 itself, so it still blends at 174;
   - the beat view shows 8 seconds around what's playing, downbeats in amber with their bar number. Tap it to jump;
   - the chart shows the tempo along the song (amber), the BPM tag (green), and the ends (the first and last 30 s,
     shaded). Tap it to jump there;
   - **Analyse again** reads it once more; **Remove** forgets it (nothing changes on Navidrome).
4. **Export CSV** gives the table, for a spreadsheet.

**The log.** Everything Siansa Beats does goes to the container's log (`docker compose logs -f siansa-beats`, or the
app's Logs on TrueNAS) and to the **Log** page: starting up, the libraries read, each song
done or failed, errors with their traceback. Tick **Debug details** to add every step of every song with its times and
sizes, what the model and the grid found, and every request to Navidrome with how long it took; it's kept across
restarts, so turn it off when the problem is found (a pill at the top says while it's on). `LOG_LEVEL=debug` turns it
on from the start. Passwords and tokens are never written: Navidrome's login token is taken out of every line.

**When something's wrong or stuck,** **Download debug report** saves one file with the versions (torch, CUDA, the
GPU), the setup (addresses, never passwords), the status, where each part of the service is right now (a stuck one
shows the line it waits on), the latest activity and the log. **Download log** saves the log alone. Send either.

**Back** (the browser's or the phone's) closes a song, and the **Siansa Beats** logo goes back to all the songs.
A song's address (`#song=…`) opens it straight away.

**Section marks.** While a song plays, tap **Section starts here** (or press **M**) on every drop, breakdown or big
change you hear. Each mark shows the bar it's nearest the start of, and whether it falls on a phrase start; tap it to
hear it again, ✕ to take it away. Marks are kept through analysing again, show as ◆ in the table, and go out with
**Download data**: they're what the phrase rules are checked against. About 20 songs with their drops marked is
enough.

**Download data** gives every song's beats and sound levels as one file (a few MB; song names and genres, no
addresses or passwords): what the grid and phrases are worked out from, to tune them on real music.

**Trying the dev version.** New work goes to the `dev` branch first and is published as `:dev` (CPU) and
`:dev-cuda` (GPU): put that tag in the YAML instead of `latest` / `cuda` and restart. It keeps the same data; going
back to `:cuda` keeps it too.

**Start analysis checks everything first (0.40).** Before a song is read, six checks run and are shown as a list under
the button, each ✓, ! (analysis goes ahead; something to look at) or ✕ (nothing starts; it says why):

- **Music server**: it answers, and nothing is ever written to it. A plain-`http://` address outside the home (a
  public IP or domain) gets a !: the login crosses the internet unencrypted.
- **Libraries**: every ticked one still exists on the server; how many of their songs are known so far.
- **Database**: SQLite's `quick_check`, and rows left behind by removed songs are tidied away. A damaged database gets a
  ✕ (stop the container and restore `beats.db` from a backup).
- **Disk**: free space where the data lives (✕ under 500 MB, ! under 2 GB), and temporary song files from a run that
  was cut off are removed.
- **Models**: every file in the models folder is fingerprinted (SHA-256) the first time a version is checked and
  compared each time after: a changed or missing model file gets a ✕ (pull the image again), since a model that
  isn't the image's gives wrong answers for every song. Models not in the image get a !.
- **Safety**: the page has a password (! when not: anyone who reaches the port can change everything), the app has its
  key, and no secret is left in the container that it no longer reads.

A song's file is never downloaded past 2 GB (enough for a two-hour FLAC mix): a stream that doesn't end, or a server
sending something else, can't fill the disk. The last report is kept and shown again when the page opens.

**What each library gets (0.40).** Under the ticked libraries, a row of chips a library: **Beats** (tempo, beats and
phrases, what the DJ blends need), **Loudness & key** (LUFS, fades, the key), **Sound** (moods, energy, similar music
and the search by words) and **Genres** (the 400 styles by sound). Tap one to leave the library out of it, crossed
out, and press Start analysis: a library of two-hour mixes can keep its loudness and skip the beats, which take Beat
This! a long time on such songs. Songs left out of the beats show as *no beats (left out)* and count as settled;
their loudness is still measured on its own. A song two servers have is left out of a task only when every library
it's in leaves it out. Putting a task back queues the songs for it. The Overview's cards count each thing over the
songs a library wants it for (0.47.1): a library with only Loudness on is in **Loudness & key**'s "of" and not in
**Beats**', **Sound**'s or **Genres**', and the numbers follow a change at once.

**Tidy the database (0.40).** Under Libraries, **Look for what's gone** asks the server for every ticked library right
now and shows, by name, songs the server no longer has, songs of libraries left out, songs linked to no server and songs
that couldn't be analysed (which are found and tried again on the next read). Looking removes nothing. Tick the groups
and press **Remove**: a copy of the database from before is kept beside it first (`beats-before-clean.db`, replacing
the previous copy; skipped when the disk hasn't room, and said), then exactly the songs shown go, and SQLite looks the
database over afterwards. Each look comes with a token good for 15 minutes that the removal must send back, so a
stale page, or a request that never saw the look, removes nothing. A library the server lists at under half the songs
it had gets a warning (the server may still be scanning) and isn't ticked by default. Reading the libraries removes a
few gone songs by itself (up to 25, or a tenth); more than that is left to this, where you see what goes.

**Progress (0.40.1).** Under Libraries, a bar for each kind of work going on: the beats (with the song and its step),
genres by sound (and, after a change of model, how many songs are heard again with the new one, with a rough time
left), loudness and key, the sound, and the libraries being read. Changing the style model answers at once; marking
the songs to be heard again is shown here and under Setup while it runs.

**Libraries.** Each ticked library shows how many of its songs are done. Ticks take effect with **Start analysis**.
Untick one and start to leave it out: its songs not yet analysed leave the queue, the ones done stay, and **Remove
them** next to it forgets them (their beats and marks; nothing changes on Navidrome). The choice is kept across restarts, and the ticked libraries are
read again every 6 hours for new songs (**Start analysis** does it now, with its checks). The next song is downloaded and decoded
while the model works on this one, so the model rarely waits for the network; the top says how long each song takes,
to judge how long a library will. The table shows the first 200 songs, the search finding the rest, and **Export
CSV** and **Download data** take the songs it finds (every song when nothing is searched: for a big library the data
is large).

**Genres from the sound.** Each song's genres come from its sound alone, for Siansa's genre list (Search › Genres),
genre pages and genre radios:

- One of two models from Essentia (the Music Technology Group, UPF) hears the song and scores each of 400 Discogs
  styles, from Progressive Trance and Deep House to Punk and Boom Bap. **Discogs-EffNet** (2021) is small and quick,
  about a second a song on a CPU, and the one in use unless another is chosen. **MAEST** (2023; 0.39) is a larger
  transformer hearing 30 seconds at a time, markedly more accurate on the same styles and surer of what it hears,
  the better choice beyond electronic music; slow on a CPU (about 4 seconds per 30 seconds heard, a few windows a
  song), quick on a GPU. The page's Setup › Genre model picks one, each with what it's good at and what to watch out
  for; a new install asks for it in Get started before its first analysis (0.58). Changing it keeps the choice, and
  every song is heard again with the new model: each song's old styles stay in use until it's heard again, then
  they're replaced (the two are never kept side by side), and going back means hearing every song again. Meanwhile
  genres are partly old and partly new; beats, blends, loudness, keys, moods, similar music and the search by words
  don't use the genre model. The page says all this before a change, and warns when one is made halfway through the
  first listen or another switch. Both give the
  same 400 styles, so the genre pages read the same. The model runs on the GPU when there is one (through the
  PyTorch Beat This! uses), else on the CPU (ONNX Runtime, `STYLE_THREADS`, 2 by default); `BEATS_DEVICE=cpu`
  keeps both on the CPU. On a GPU with tensor cores (an RTX, any card of compute capability 7 or more) it hears in
  half precision (0.41, the owner, 13 Nov: an RTX 3050 took 1.7 s a song in full precision), two songs in one pass
  where the card's memory allows (a pass that runs out of memory is the last one of two: one a pass from then on,
  said once in Activity; 0.42.2, the 3050's 6 GB), while the next songs download and decode in the background;
  older cards and the CPU hear in full precision, one at a time (`STYLE_PRECISION`). Half precision that strays from the CPU's scores on the first song goes back to
  full precision by itself. EffNet is at home among electronic
  releases and can misread a clean, sparse production (a country ballad as Dance-pop, the owner, 13 Nov); `GET
  /api/v1/songs/families?ids=` (0.38) shows, for up to ten songs, how CLAP hears their genre family from the vector
  kept for the search by words, and what their styles would be weighed by that — a look, nothing kept, until it has
  proved itself. On the first real song the GPU's scores
  are checked against ONNX Runtime's (0.37.1): a GPU that disagrees by more than 0.05 is let go for the CPU, the
  page says so, and every song is heard again (its old styles stay in use until then). `GET
  /api/v1/songs/styles/again?ids=` hears up to ten songs again both ways, to see the two side by side. New songs are
  heard on their way through the queue; songs analysed before are downloaded once more and heard while the queue is
  empty;
- **a song is in a genre when its sound scores that style 0.15 or more and the style is among its three best, and
  always in the one it scores highest** (0.36: before, a country album's faint fourth and fifth guesses put it in
  Electro House). A genre gives all its songs, the ones that sound most like it first, with each one's score, so the
  app's radio prefers the songs the sound is sure of. A radio for a whole family ("Electronic") takes only the songs
  whose best style is in it;
- the songs' own genre tags play no part (before 0.28 they were voted together with the sound; those votes are
  removed on the first start). Siansa still shows the tags where they belong: on an album's and an artist's page.

The **Genres** card says how far it is, where the model runs, how often the sound agrees with the tags (the tagged
genre, and the tagged style in the sound's top 3: for your information only), and the styles with the most songs. A
song's page shows its genres, everything its sound said and its tags; the table's genre column and the CSV
(`sound_genres`, `sound_top`) its genres. The model is under CC BY-NC-ND 4.0 (free for non-commercial use,
unchanged), downloaded while the image is built; how often it's right on your music is what you hear.

## Test it

Every change is tested by GitHub Actions (`.github/workflows/beats.yml` in this repository):

- **Without the model**: the tempo, bar and comparison maths (`tests/test_grid.py`), and the whole service against
  a fake Navidrome (`tests/test_service.py`): the token login, libraries, the queue, failures, the
  page's API, the audio passing through with seeking, the CSV, the log and debug report (with no secrets in them),
  pause and the password. `tests/test_page_script.py` checks the page's script parses.
- **Several servers** (`tests/test_match.py`, `tests/test_servers.py`): finding the same song on two servers by its
  file or tags and never by a guess; fake Emby and Jellyfin servers, each taking only its own way of logging in; a
  song another server has not analysed again; a song only the other has, analysed from it; a second user of one
  server; each server's own ids and numbers with `?server=`; and no password in any answer.
- **Real servers** (`tests/real_servers.py`): real Navidrome, Emby and Jellyfin with the same music (the Siansa app's
  test servers, their newest releases and the oldest it supports): each one's login, libraries, songs, file paths and
  downloads, and the songs analysed from Navidrome found again on the other two by their files, none analysed twice.
- **CPU or GPU** (`tests/test_analyser.py`): which device each `BEATS_DEVICE` gives, and the fallback to the CPU,
  with a note, when a GPU is asked for but missing.
- **With the model**: both images (CPU and cuda) are built, `tests/make_test_songs.py` makes five songs of known tempo and bars (140,
  174, 122, 128 BPM in 4/4, and 96 BPM in 3/4), one a BPM tag at half,
  and `tests/e2e.py` runs the real Beat This! on them through the service. The steady 4/4 dance songs must read
  within 1.5 % with 4 beats a bar; the others are reported. The run's log has the table, and the log and debug report are checked too.

On your own computer, without Docker or the model:

```
cd beats
python3 tests/test_grid.py && python3 tests/test_service.py
python3 tests/make_test_songs.py /tmp/songs        # needs ffmpeg
python3 tests/preview.py /tmp/songs                 # the page with a stand-in for the model: http://127.0.0.1:8090
```

On the server, after setting it up:

1. `docker compose ps` says **healthy**, and http://\<server\>:8090/api/health answers `"status": "ok"`.
2. The page's Navidrome pill is green.
3. **Tick a library** and **Start analysis**: the songs appear, the first one loads the model (the pill then says how long it took),
   and the rest follow. A song that fails says why in its row and in Activity, and the queue goes on.
4. Open Control (or another song you know): play it with clicks on, and check the clicks sit on the beat.

## What it can't do yet

- **Bars in 3/4.** In the first test run, Beat This! read every test song's tempo exactly (140, 174, 122, 128 and
  96 BPM, the 174 not halved), but counted the 96 BPM waltz as 4 beats a bar. Steady 4/4 music, what DJ blends
  need, read right. Watch the **Bar** column on your own 3/4 songs.

- Genres come from the files' tags only (the **tag** source), and are only shown. The database keeps each genre's
  source, so others can be added beside them.
- `GET /api/grids?ids=a,b` gives each song's grid at both ends as the Siansa app reads it. `GET /api/beats/<song id>` gives every beat of one song.
- Each end is taken **inside the lock**: from the first 4 bars where the model's beats sit on the grid to the last
  (`intro_lock_ms`, `outro_lock_ms`). A track cut from a mixed CD carries the DJ's own transitions at its ends, the
  next or last record still playing; its blends belong inside the lock. Each end also says how many bars the bass
  stays out (`intro_bass_bars`, `outro_bass_bars`), how loud it is next to the song (`intro_energy`,
  `outro_energy`, dB), and the song where the bass drops out and comes back (`breakdowns_ms`, `drops_ms`), for the
  app to choose how to blend.
- **Breakdowns and drops** (0.49.0): a song's page lists where Beats found the bass dropping out (a breakdown) and
  coming back (a drop), as the app gets them, each with how much the bass falls or rises (10 dB or more is clear,
  under that faint; it takes 6 dB to count), tap one to hear it. They show on the beat strip and the tempo chart
  too. With your own **Section starts here** marks, a line says how many of Beats' ones your marks agree with
  (within a bar), to see where the rule works and where it doesn't before the app mixes on them.
- **Downloads** (0.50.2): **Download data** is sent as it's made, a song at a time, so the download starts at once
  and runs to the end however big it is (every song's beats came to a file a proxy in front gave up waiting for). Your
  browser downloads it as usual.
- **The breakdown and drop trial is over** (0.51.1): the marks tapped in Siansa Dev and the Marked filter are gone,
  and so are those marks from the database. Marks set on a song's page (Section starts here) stay.
- **Bad blends**: a song change marked as bad in Siansa Dev lands in a list on the page, with how the app blended it
  (technique, bars, tempos, confidence at each end, why it was planned that way), and both songs a tap away. When the
  app heard each song's kicks during the blend, it shows how far they fell from the song's beat grid (more than 20 ms
  is off). **Analyse both again** (0.48.0) works the beats out again for the two songs: it helps when the first
  analysis went wrong; a song that's hard to read usually comes out the same, and the blend is better marked and
  left. **Clear all** takes them all away for a
  fresh start (download them first if you still want them). **Download bad blends** saves them all
  with both songs' beats, sound levels and results in one file (`GET /api/bad-blends/export`).
- **Failed songs**: when songs couldn't be analysed, **Download failed songs (N)** beside the exports saves them with
  why (the error), their file type, length and library in one file (`GET /api/failed/export`); the CSV export has the
  error too. Filter **Failed** shows them in the table.
- Phrases are 8 or 16 bars: 16 when three quarters of the big changes (at least 4) fall on every other start of
  8. A song whose sections don't change its sound much (a long, even techno track) may have no clear phrases.
- Songs analysed before 0.5.0 are analysed again once, on start, to measure their sound (a few seconds each).
- 0.15.0 works every song out again once from its saved beats, on start, for the following grid (no download or
  model: about 40 ms a song, so half an hour for 45,000; the top shows how far it is), and analyses again the songs
  that failed on the two bugs it fixes.

## Settings

| Variable | Default | |
|---|---|---|
| `STYLE_THREADS` | `2` | The style model's CPU threads. |
| `STYLE_PRECISION` | `auto` | The style model on a GPU: `auto` hears in half precision on a card with tensor cores (an RTX, or any card of compute capability 7 or more; about twice as quick) and in full precision on older cards; `fp16` or `fp32` insist. The first real song is checked against the CPU either way, and half precision that strays goes back to full precision by itself, then to the CPU. |
| `LOG_LEVEL` | `info` | `debug`: every step of every song in the log, from the start. The page's **Debug details** switch changes it while running and wins over this. |
| `BEATS_MODEL` | `final0` | `small0` is smaller and faster, a little less exact. Both are in the image. |
| `BEATS_DEVICE` | `auto` | `auto` (the GPU when the container has one), `cpu`, `cuda`, `cuda:N`. Needs the `cuda` image for a GPU. |
| `BEATS_FLOAT16` | `0` | `1`: half precision on a GPU. |
| `BEATS_THREADS` | `0` (all) | The model's CPU threads. |
| `BEATS_CPUS` | `4` | (docker-compose) The cores the container may use. |
| `BEATS_SECRET_KEY` | empty | The key the kept secrets are encrypted with, to keep it out of the data folder. Without it, a key file (`secret.key`) is made there. Changing it means entering the servers' passwords again. |
| `BEATS_RESET_ACCESS` | empty | `yes`: takes the page's password and the app's key away at the start, when the password is forgotten. Take it off again afterwards. Simpler, and without a restart: `docker exec siansa-beats python -m beats.reset` (below). |

The music servers, the page's password and the app's key are **not** settings of the container: they're
set on the page, under Setup.

### Secrets

No secret is kept as plain text, and none belongs in the YAML (0.24.0).

| Secret | How it's kept |
|---|---|
| The page's password | **Hashed** (scrypt, salted). It can't be read back, only checked. |
| The app's key | **Hashed** (SHA-256 of a random key). It's shown once, when you make it under Setup › Access. |
| Emby's and Jellyfin's password | **Not kept.** It's used once to sign in; the sign-in token the server gives is kept, encrypted. If the server stops taking it (you signed its devices out), Edit the server and enter the password again. |
| Navidrome's password | **Encrypted.** It can't be hashed: Siansa Beats has to say it to Navidrome each time, and a hash can't be said in its place. |
| A browser's sign-in | **Hashed** (SHA-256 of a random session token, 0.43). The token itself is only in the browser's cookie, which scripts can't read and other sites aren't sent; it lasts 30 days, and ends at Sign out, a changed password or a reset. |

What's encrypted is locked with a key that isn't in the database: `BEATS_SECRET_KEY` from the container when you set
one, else the file `secret.key` in the data folder, readable by Siansa Beats alone. A copy or backup of `beats.db`
without the key gives nothing away. Someone who has the whole data folder, key file included, can decrypt them, so
set `BEATS_SECRET_KEY` (in the container's settings, or a Docker secret) to keep the key apart from the data. If the
key is lost, the servers show "enter its password again".

**Coming from 0.23 or before:** `NAVIDROME_URL`, `NAVIDROME_USER`, `NAVIDROME_PASSWORD`, `BEATS_PASSWORD` and
`BEATS_API_KEY` are taken over once at the first start of 0.24 (hashed or encrypted) and never read again.
`AUDIOMUSE_URL` and `AUDIOMUSE_TOKEN` are read by nothing since 0.43. Setup says which are still in your YAML: delete
those lines. Nothing is analysed
again, and the app keeps its key.

A key for the app needs the page to have a password (without one the page is open and the app needs no key), and
goes when the password is removed.

### A forgotten password

On the server, with the container running:

    docker exec siansa-beats python -m beats.reset

It takes the page's password and the app's key away at once, without a restart, and says what it took. The page is
then open to your network again: set a new password under Setup and give the Siansa app its new key. Nothing else is
changed (not the songs, not the listens, not the servers' logins). On TrueNAS, the app's Shell does the same with
`python -m beats.reset`.

## The app's API (v1)

What the Siansa app asks for, under `/api/v1/`, described in full in [`beats/openapi.json`](beats/openapi.json)
(`GET /api/v1/openapi.json`). Within v1, fields are only ever added, so an older app keeps working.

| | |
|---|---|
| `GET /api/v1/capabilities` | What this Siansa Beats can do now and how far it is: songs analysed, measured for loudness, the style model. |
| `GET /api/v1/profiles?ids=a,b` | Up to 500 songs: loudness (`ref_lufs`), fades (`start_ramp`, `end_ramp`), key and scale, and the beat grid at each end. Songs with nothing yet are `pending`. |
| `GET /api/v1/genres` | Every style with songs in its genre by their sound, most songs first. |
| `GET /api/v1/genre?name=&limit=` | The songs of a genre, by their sound, the ones that sound most like it first: all of them (`songs` says how many), or a random `limit` of them. |
| `POST /api/v1/listens` | Finished listens of a listener: `{"user", "listens": [{"id", "at", "artist", "title", "album", "album_artist", "duration"}]}` (at most 500; `at`: seconds since 1970). Answers `{"kept", "known", "skipped"}`; the same listen twice is kept once. `album_artist` (0.37) goes on to Last.fm, which finds a collaboration's or compilation's album, and its cover, by it. |
| `POST /api/v1/listens/now` | What's playing now: `{"user", "artist", "title", "album", "album_artist", "duration"}`. |
| `GET /api/v1/listens/top?user=&kind=&from=&to=&limit=` | A listener's most listened `songs` (with the server's id, when it has the song), `artists` or `albums` in a stretch of time. |
| `GET /api/v1/listens/totals?user=&from=&to=&tz=` | That stretch in numbers (0.33): `listens`, `seconds`, `artists`, `songs`, `albums`, `new_artists` and `hours` (listens per hour of the day in `tz`). Siansa's Time machine and listening reports read a listener's history from this and `listens/top`. |
| `GET /api/v1/songs/genres?ids=a,b` | The genres each of up to 500 songs is in by its sound, its best first (0.32): `{"songs": {"<id>": [{"name", "genre", "style", "score"}]}}`. Siansa picks a vibe's sound dials from it: what that mix has to offer. |
| `GET /api/v1/genre/about?name=` | A short description of a genre, from Wikipedia. Every genre's (the sound's and the songs' tags) is fetched in the background every 6 hours and kept; one not fetched yet waits up to 3 s and then answers `"pending": true`, to ask again shortly. |
| `GET /api/v1/similar/albums?track_id=` | Albums that sound like that song's album, among the named server's own (`?server=`; `source`: `beats`). An empty list, with a `note`, while that song's sound isn't known here yet. |
| `GET /api/v1/similar/artists?track_id=` or `?artist=` | Artists that sound like that one, the same way. |
| `GET /api/v1/sound/similar?item_id=&n=` | Songs that sound like a song (`mood_similarity=true`: only in its mood; `mood=&centroid_index=`: around a mood centre). |
| `GET /api/v1/sound/path?start_song_id=&end_song_id=&max_steps=` | A path of exactly `max_steps` songs from one song to the other (an end can be `start_mood` / `end_mood`). |
| `POST /api/v1/sound/blend` | `{"items": [{"id", "op": "ADD" or "SUBTRACT", "type": "song"}], "n"}`: songs near the ones to blend, away from the ones to avoid. |
| `GET /api/v1/sound/moods` | The mood centres, each with its tags. |
| `POST /api/v1/sound/yours` | `{"n"}`: songs near what this server's user has played most (or near `ids`, when given). |
| `POST /api/v1/sound/search` | `{"query", "limit", "steering": [{"term", "direction": "more" or "less", "weight"}]}`: the songs that sound like the description (0.26), each with its `similarity`; `steering_warnings` names terms that aren't concepts. |
| `GET /api/v1/sound/concepts` | The concepts a search can be steered by, in their groups. |
| `GET /api/v1/sound/songs?ids=` | Up to 500 songs' tempo (Beat This!'s, `tempo_source`: `beat_this`), key, moods, genres and energy, without the vectors. `energy_source` says where the energy is from (`beats`, `converted`: the same scale; `audiomuse`: kept from before 0.43, as it was). `arousal` (0.35) is how energetic the song is to a listener, the one to order songs by. |
| `POST /api/v1/bad-blends` | A song change marked as bad in the app. |

With several music servers, every one of these takes `?server=`: the id (or name) of the server the app plays from,
from the capabilities' `servers` (each with its `kind`, `url` and `user`, to tell which is the app's). Ids asked about
(`profiles`, `bad-blends`) are understood from any server; ids answered (`genre`) are that server's own, and the counts
(`capabilities`, `genres`) are of its songs. Without `server` the default one is meant.

What songs sound like is asked under `/api/v1/sound/` (0.44). The capabilities' `sound` says what's answered and for
how many songs, and its `paths` where each answer is. Apps from before 0.44 ask the same things under
`/api/v1/audiomuse/` (the names of AudioMuse-AI's API, which the Siansa app spoke before Siansa Beats answered these
itself); those paths are answered the same and stay until no released app asks there.

Songs analysed before 0.20 get their loudness, fades and key while the queue is empty: each is downloaded once more
and measured here. New songs are measured on the way.

## The page's API

`POST /api/analyse-again` with `{"what": "beats" | "loudness" | "sound" | "genres" | "vocals"}` does one kind of
analysis again for every song (0.45; on the page under Libraries › **Start over** since 0.46; vocals since 0.60.2):
beats are queued; loudness, key, genres, the sound and the vocals are worked out again while what's known stays in
use (0.46: the sound was forgotten first before). A paused service starts again.

`POST /api/vocals` with `{"only_sung": bool}` sets Only songs with vocals; with `{"alone": true}` (0.60.2) the rest of
the analysis pauses and the vocals are found now, until every song's are (409 in an image without the model);
`{"alone": false}`, `/api/pause` and `/api/resume` end it. Its answer, like `GET /api/vocals`, has `alone`, and
`working` has `for_seconds`.

`GET /api/health`, `/api/status`, `/api/libraries`, `/api/songs`, `/api/songs/<id>` (with every beat),
`/api/beats/<id>`, `/api/audio/<id>`, `/api/grids?ids=`, `/api/export.csv`, `/api/export.json`;
`/api/bad-blends`, `/api/failed/export`, `/api/listens?user=&year=&month=&tz=`, `/api/art/cover/<song id>?size=` and `/api/art/artist/<song id>?size=` (a song's cover and its artist's picture), `/api/listens/import` (`POST`: the export file as the body, `?user=&name=`), `/api/listens/artist?user=&name=&tz=` (one artist's page), `/api/listens/profile?user=&tz=` (My profile, 0.59), `POST /api/listens/lastfm`, `POST /api/listens/remove`, `/api/genres`, `/api/genre?name=&limit=`, `/api/mixes?user=&tz=&part=&days=` (the Mixes page, 0.53), `/api/voice` (the Voice and mood page's numbers, 0.52), `/api/voice/songs?line=&order=&limit=&offset=` (the songs of one of its lines; order: `most`, `least` or `unsure`), `/api/style/models` (the style models to choose from, 0.39; `POST /api/style/model {"model"}` picks one), `/api/log?after=&limit=&level=`, `/api/log/download`, `/api/debug`, `/api/analysis/checks` (the last Start analysis report, 0.40), `/api/clean/preview` (what could be tidied away, with a token); `POST /api/analysis/start {"ids", "skips": {library: [tasks]}}` (the checks, then the ticked libraries read for new songs; tasks: `beats`, `loudness`, `sound`, `styles`), `/api/clean {"token", "groups"}`, `/api/libraries {"ids"}`, `/api/libraries/read`, `/api/bad-blends`, `/api/songs/<id>/analyse`, `/api/analyse-all`, `/api/log/level {"level"}`, `/api/pause`, `/api/resume`; `DELETE /api/songs/<id>`, `/api/bad-blends/<n>`, `/api/libraries/<id>/songs`. See
`beats/server.py`.

## Building the image

The Beat This! checkpoints are downloaded while the image is built: from this repository's release `models-1`
first, then from the authors' host, and each must have the SHA-256 written in the Dockerfile. The release is made
by the **Model files** workflow (run by hand), which copies them out of the published image.

## Credits

Siansa Beats is built on other people's work, each under its own licence:

- **Beats and bars:** Beat This! by Francesco Foscarin, Jan Schlüter and Gerhard Widmer (ISMIR 2024), MIT licence.
- **Genres:** Discogs-EffNet and MAEST by Pablo Alonso-Jiménez, Xavier Serra and Dmitry Bogdanov (MTG, Universitat
  Pompeu Fabra), from [Essentia's models](https://essentia.upf.edu/models.html), CC BY-NC-ND 4.0 and CC BY-NC-SA 4.0.
- **How energetic a song is:** Essentia's emoMusic model (MTG, UPF), CC BY-NC-SA 4.0.
- **How songs sound, moods, and the search by words:** the models (MusiCNN for the songs' vectors and tags, a
  distilled CLAP for the search by words, the concept models for steering), the mood centres
  (`beats/mood_centroids.json`), the concept catalogue (`beats/sound_concepts.json`) and the method are those of
  [AudioMuse-AI](https://github.com/NeptuneHub/AudioMuse-AI) by NeptuneHub (AGPL-3.0, as this repository). The image
  downloads the models from that project's releases. Siansa Beats runs them itself and needs no AudioMuse-AI
  installed; it's a separate project, not affiliated with it. The answers under `/api/v1/sound/` keep the layout of
  that project's API, which the Siansa app already read.
- **Where the vocals are:** Hybrid Demucs by Alexandre Défossez (Meta, 2021), the weights torchaudio publishes as
  `HDEMUCS_HIGH_MUSDB_PLUS` (trained on MUSDB-HQ and 150 more songs), MIT licence.
- **Genre descriptions:** Wikipedia (CC BY-SA), named and linked wherever one is shown.
