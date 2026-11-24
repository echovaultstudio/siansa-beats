"""The demo's music: every artist, album and song here is made up, and so is who listens to it."""

import hashlib
import random

# (artist, kind, [(album, year)], where they're from): the kinds are the keys of KINDS.
ARTISTS = [
    ("Halden Vale", "liquid", [("Glass Rivers", 2021), ("Low Sun", 2023)]),
    ("Mira Okonjo", "liquid", [("Paper Lanterns", 2022)]),
    ("Brackwater", "neuro", [("Tidal Engine", 2020), ("Salt Circuit", 2024)]),
    ("Sub Atlas", "neuro", [("Night Freight", 2023)]),
    ("Lumen Park", "house", [("Open Windows", 2019), ("Sunday Rooms", 2022)]),
    ("Oda Reyes", "house", [("Terrace", 2024)]),
    ("Kite & Harbour", "deep", [("Slow Tide", 2021)]),
    ("Nocturne Bureau", "techno", [("Shift Work", 2020), ("Concrete Garden", 2023)]),
    ("Vessel Nine", "techno", [("Pressure Lines", 2022)]),
    ("Aurel Finch", "ambient", [("Moss", 2018), ("Fields at Dawn", 2021)]),
    ("Tessellate", "ambient", [("Quiet Geometry", 2023)]),
    ("The Pale Coast", "indie", [("Postcards", 2017), ("Tall Grass", 2020), ("Every Window", 2024)]),
    ("Juniper Hale", "indie", [("Borrowed Light", 2022)]),
    ("Saltwater Choir", "folk", [("Driftwood Hymns", 2019), ("Winter Almanac", 2023)]),
    ("Wren Calloway", "folk", [("Small Hours", 2021)]),
    ("Iron Meridian", "metal", [("Ashfall", 2018), ("Black Tide Rising", 2022)]),
    ("Hollow Crown", "metal", [("Cathedral of Rust", 2024)]),
    ("Marlow Quartet", "jazz", [("Blue Arcade", 2016), ("After the Rain", 2020)]),
    ("Ines Varga Trio", "jazz", [("Night Tram", 2023)]),
    ("Dusty Cassette", "hiphop", [("Corner Store", 2019), ("Tape Hiss", 2022)]),
    ("Sol Amari", "soul", [("Honey & Static", 2021), ("Golden Hour", 2024)]),
    ("Northern Static", "synth", [("Neon Motorway", 2020), ("Arcade Summer", 2023)]),
    ("Elin Thorsdal", "classical", [("Études for a Quiet House", 2019)]),
    ("Cobalt Parade", "pop", [("Confetti", 2022), ("Bright Side", 2024)]),
]

