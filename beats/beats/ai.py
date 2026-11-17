"""An AI service to name the mixes (0.54, the owner, 17 Nov: "the AI settings services on Beats for all AI providers
which Siansa has in the app").

The same providers as the Siansa app (its ``AiProvider``): OpenRouter, OpenAI, Anthropic, Google Gemini, Mistral,
Groq, Ollama, or any other with an OpenAI-style API. Each is asked the same way, a chat completion at
``<address>/chat/completions`` with the key as a bearer token, as the app does. Set on the page (Setup): the key is
kept encrypted (:mod:`beats.vault`), never shown again, never logged.

What it's for: a mix's name. Without it (or when it fails) a mix keeps the name its sound gives
(:func:`beats.mixes.Mixes._name`), so nothing waits on it. Only a mix's description is sent: its genres, its energy
and mood in words, three of its artists and its tags. Never a listener's name or history.
"""

import json
import re
import threading
import urllib.error
import urllib.request

from . import log

_log = log.get("ai")

# key: (as it's shown, its address (empty: typed in), the model it starts with, whether it needs a key, what to do)
PROVIDERS = {
    "OPENROUTER": ("OpenRouter", "https://openrouter.ai/api/v1", "google/gemini-2.5-flash", True,
                   "Many models from one account and key, at openrouter.ai."),
    "OPENAI": ("OpenAI", "https://api.openai.com/v1", "gpt-4.1-mini", True, "An API key from platform.openai.com."),
    "ANTHROPIC": ("Anthropic", "https://api.anthropic.com/v1", "claude-haiku-4-5", True, "An API key from console.anthropic.com."),
    "GEMINI": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", True,
               "An API key from Google AI Studio (aistudio.google.com)."),
    "MISTRAL": ("Mistral", "https://api.mistral.ai/v1", "mistral-small-latest", True, "An API key from console.mistral.ai."),
    "GROQ": ("Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", True, "An API key from console.groq.com."),
    "OLLAMA": ("Ollama", "", "llama3.2", False,
               "Ollama on your own network: its address, like 192.168.1.10:11434. No key, and nothing leaves your network."),
    "OTHER": ("Other", "", "", False,
              "Any other service with an OpenAI-style API, like LM Studio, LocalAI or vLLM: its address, and a key if it asks for one."),
}
SETTING = "ai"
TIMEOUT = 45
MOST_NAME = 28  # characters in a name
# A name never promises weather, a season or a time of day: the mixes are for now, whatever it's like outside.
BANNED = re.compile(r"\b(sun|suns|sunny|sunshine|sunlit|sunrise|sunset|summer|summery|spring|autumn|fall|winter|wintry|"
                    r"snow|snowy|rain|rainy|storm|stormy|beach|tropical|morning|afternoon|evening|night|midnight|tonight|"
                    r"dawn|dusk|noon|weekend|monday|friday)\b", re.I)


def completions_url(provider, typed=""):
    """The chat completions call for ``provider``: its own address, or ``typed`` for one on your network
    ("192.168.1.10:11434" gets http:// and /v1, as Ollama and LM Studio serve it). None without one."""
    if provider not in PROVIDERS:
        return None
    base = PROVIDERS[provider][1]
    if not base:
        typed = str(typed or "").strip().rstrip("/")
        if not typed:
            return None
        base = typed if "://" in typed else "http://" + typed
        if not base.split("://", 1)[1].partition("/")[2]:
            base += "/v1"
    return base + "/chat/completions"


class AiError(Exception):
    pass


