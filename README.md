# lazy-catalog

Catalogues a folder of films and TV into a `CONTENTS.md` you can read on
GitHub or your phone, and a browsable page that works offline. It updates
itself whenever the folder changes, and a local LLM will tell you what to
watch tonight.

Built for macOS. Python 3.9+, no pip install, no virtualenv, no dependencies.

```
- [x] **The Thing** (1982) · Horror, Sci-Fi · 1h 49m · ★ 8.2
      A research team in Antarctica is hunted by a shape-shifting alien
      that assumes the appearance of its victims.
      *bleak · paranoid · tense*
      `1080p · hevc · EAC3 5.1 · subs: eng · 11.5 GB` · [TMDB](…)
```

## What it does

- Reads scene-release folder names — `The.Thing.1982.REMASTERED.1080p.BluRay…`
  becomes *The Thing (1982)* — and tells films from series.
- Pulls plot, genre, runtime, rating, director and cast from **TMDB**.
- Reads the actual files with **ffprobe**: resolution, codecs, audio channels,
  and whether subtitles are already embedded.
- Asks a **local Ollama model** for mood tags, and for a ranked recommendation
  when you ask for one.
- Regenerates `CONTENTS.md` and a self-contained `index.html` every run.
- Watches the folder with **launchd**, so a new download appears on its own.

## The one design rule

**The model is never asked for a fact.**

Runtimes, years, ratings and plots come from TMDB. Resolution and subtitles
come from the file itself. The model is asked exactly two things: what a
mangled folder name probably says, and how a film *feels*. Both are questions
where a wrong answer is an opinion rather than an error.

This matters because a catalogue that is confidently wrong is worse than one
that is incomplete. Ask a 24B model for the runtime of an obscure film and it
will give you a plausible number that is off by twenty minutes. Anything not
verified against TMDB is marked with a `~` so you know not to trust it.

## Install

```bash
git clone https://github.com/RafatH0ssain/lazy-catalog.git ~/Projects/lazy-catalog
cd ~/Projects/lazy-catalog
./scripts/lazy-catalog init
```

`init` asks for your library folder and your TMDB API key. The key is typed
hidden, checked against TMDB, and written to
`~/.config/lazy-catalog/config.json` at mode 600. It never enters your shell
history and never enters this repo.

A TMDB key is free and instant: [themoviedb.org](https://www.themoviedb.org)
→ Settings → API. Both v3 keys and v4 read-access tokens work.

Then:

```bash
./scripts/lazy-catalog update
```

### Optional extras

| Tool | Gives you | Install |
|---|---|---|
| ffmpeg | resolution, codecs, embedded-subtitle detection | `brew install ffmpeg` |
| Ollama | mood tags and `lazy-pick` | `brew install ollama` |
| subliminal | subtitle downloads | `uv tool install subliminal` |

Everything degrades gracefully. Without ffmpeg you lose the tech line; without
Ollama you lose mood tags; the catalogue still builds.

### Put the commands on your PATH

```bash
echo 'alias lazy-catalog="$HOME/Projects/lazy-catalog/scripts/lazy-catalog"' >> ~/.zshrc
echo 'alias lazy-pick="$HOME/Projects/lazy-catalog/scripts/lazy-pick"' >> ~/.zshrc
echo 'alias movies="$HOME/Projects/lazy-catalog/scripts/movies"' >> ~/.zshrc
```

## Watching the folder

```bash
lazy-catalog install
```

Installs a launchd agent that runs on any change to the library folder, plus
every 30 minutes as a backstop for downloads that were still being written
when the folder first appeared. `lazy-catalog uninstall` removes it.

**New folders are not published immediately.** A torrent creates its folder
long before the file is finished, so a folder is only added once its size has
stopped changing between two checks, and never while a `.part` or `.!qB` file
is present. A finished download typically appears within a couple of minutes.

## Commands

| Command | Does |
|---|---|
| `lazy-catalog init` | set up the config and TMDB key |
| `lazy-catalog update` | catalogue anything new |
| `lazy-catalog update --now` | skip the wait for downloads to settle |
| `lazy-catalog rebuild` | discard the cache and start over, keeping watched ticks |
| `lazy-catalog status` | what the catalogue currently knows |
| `lazy-catalog subs` | download subtitles for titles that have none |
| `lazy-catalog nfo` | write `.nfo` sidecars for Jellyfin, Kodi and Plex |
| `lazy-catalog suggest-renames` | report tidier folder names, changing nothing |
| `lazy-catalog install` / `uninstall` | start or stop watching the folder |
| `movies` | open the library page |
| `movies --refresh` | update first, then open |
| `lazy-pick …` | ask the model what to watch |

## lazy-pick

```
$ lazy-pick something short and funny

S  Dogma (1999) · 2h 10m
   Irreverent, quotable, and asks nothing of you emotionally.

A  Wild Tales (2014) · 2h 2m
   An anthology, so you can stop after one segment guilt-free.

Honorable mentions
   The Truman Show (1998) — funny, but it lingers more than you asked for.

Ruled out: Beau is Afraid, Anomalisa
```

The model picks by number from a list it is handed, and every number is
checked against that list before anything is printed — it cannot recommend a
film you don't own. Flags: `--unwatched`, `--films`, `--series`.

## Marking things watched

Tick the box in `CONTENTS.md`:

```markdown
- [x] **Her** (2013) · Drama, Romance · 2h 6m · ★ 8.0
```

That's the only place watched state is set. It's read back on every run and
survives regeneration — each entry carries an invisible key anchor, so a tick
even survives the folder being renamed. The web page displays watched state
but doesn't set it, so the two views can't disagree.

## Where things live

```
~/TV/
├── CONTENTS.md          the readable catalogue (the only visible file added)
├── .lazy/
│   ├── cache.json       the source of truth; both views regenerate from it
│   ├── index.html       the browsable page
│   ├── posters/         cached artwork, so the page works offline
│   └── run.log          what the background job did
└── …your folders, untouched…
```

`~/.config/lazy-catalog/config.json` holds the API key, at mode 600, outside
the repo.

## Things it deliberately doesn't do

**It never renames or moves your files.** `suggest-renames` prints what it
would do and stops. Renaming is also mildly harmful here: the catalogue is
keyed on folder name, so a rename loses that title's watched tick. If you
wanted tidy names for a media server, `lazy-catalog nfo` gets you recognition
without touching a filename.

**It doesn't integrate with Plex or Jellyfin.** They are media servers that do
their own scraping and ship their own UI, so an integration would duplicate
most of this project. The `.nfo` sidecars are the useful 5%: install Jellyfin
later and your library identifies instantly, with no scraping.

**It doesn't download subtitles automatically.** The free providers are rate
limited, and a folder-watching loop could burn a day's quota in one sweep.
`lazy-catalog subs` runs only when you ask.

## Tests

```bash
python3 -m unittest discover -s tests -t . -v
```

124 tests, no network, no fixtures to download. The release-name parser is
tested against real scene folder names; TMDB, ffprobe and Ollama are mocked.

## License

MIT
