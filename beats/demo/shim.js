// The demo's stand-in for the service (demo/build.py puts this before the page's own script). The page asks its
// questions as ever; they're answered here from what the real service said of a made-up library when the demo was
// built. Nothing leaves the browser, and nothing changed here is kept: a reload starts again.
(() => {
  const data = window.demoData;
  const answers = data.answers;
  const misses = window.demoMisses = [];  // what the page asked that the demo can't answer: the build's check reads it
  const NOT_HERE = "This is the demo, with made-up music: that needs a real Siansa Beats. Nothing was changed.";

  // ---- the clock: the day the demo was made, moving on from there, so "today" is where its listening ends ----
  const RealDate = Date, opened = RealDate.now();
  const nowMs = () => data.at + (RealDate.now() - opened);
  class DemoDate extends RealDate {
    constructor(...args) { if (args.length) super(...args); else super(nowMs()); }
    static now() { return nowMs(); }
  }
  window.Date = DemoDate;

  // ---- pictures: drawn from the name, one for each album and each artist ----
  const hash = (text) => { let h = 2166136261; for (const c of text) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
  const drawn = new Map();
  function picture(seed, round) {
    if (drawn.has(seed)) return drawn.get(seed);
    let h = hash(seed);
    const next = () => { h = Math.imul(h ^ (h >>> 15), 2246822507) >>> 0; h = Math.imul(h ^ (h >>> 13), 3266489909) >>> 0; return (h >>> 8) / 16777216; };
    const hue = Math.floor(next() * 360), turn = 30 + Math.floor(next() * 90);
    const a = `hsl(${hue} ${55 + next() * 25}% ${28 + next() * 14}%)`, b = `hsl(${(hue + turn) % 360} ${60 + next() * 25}% ${48 + next() * 16}%)`;
    const c = `hsl(${(hue + 180) % 360} 70% 82%)`;
    let shapes = "";
    if (round) {  // an artist: rings, like a record
      for (let i = 0; i < 4; i++) shapes += `<circle cx="${100 + (next() - 0.5) * 30}" cy="${100 + (next() - 0.5) * 30}" r="${22 + i * 22}" fill="none" stroke="${c}" stroke-opacity="${0.5 - i * 0.09}" stroke-width="${2 + next() * 5}"/>`;
    } else {  // an album: a sun, a horizon and a few bars
      const y = 95 + next() * 50;
      shapes += `<circle cx="${50 + next() * 100}" cy="${y - 20}" r="${26 + next() * 26}" fill="${c}" fill-opacity="0.75"/>`;
      shapes += `<rect x="0" y="${y}" width="200" height="${200 - y}" fill="#000" fill-opacity="0.28"/>`;
      for (let i = 0; i < 9; i++) shapes += `<rect x="${14 + i * 20}" y="${y + 12}" width="10" height="${8 + next() * (170 - y)}" rx="3" fill="${c}" fill-opacity="0.55"/>`;
    }
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs><rect width="200" height="200" fill="url(#g)"/>${shapes}</svg>`;
    const url = "data:image/svg+xml," + encodeURIComponent(svg);
    drawn.set(seed, url);
    return url;
  }
  const songById = new Map(answers["songs:all"].map((row) => [row.id, row]));
  window.demoArt = (kind, song) => {
    const row = songById.get(song) || {artist: song, album: song};
    return kind === "artist" ? picture("artist|" + row.artist, true) : picture("album|" + row.artist + "|" + row.album, false);
  };

  // ---- a song to play: there are no files, so each song gets a sound made here, at its own tempo and in its key ----
  const NOTES = {C: 0, "C#": 1, D: 2, "D#": 3, E: 4, F: 5, "F#": 6, G: 7, "G#": 8, A: 9, "A#": 10, B: 11};
  let playing = null;
  window.demoAudio = (id) => {
    const row = songById.get(id);
    if (playing) URL.revokeObjectURL(playing);
    if (!row || !row.result || !row.result.bpm) return (playing = null, "");
    const rate = 8000, seconds = Math.min(row.duration || 180, 600), n = Math.floor(seconds * rate);
    const out = new Float32Array(n);
    const beat = 60 / row.result.bpm, bar = row.result.beats_per_bar || 4, first = (row.result.first_downbeat_ms || 400) / 1000;
    const style = ((row.genres || [])[0] || {}).label || "";
    const soft = /Ambient|Drone|Classical|Folk|Jazz|Soul/.test(style);
    const root = 55 * Math.pow(2, (((NOTES[(row.sound || {}).key] ?? 9) + 3) % 12) / 12);  // from A1 up
    const third = (row.sound || {}).scale === "major" ? 4 : 3;
    const chord = [1, Math.pow(2, third / 12), Math.pow(2, 7 / 12)].map((x) => root * 4 * x);
    let seed = hash(id);
    const noise = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 2147483648 - 1; };
    for (let i = 0; i < n; i++) {  // the chord, swelling bar by bar
      const t = i / rate, swell = 0.6 + 0.4 * Math.sin(2 * Math.PI * t / (beat * bar * 4));
      out[i] = (Math.sin(2 * Math.PI * chord[0] * t) + Math.sin(2 * Math.PI * chord[1] * t) + Math.sin(2 * Math.PI * chord[2] * t)) * (soft ? 0.07 : 0.035) * swell;
    }
    for (let b = 0, t0 = first; t0 < seconds - 0.3; b++, t0 = first + b * beat) {
      const down = b % bar === 0, start = Math.floor(t0 * rate);
      const part = Math.floor(b / (bar * 16)) % 4;  // sixteen bars at a time: every fourth part is a breakdown
      if (!soft && part !== 3) {  // the kick
        for (let i = 0; i < rate * 0.16 && start + i < n; i++) {
          const t = i / rate;
          out[start + i] += Math.sin(2 * Math.PI * (48 * t + 70 * (1 - Math.exp(-t * 30)) / 30)) * Math.exp(-t * 22) * (down ? 0.75 : 0.6);
        }
        const hat = Math.floor((t0 + beat / 2) * rate);  // the hat, between the beats
        for (let i = 0; i < rate * 0.03 && hat + i < n; i++) out[hat + i] += noise() * 0.1 * (1 - i / (rate * 0.03));
      }
      for (let i = 0; i < rate * beat * 0.45 && start + i < n; i++) {  // the bass: the key's note, a fifth up on the third beat
        const t = i / rate, f = root * (b % bar === 2 ? 1.5 : 1);
        out[start + i] += Math.sin(2 * Math.PI * f * t) * (soft ? 0.12 : 0.22) * Math.min(1, t * 80) * Math.exp(-t * 4);
      }
    }
    const fade = rate * 4;
    const wav = new DataView(new ArrayBuffer(44 + n * 2));
    const text = (at, s) => { for (let i = 0; i < s.length; i++) wav.setUint8(at + i, s.charCodeAt(i)); };
    text(0, "RIFF"); wav.setUint32(4, 36 + n * 2, true); text(8, "WAVEfmt "); wav.setUint32(16, 16, true); wav.setUint16(20, 1, true);
    wav.setUint16(22, 1, true); wav.setUint32(24, rate, true); wav.setUint32(28, rate * 2, true); wav.setUint16(32, 2, true);
    wav.setUint16(34, 16, true); text(36, "data"); wav.setUint32(40, n * 2, true);
    for (let i = 0; i < n; i++) {
      const edge = Math.min(1, i / fade, (n - i) / fade);
      wav.setInt16(44 + i * 2, Math.max(-1, Math.min(1, out[i] * edge)) * 32767, true);
    }
    return (playing = URL.createObjectURL(new Blob([wav], {type: "audio/wav"})));
  };

  // ---- each song's own page: one more file, fetched the first time a song is opened ----
  const realFetch = window.fetch.bind(window);
  let details = null;
  const songPages = () => details || (details = new Promise((done, failed) => {
    const script = document.createElement("script");
    script.src = data.songs;
    script.onload = () => done(window.demoSongs);
    script.onerror = () => { details = null; failed(new Error("The demo's songs couldn't be fetched; try again.")); };
    document.head.appendChild(script);
  }));

  // ---- what's changed since the page was opened, for as long as it's open ----
  let mixesTurn = 0;
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const ok = (body) => ({status: 200, body});
  const no = (text = NOT_HERE, status = 400) => ({status, body: {error: text}});

  function songsList(q) {
    const show = q.get("show") || "all", find = (q.get("find") || "").trim().toLowerCase(), limit = +(q.get("limit") || 0);
    let rows = answers["songs:all"];
    if (show !== "all" && answers["songs:" + show]) { const ids = new Set(answers["songs:" + show]); rows = rows.filter((r) => ids.has(r.id)); }
    if (find) rows = rows.filter((r) => find.split(/\s+/).every((word) => `${r.title} ${r.artist} ${r.album}`.toLowerCase().includes(word)));
    return limit ? rows.slice(0, limit) : rows;
  }

  async function get(path, q) {
    const key = path + (q.toString() ? "?" + sorted(q) : "");
    if (path === "api/songs") return ok(songsList(q));
    if (path === "api/mixes" && !q.get("part") && mixesTurn) return ok(answers["mixes:again"][(mixesTurn - 1) % answers["mixes:again"].length]);
    if (path === "api/voice/songs") {
      const whole = answers[`api/voice/songs?limit=1000&line=${q.get("line")}&offset=0&order=${q.get("order")}`];
      if (!whole) return miss(key);
      const offset = +(q.get("offset") || 0), limit = +(q.get("limit") || 50);
      const list = Object.keys(whole).find((k) => Array.isArray(whole[k]));
      return ok({...whole, [list]: whole[list].slice(offset, offset + limit)});
    }
    if (path === "api/log") return ok(+q.get("after") ? {...answers["api/log?after=0&limit=1000"], lines: []} : answers["api/log?after=0&limit=1000"]);
    const song = path.match(/^api\/songs\/([^/]+)$/);
    if (song) { const all = await songPages(), found = all[decodeURIComponent(song[1])]; return found ? ok(found) : no("That song isn't in the demo.", 404); }
    if (key in answers) return answers[key] && answers[key].missing ? { status: 404, body: JSON.parse(answers[key].missing) } : ok(answers[key]);
    if (path in answers) return ok(answers[path]);
    return miss(key);
  }
  const sorted = (q) => new URLSearchParams([...q.entries()].sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0))).toString();
  function miss(key) { misses.push(key); console.warn("The demo has no answer for", key); return no("That isn't in the demo.", 404); }

  // Changes that only move a switch or a number: kept in the page's answers until it's closed.
  async function change(method, path, body) {
    body = body || {};
    if (path === "api/mixes/settings" && method === "POST") {
      const kept = answers["api/mixes/settings"];
      const {keep_days: days, ...settings} = body.settings || {};
      Object.assign(kept.settings, settings);
      if (days != null) kept.keep_days = days;
      return ok(kept);
    }
    if (path === "api/mixes/keep") { answers["api/mixes/settings"].keep_days = body.days; return ok({keep_days: body.days}); }
    if (path === "api/mixes/again") { mixesTurn += 1; return ok({user: answers["api/mixes/settings"].user, times: mixesTurn}); }
    if (path === "api/vocals") {
      for (const where of [answers["api/vocals"], answers["api/status"].vocals]) for (const k of ["on", "only_sung", "alone"]) if (k in body) where[k] = body[k];
      return ok(answers["api/vocals"]);
    }
    if (path === "api/log/level") { answers["api/status"].log_level = body.level; answers["api/log?after=0&limit=1000"].level = body.level; return ok({level: body.level}); }
    if (path === "api/pause" || path === "api/resume") { answers["api/status"].paused = path === "api/pause"; return ok({paused: answers["api/status"].paused}); }
    if (path === "api/listens/memory") { const m = answers["api/listens"]; if (m && m.memory) m.memory.minutes = body.minutes; return ok({minutes: body.minutes}); }
    if (path === "api/signout") return ok({});
    const marks = path.match(/^api\/songs\/([^/]+)\/marks(?:\/(\d+))?$/);
    if (marks) {
      const page = (await songPages())[decodeURIComponent(marks[1])];
      if (!page) return no("That song isn't in the demo.", 404);
      page.marks = page.marks || [];
      if (method === "POST") page.marks.push({id: Date.now() % 1e9, seconds: body.seconds, at: Date.now() / 1000});
      else page.marks = page.marks.filter((m) => String(m.id) !== marks[2]);
      return ok({marks: page.marks});
    }
    if (window.banner) window.banner(NOT_HERE);  // said here too: not every button of the page says what went wrong
    return no();
  }

  window.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    if (!/^api\//.test(url)) return realFetch(input, init);
    const method = (init.method || "GET").toUpperCase();
    const [path, query = ""] = url.split("?");
    const q = new URLSearchParams(query);
    for (const own of ["tz", "user", "server"]) q.delete(own);
    let body = null;
    try { body = typeof init.body === "string" ? JSON.parse(init.body) : null; } catch (e) { /* a file: not in the demo */ }
    const out = method === "GET" ? await get(path, q) : await change(method, path, body);
    return new Response(JSON.stringify(copy(out.body)), {status: out.status, headers: {"Content-Type": "application/json"}});
  };

  // ---- what isn't a question to the service: files to download, a song to play ----
  document.addEventListener("click", (e) => {
    const link = e.target.closest && e.target.closest('a[href^="api/"]');
    if (!link) return;
    e.preventDefault();
    if (window.banner) window.banner("This is the demo, with made-up music: there's no file to download here.");
  }, true);

  // Where a website's rules don't let a made-up sound play, say so instead of staying silent.
  document.addEventListener("securitypolicyviolation", (e) => {
    if (/^media-src/.test(e.violatedDirective || "") && window.banner) window.banner("Songs can't be played in the demo on this website yet.");
  });

  // ---- the line that says what this is, and the way out (the owner, 25 Nov: "no easy way on mobile or web to exit") ----
  // Always there: hiding the note folds it to a small "Exit demo" in the corner, never takes the way out away.
  document.addEventListener("DOMContentLoaded", () => {
    // Back to where the demo was opened from on the website, else to the Siansa Beats page.
    let back = "/beats";
    try { const from = new URL(document.referrer); if (from.origin === location.origin && !/beats-demo/.test(from.pathname)) back = from.pathname + from.search; } catch (e) { /* no page before */ }
    const note = document.createElement("div");
    note.id = "demo-note";
    note.setAttribute("role", "note");
    note.innerHTML = '<a class="exit" href="' + back + '" aria-label="Exit the demo">← Exit demo</a>' +
      '<span class="what"><b>Demo</b> Made-up music and listening. Nothing here is real, and nothing you change is kept.</span>' +
      '<a class="get" href="/beats">Get Siansa Beats</a><button type="button" aria-label="Make this note small">×</button>';
    const style = document.createElement("style");
    style.textContent = "#demo-note{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:1000;display:flex;gap:10px;align-items:center;" +
      "max-width:calc(100vw - 24px);padding:6px 8px 6px 6px;border-radius:999px;background:#12161c;color:#f4f6f8;font:500 13px/1.3 system-ui,sans-serif;" +
      "box-shadow:0 6px 24px rgba(0,0,0,.28)}#demo-note .what b{color:#ffb547;letter-spacing:.06em;text-transform:uppercase;font-size:11px;margin-right:6px}" +
      "#demo-note a{border-radius:999px;padding:7px 12px;text-decoration:none;white-space:nowrap;font-weight:600;min-height:20px}" +
      "#demo-note .exit{color:#f4f6f8;background:#2a313b}#demo-note .exit:hover{background:#38414d}" +
      "#demo-note .get{color:#12161c;background:#ffb547}" +
      "#demo-note button{background:none;border:0;color:#9aa4b0;font-size:20px;line-height:1;cursor:pointer;padding:6px 8px;min-width:32px;min-height:32px}" +
      "#demo-note.small{left:auto;right:14px;transform:none;padding:6px}#demo-note.small .what,#demo-note.small .get,#demo-note.small button{display:none}" +
      "@media (max-width:640px){#demo-note{left:12px;right:12px;transform:none;border-radius:16px;flex-wrap:wrap;padding:8px}" +
      "#demo-note .what{flex:1 1 100%;order:-1;padding:2px 4px}#demo-note .exit,#demo-note .get{flex:1;text-align:center}" +
      "#demo-note.small{left:auto;right:12px;border-radius:999px}#demo-note.small .exit{flex:none}}";
    document.head.appendChild(style);
    document.body.appendChild(note);
    note.querySelector("button").addEventListener("click", () => note.classList.add("small"));
  });
})();
