"""What goes into a listener's mixes, as they choose it (0.56; the owner, 17 Nov: "a settings page so the user can
adjust what should be contained or left out from the mixes. Make settings or toggles for everything that is currently
automatically chosen").

Every choice :mod:`beats.mixes` used to make by itself is here, with what it was as its default, so a listener who
changes nothing gets the mixes they had. Kept per listener in the store's settings (``mix_settings:<listener>``),
changed on Siansa Beats' Mixes page or from the app (``/api/v1/mixes/settings``). Only what differs from the default is
kept, so a better default later reaches everyone who never changed it.
"""

KEY = "mix_settings:"

# name -> (default, kind, low, high, what it is, in the words the page and the app show). Kinds: "on" a switch,
# "number" a whole number from low to high, "words" a list of names (genres, artists) to leave out.
SETTINGS = {
    # Which mixes are made.
    "now": (True, "on", None, None, "For now: mixes for this part of the day (Home's For now)"),
    "now_count": (4, "number", 1, 6, "How many For now mixes"),
    "daily": (True, "on", None, None, "Made for you: the kinds of music you play most (Home's Made for you)"),
    "daily_count": (5, "number", 1, 8, "How many Made for you mixes"),
    "repeat": (True, "on", None, None, "More of you: On repeat"),
    "rediscover": (True, "on", None, None, "More of you: Rediscover"),
    "new": (True, "on", None, None, "More of you: New for you"),
    # 0.65 (the owner, 26 Nov).
    "deep": (True, "on", None, None, "More of you: Deep cuts, songs you haven't played from albums you love"),
    "forgotten": (True, "on", None, None, "More of you: Forgotten artists, artists you played a lot and not lately"),
    # Where they go on Home (0.62, the owner: "I don't like the idea of always separating More of you and Made for you";
    # "allow choosing how many cards it sends to Siansa").
    "together": (False, "on", None, None, "All in one row on Home, in For now's place: For now's first, then Made for you's, then More of you's"),
    "together_count": (6, "number", 1, 20, "How many cards that one row has, at most"),
    # What's in each.
    "size": (40, "number", 10, 100, "Songs in a mix"),
    "familiar": (40, "number", 0, 100, "Songs you know, in %: the rest are new to you"),
    "per_artist": (2, "number", 1, 5, "Songs by one artist, at most"),
    "fresh_days": (45, "number", 0, 180, "Leave out songs you played in the last … days"),
    "leave_genres": ([], "words", None, None, "Genres to leave out"),
    "leave_artists": ([], "words", None, None, "Artists to leave out"),
    # What they're made from.
    "time_of_day": (True, "on", None, None, "Made for the part of the day you listen in"),
    "weekend_apart": (True, "on", None, None, "Weekends apart from weekdays"),
    "daylight": (True, "on", None, None, "Calmer when it's dark outside"),
    "season": (True, "on", None, None, "This time of year counts more"),
    "skips": (True, "on", None, None, "Songs you skip count for less"),
    "half_life": (120, "number", 14, 730, "Listening counts half after … days"),
    "repeat_days": (30, "number", 7, 90, "On repeat looks back … days"),
    "forgotten_days": (180, "number", 30, 730, "Rediscover: not played for … days"),
    # Their names.
    "ai_names": (True, "on", None, None, "Names and lines from the AI service"),
}

MOST_WORDS = 50
MOST_WORD = 80


def defaults():
    return {name: (list(d) if isinstance(d, list) else d) for name, (d, *_rest) in SETTINGS.items()}


def clean(given, base=None):
    """``given`` (from the page or the app) checked against :data:`SETTINGS` over ``base`` (the defaults): unknown
    names dropped, numbers kept in their limits, words trimmed, without repeats. A value that can't be read is a
    ``ValueError`` naming the setting."""
    out = dict(base or defaults())
    for name, value in (given or {}).items():
        if name not in SETTINGS:
            continue
        default, kind, low, high, _ = SETTINGS[name]
        if kind == "on":
            if not isinstance(value, bool):
                raise ValueError(f"{name} is true or false")
            out[name] = value
        elif kind == "number":
            if isinstance(value, bool):
                raise ValueError(f"{name} is a number: {low} to {high}")
            try:
                out[name] = max(low, min(high, int(value)))
            except (TypeError, ValueError):
                raise ValueError(f"{name} is a number: {low} to {high}") from None
        else:
            if isinstance(value, str):
                value = value.split(",")
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"{name} is a list of names")
            seen, words = set(), []
            for word in value:
                word = " ".join(str(word).split())[:MOST_WORD]
                if word and word.lower() not in seen:
                    seen.add(word.lower())
                    words.append(word)
            out[name] = words[:MOST_WORDS]
    return out


def load(store, listener):
    """``listener``'s settings, every one (the defaults where they changed nothing)."""
    try:
        return clean(store.setting(KEY + (listener or ""), {}) or {})
    except ValueError:  # written by hand, or by an older Siansa Beats: the defaults
        return defaults()


def save(store, listener, given):
    """Changes ``listener``'s settings by ``given`` (only the ones named) and returns them all."""
    merged = clean(given, load(store, listener))
    base = defaults()
    store.set_setting(KEY + (listener or ""), {k: v for k, v in merged.items() if v != base[k]})
    return merged


def described():
    """Each setting for a page or an app to draw: ``[{"name", "kind", "default", "low", "high", "label"}]``."""
    return [{"name": name, "kind": kind, "default": default, "low": low, "high": high, "label": label}
            for name, (default, kind, low, high, label) in SETTINGS.items()]


def signature(settings):
    """What mixes made with ``settings`` are kept by: changed settings make them again."""
    return tuple((k, tuple(v) if isinstance(v, list) else v) for k, v in sorted(settings.items()))