# kind: (the genre tag, what the style model hears (Discogs labels, the first the strongest), BPM range, energy,
# mood (valence), how often it's sung, where it sits in the sound's space).
KINDS = {
    "liquid": ("Drum and Bass", ["Electronic---Drum n Bass", "Electronic---Liquid Funk"], (170, 176), 0.62, 0.62, 0.45, 0),
    "neuro": ("Drum and Bass", ["Electronic---Drum n Bass", "Electronic---Neurofunk"], (172, 176), 0.9, 0.3, 0.1, 1),
    "house": ("House", ["Electronic---House", "Electronic---Disco"], (120, 126), 0.7, 0.8, 0.5, 2),
    "deep": ("Deep House", ["Electronic---Deep House", "Electronic---House"], (118, 122), 0.5, 0.6, 0.3, 3),
    "techno": ("Techno", ["Electronic---Techno", "Electronic---Minimal"], (128, 136), 0.85, 0.35, 0.05, 4),
    "ambient": ("Ambient", ["Electronic---Ambient", "Electronic---Drone"], (60, 90), 0.12, 0.5, 0.0, 5),
    "indie": ("Indie Rock", ["Rock---Indie Rock", "Rock---Alternative Rock"], (100, 150), 0.6, 0.6, 0.95, 6),
    "folk": ("Folk", ["Folk, World, & Country---Folk", "Rock---Folk Rock"], (80, 120), 0.3, 0.55, 0.95, 7),
    "metal": ("Metal", ["Rock---Heavy Metal", "Rock---Progressive Metal"], (110, 180), 0.95, 0.25, 0.9, 8),
    "jazz": ("Jazz", ["Jazz---Contemporary Jazz", "Jazz---Post Bop"], (90, 160), 0.4, 0.6, 0.05, 9),
    "hiphop": ("Hip Hop", ["Hip Hop---Boom Bap", "Hip Hop---Instrumental"], (84, 96), 0.55, 0.5, 0.7, 10),
    "soul": ("Soul", ["Funk / Soul---Neo Soul", "Funk / Soul---Soul"], (76, 110), 0.45, 0.75, 1.0, 11),
    "synth": ("Synthwave", ["Electronic---Synthwave", "Electronic---Synth-pop"], (96, 122), 0.65, 0.7, 0.4, 12),
    "classical": ("Classical", ["Classical---Modern", "Classical---Impressionist"], (60, 110), 0.15, 0.45, 0.0, 13),
    "pop": ("Pop", ["Pop---Indie Pop", "Electronic---Synth-pop"], (100, 128), 0.7, 0.85, 1.0, 14),
}

FIRST = ["Paper", "Glass", "Silver", "Hollow", "Quiet", "Golden", "Northern", "Slow", "Last", "Open", "Distant", "Velvet",
         "Electric", "Winter", "Small", "Bright", "Lost", "Blue", "Midnight", "Second", "Long", "Soft", "Broken", "New"]
SECOND = ["Rivers", "Harbour", "Signals", "Gardens", "Machines", "Letters", "Horizon", "Rooms", "Weather", "Engines",
          "Satellites", "Lanterns", "Stations", "Tides", "Shadows", "Windows", "Echoes", "Maps", "Mornings", "Avenues",
          "Wires", "Orchards", "Summers", "Radios"]
KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def slug(text):
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def catalog():
    """Every song of the demo, as the fake music server's catalogue wants it, with what the stand-ins say of it."""
    songs, titles = [], set()
    for artist, kind, albums in ARTISTS:
        tag, heard, (low, high), energy, mood, sung, axis = KINDS[kind]
        for album, year in albums:
            rng = random.Random(f"{artist}|{album}")
            for track in range(1, rng.randint(6, 9) + 1):
                while True:
                    title = f"{rng.choice(FIRST)} {rng.choice(SECOND)}"
                    if title not in titles:
                        titles.add(title)
                        break
                song_id = "s" + slug(f"{artist}|{album}|{title}")
                bpm = round(rng.uniform(low, high), 1 if kind in ("jazz", "folk", "classical", "ambient", "indie") else 0)
                songs.append({
                    "id": song_id, "file": f"{song_id}.flac", "title": title, "artist": artist, "album": album, "year": year,
                    "track": track, "genre": tag, "bpm": int(round(bpm)) if rng.random() < 0.6 else None,
                    "duration": rng.randint(150, 420) if kind not in ("ambient", "classical") else rng.randint(240, 600),
                    "expect_bpm": float(bpm), "expect_bar": 3 if kind in ("folk", "classical") and rng.random() < 0.2 else 4,
                    "kind": kind, "heard": [(heard[0], round(rng.uniform(0.55, 0.9), 2)), (heard[1], round(rng.uniform(0.2, 0.5), 2))],
                    "energy": min(1.0, max(0.02, energy + rng.uniform(-0.12, 0.12))),
                    "mood": min(1.0, max(0.02, mood + rng.uniform(-0.15, 0.15))),
                    "sung": rng.random() < sung, "axis": axis,
                    "key": rng.choice(KEYS), "scale": "minor" if rng.random() < (0.75 if mood < 0.5 else 0.35) else "major",
                    "lufs": round(rng.uniform(-13.5, -7.0), 2),
                })
    return songs
