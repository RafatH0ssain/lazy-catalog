# lazy-catalog

Turns a folder of films and TV into a readable `CONTENTS.md` and an offline
web page, updates itself when the folder changes, and lets a local LLM tell
you what to watch.

macOS, Python 3.9+, no dependencies.

![The library page](docs/library.png)

## The one rule

**The model is never asked for a fact.** Runtimes, genres, ratings and plots
come from TMDB; resolution, codecs and embedded subtitles come from ffprobe
reading your actual files. The model only cleans up unreadable folder names and
writes mood tags — questions where a wrong answer is an opinion, not an error.
Ask a small model for a runtime and it will confidently invent one. Anything
unverified is marked `~`.

## Setup

```bash
git clone https://github.com/RafatH0ssain/lazy-catalog.git ~/Projects/lazy-catalog
cd ~/Projects/lazy-catalog

# Put the commands on your PATH first, or none of them will be found.
for c in lazy-catalog lazy-pick movies; do
  echo "alias $c=\"$PWD/scripts/$c\"" >> ~/.zshrc
done
source ~/.zshrc

lazy-catalog init      # asks for your library folder and TMDB key
lazy-catalog update    # builds the catalogue
lazy-catalog install   # watch the folder from now on
```

The TMDB key is [free and instant](https://www.themoviedb.org/settings/api).
`init` takes it with hidden input and writes it to
`~/.config/lazy-catalog/config.json` at mode 600 — never your shell history,
never the repo. v3 keys and v4 tokens both work.

Optional: `brew install ffmpeg` for tech specs, [Ollama](https://ollama.com)
for mood tags and `lazy-pick`, `uv tool install subliminal` for subtitles.
Each one degrades gracefully if missing.

## Using it

```bash
movies                    # open the library page
lazy-pick something short and funny
lazy-catalog subs --films # subtitles for anything missing them
lazy-catalog nfo          # .nfo sidecars for Jellyfin, Kodi and Plex
```

```
$ lazy-pick under two hours, something bleak I can pay full attention to

S  Closer (2004) · 1h 44m
   A tense and unsettling drama that demands your undivided attention.
A  Blue Valentine (2010) · 1h 52m
   This melancholy romance will grip you with its bleak intensity.

Honorable mentions
   Force Majeure (2014) · 1h 59m — A slow burn with a tense, unsettling vibe.

Ruled out: The Thing
```

The model picks by number from a list it's handed, and every number is checked
against that list, so it can't recommend a film you don't own.

Mark things watched by ticking the box in `CONTENTS.md`. That's the only place
it's set; it's read back on every run and survives regeneration, even if the
folder gets renamed.

`lazy-catalog --help` lists the rest.

## Notes

New folders aren't published until their size stops changing, so a
half-finished download never lands in the catalogue.

Your files are never renamed or moved. `suggest-renames` prints what it would
do and stops — and `lazy-catalog nfo` gets you media-server recognition without
touching a filename anyway.

Subtitles only download when you ask, capped at 25 files per run, because free
providers are rate limited and one long series would spend the day's quota.

```bash
python3 -m unittest discover -s tests -t .   # 139 tests, no network
```

MIT.
