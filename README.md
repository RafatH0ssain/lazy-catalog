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
for c in lazy-catalog lazy-pick lazy-suggest movies; do
  echo "alias $c=\"$PWD/scripts/$c\"" >> ~/.zshrc
done
source ~/.zshrc

lazy-catalog init      # asks for your library folder and TMDB key
lazy-catalog update    # builds the catalogue
lazy-catalog install   # watch the folder from now on
```

Either key can be replaced on its own later with `lazy-catalog key tmdb` or
`lazy-catalog key omdb`, without walking through the rest of setup. A new OMDb
key does not work until you click the activation link OMDb emails you.

`init` also asks for an optional [OMDb key](https://www.omdbapi.com/apikey.aspx)
(free, instant). With one you get Rotten Tomatoes, Metacritic and IMDb scores
alongside the TMDB rating, looked up by the IMDb id TMDB already returns — so
they can never land on the wrong film. Without one, everything else works the
same.

The TMDB key is [free and instant](https://www.themoviedb.org/settings/api).
`init` takes it with hidden input and writes it to
`~/.config/lazy-catalog/config.json` at mode 600 — never your shell history,
never the repo. v3 keys and v4 tokens both work.

Optional: `brew install ffmpeg` for tech specs, [Ollama](https://ollama.com)
for mood tags and `lazy-pick`, `uv tool install subliminal` for subtitles.
Each one degrades gracefully if missing.

## Using it

```bash
movies                    # open the library page; Ctrl+C stops it
lazy-pick something short and funny
lazy-suggest slow and bleak   # films you *don't* own, that you might like
lazy-catalog subs --films # subtitles for anything missing them
lazy-catalog delete lobster  # move a title to the Trash
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

`lazy-suggest` is the opposite: it reads your library as a taste profile and
recommends films you *don't* have, weighting the ones you've marked watched.
Every suggestion is looked up on TMDB before you see it — anything the model
invented is dropped, and the year, runtime, genres and rating shown are TMDB's,
not the model's. Survivors are appended to `WATCHLIST.md` with checkboxes, and
nothing is ever suggested twice.

Both commands take `--model` if you want to try another one, and `suggest_model`
in the config can differ from `ollama_model`.

A 12B model is the default deliberately. On a 24GB machine a 24B measured 20GB
resident and 12.7s per call against 8.6GB and 4.7s for a 12B, with tags that
were no better — and the background job runs unattended, so a model that large
just makes the machine feel slow. Models are released after a minute rather
than Ollama's default five, and reasoning is switched off: gemma4 spent 126
tokens and 11.6s on a one-word answer with it on, and 3 tokens and 0.5s with
it off. Nothing here wants visible chain-of-thought.

`suggest` defaults to `gemma4:12b` and everything else to `gemma3:12b`, because
they are good at different things: asked for something "slow and bleak", gemma4
named Stalker, Threads and The Turin Horse where gemma3 offered Winter's Bone —
but gemma3 is faster and picks better from a list it is handed.

Click any title to expand it, then click its poster to play it in VLC, or
"Move to Trash" to delete it. Both only appear while `movies` is running,
since a page opened straight off disk has no way to reach your machine.

Mark things watched by ticking the box in `CONTENTS.md`. That's the only place
it's set; it's read back on every run and survives regeneration, even if the
folder gets renamed.

`lazy-catalog --help` lists the rest.

## Notes

`movies` serves the page from `127.0.0.1` and runs until you Ctrl+C, rather
than opening a file. That's only so a poster click can hand the file to VLC:
VLC registers no URL scheme on macOS, so a page loaded from `file://` has no
way to launch it. The play endpoint takes a catalogue key, never a path, looks
the file up itself, refuses anything that doesn't resolve inside your library,
and requires a token that only the page it served knows.

New titles aren't published until their size stops changing, so a
half-finished download never lands in the catalogue.

Reading a release name is guesswork with rules. A bracketed `(2017)` is taken
as the release year over any bare number, and a year that hasn't happened yet
is treated as part of the title — which is how *Blade Runner 2049 (2017)* comes
out as the 2017 film rather than a 2049 one. Season markers end a title in
every spelling (`Season 1`, `S04`, `S01E01`, `1x01`), and anything under an
`Extras` folder is excluded from episode counts and from playback.

Your files are never renamed or moved. `suggest-renames` prints what it would
do and stops — and `lazy-catalog nfo` gets you media-server recognition without
touching a filename anyway.

Subtitles only download when you ask, capped at 25 files per run, because free
providers are rate limited and one long series would spend the day's quota.

```bash
python3 -m unittest discover -s tests -t .   # 299 tests
```

MIT.