class Ai:
    def __init__(self, store, vault, opener=None):
        self.store, self.vault = store, vault
        self.opener = opener or urllib.request.urlopen
        self._lock = threading.Lock()
        self.last_error = None

    # ---- the settings ----

    def _saved(self):
        return self.store.setting(SETTING, {}) or {}

    def settings(self):
        """As the page shows them, without the key: ``{"on", "provider", "address", "model", "has_key", "ready",
        "providers": [...], "error"}``."""
        s = self._saved()
        provider = s.get("provider") or "OPENROUTER"
        return {"on": bool(s.get("on")), "provider": provider, "address": s.get("address") or "",
                "model": s.get("model") or PROVIDERS.get(provider, PROVIDERS["OPENROUTER"])[2],
                "has_key": bool(s.get("key")), "ready": self.ready, "error": self.last_error,
                "providers": [{"key": k, "label": p[0], "own_address": not p[1], "model": p[2], "needs_key": p[3], "hint": p[4]}
                              for k, p in PROVIDERS.items()]}

    def save(self, on=None, provider=None, address=None, model=None, key=None):
        """Changes what's given; ``key`` "" removes it, None keeps it."""
        s = dict(self._saved())
        if provider is not None:
            if provider not in PROVIDERS:
                raise AiError("No such AI service")
            s["provider"] = provider
        if on is not None:
            s["on"] = bool(on)
        if address is not None:
            s["address"] = str(address).strip()[:300]
        if model is not None:
            s["model"] = str(model).strip()[:120]
        if key is not None:
            s["key"] = self.vault.seal(str(key).strip()) if str(key).strip() else ""
        self.store.set_setting(SETTING, s)
        self.last_error = None
        return self.settings()

    @property
    def ready(self):
        s = self._saved()
        provider = s.get("provider") or "OPENROUTER"
        needs = PROVIDERS.get(provider, PROVIDERS["OTHER"])[3]
        return bool(s.get("on")) and completions_url(provider, s.get("address")) is not None and \
            bool(s.get("model") or PROVIDERS[provider][2]) and (not needs or bool(s.get("key")))

    # ---- asking ----

    def complete(self, system, user, saved=None):
        """One chat completion's text."""
        s = saved or self._saved()
        provider = s.get("provider") or "OPENROUTER"
        url = completions_url(provider, s.get("address"))
        label = PROVIDERS.get(provider, ("AI",))[0]
        if url is None:
            raise AiError(f"{label}: no address set")
        key = self.vault.open(s.get("key")) if s.get("key") else ""
        if PROVIDERS[provider][3] and not key:
            raise AiError(f"No {label} key set")
        body = json.dumps({"model": s.get("model") or PROVIDERS[provider][2], "temperature": 0.9, "max_tokens": 400,
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "siansa-beats"}
        if key:
            headers["Authorization"] = "Bearer " + key
        if provider == "OPENROUTER":
            headers["X-Title"] = "Siansa Beats"
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with self.opener(request, timeout=TIMEOUT) as response:
                text = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace") if e.fp else ""
            raise AiError(f"{label}: {_error_of(text) or f'HTTP {e.code}'}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise AiError(f"{label} can't be reached: {getattr(e, 'reason', e)}") from None
        try:
            answer = json.loads(text)
        except ValueError:
            raise AiError(f"{label} sent an answer that isn't JSON") from None
        error = _error_of(answer)
        if error:
            raise AiError(f"{label}: {error}")
        try:
            content = answer["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if not content or not str(content).strip():
            raise AiError(f"{label} sent an empty answer")
        return str(content)

    def test(self, **trying):
        """A short call with the settings as they are, or as ``trying`` would make them (not saved): ``{"ok", "said"}``."""
        s = dict(self._saved())
        for k in ("provider", "address", "model"):
            if trying.get(k) is not None:
                s[k] = trying[k]
        if trying.get("key"):
            s["key"] = self.vault.seal(trying["key"])
        try:
            said = self.complete("Answer in one short word.", "Say ready.", s).strip()[:60]
            return {"ok": True, "said": said}
        except AiError as e:
            return {"ok": False, "said": str(e)}

    def name_mixes(self, described):
        """Names for mixes, from ``described`` (``[{"id", "genres", "energy", "mood", "artists", "tags"}]``):
        ``{id: name}`` of those it named well; the rest keep their own. Nothing when it isn't set up or fails."""
        if not described or not self.ready:
            return {}
        lines = "\n".join(json.dumps({k: d.get(k) for k in ("id", "genres", "energy", "mood", "artists", "tags")}, ensure_ascii=False)
                          for d in described)
        system = ("You name playlists for a music streaming app, like a good editor at a streaming service would. "
                  "Each name is 1 to 4 words, evocative and specific to the music, in title case. No emoji, no quotes, "
                  "no artist names, no genre name on its own, and never weather, seasons, the sun or a time of day: "
                  "the listener hears these at any hour. Every name is different. Answer with JSON only: "
                  '{"<id>": "<name>", ...}')
        user = "The playlists (energy and mood are in words, against the listener's own library):\n" + lines
        try:
            text = self.complete(system, user)
        except AiError as e:
            self.last_error = str(e)
            _log.warning("The mixes weren't named by the AI: %s", e)
            return {}
        self.last_error = None
        return clean_names(text, [d["id"] for d in described])


def clean_names(text, ids):
    """The names in an AI's answer that can be used: one of ``ids`` each, short, no weather or time of day, none
    twice."""
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        found = json.loads(match.group(0)) if match else {}
    except ValueError:
        return {}
    out, seen = {}, set()
    for mix_id in ids:
        name = found.get(mix_id) if isinstance(found, dict) else None
        if not isinstance(name, str):
            continue
        name = re.sub(r"\s+", " ", name.strip().strip("\"'“”‘’.")).strip()
        if not name or len(name) > MOST_NAME or BANNED.search(name) or name.casefold() in seen or not re.search(r"\w", name):
            continue
        seen.add(name.casefold())
        out[mix_id] = name
    return out


def _error_of(answer):
    """The error an answer says: most send {"error": {"message": …}}, some a plain {"error": "…"}."""
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except ValueError:
            return answer.strip()[:200] or None
    if not isinstance(answer, dict):
        return None
    error = answer.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or "")[:200] or None
    return str(error)[:200] if error else None
