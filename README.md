# lazy-catalog

Turns a local folder of films and TV into a browsable web page and Markdown catalogue. It updates automatically and uses a local LLM to recommend what to watch.

macOS, Python 3.9+, zero strict dependencies.

## Setup

```bash
git clone https://github.com/RafatH0ssain/lazy-catalog.git ~/Projects/lazy-catalog
cd ~/Projects/lazy-catalog

# Add aliases to your shell
for c in lazy-catalog lazy-pick lazy-suggest movies; do
  echo "alias $c=\"$PWD/scripts/$c\"" >> ~/.zshrc
done
source ~/.zshrc

lazy-catalog init    # Prompts for library path & free TMDB key
lazy-catalog update  # Builds the initial catalogue
lazy-catalog install # Runs in background to watch for folder changes
```

*Optional but recommended:* `brew install ffmpeg` (tech specs), [Ollama](https://ollama.com) (recommendations), `uv tool install subliminal` (subtitles). An [OMDb key](https://www.omdbapi.com/apikey.aspx) adds Rotten Tomatoes, Metacritic and IMDb scores — replace either key later with `lazy-catalog key tmdb|omdb`.

## Usage

```bash
movies                       # Opens local web UI (Ctrl+C to stop)
lazy-pick something funny    # LLM picks from your existing library
lazy-suggest slow and bleak  # LLM suggests films you *don't* own
lazy-catalog subs --films    # Downloads missing subtitles (--series too)
lazy-catalog delete lobster  # Moves a title to the Trash
lazy-catalog nfo             # Generates metadata for Plex/Jellyfin/Kodi
```

## Highlights

* **Click to play:** Running `movies` starts a local server; clicking a poster in the UI opens the file directly in VLC. The same panel can move a title to the Trash.
* **Safe suggestions:** `lazy-suggest` verifies recommendations against TMDB to filter out hallucinations before appending them to `WATCHLIST.md`.
* **Never destructive:** Files are never moved or renamed. Deletes go to the Trash, and `suggest-renames` only prints what it would do.
* **State tracking:** Tick the boxes in `CONTENTS.md` (or `WATCHLIST.md`) to mark films as watched; the ticks survive regeneration.

`lazy-catalog --help` lists the rest.
