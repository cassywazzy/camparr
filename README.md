# Camparr

Automatic Bandcamp downloader for Lidarr. Monitors your Lidarr wanted list and downloads free/name-your-price albums from Bandcamp in FLAC.

## How it works

1. Polls Lidarr's wanted/missing album list on a configurable interval
2. Searches Bandcamp for each wanted album using fuzzy artist + title matching
3. Checks if the matched album is free or name-your-price (minimum $0)
4. Downloads lossless FLAC via the actual Bandcamp purchase flow (not stream ripping)
5. Moves files into your Lidarr music library and triggers a rescan

Uses [free-bandcamp-downloader](https://github.com/7x11x13/free-bandcamp-downloader) under the hood.

## Quick Start

```yaml
services:
  camparr:
    image: ghcr.io/cass-sullivan/camparr:latest
    container_name: camparr
    restart: unless-stopped
    ports:
      - "8585:8585"
    volumes:
      - ./config:/config
      - /path/to/downloads:/downloads
      - /path/to/music:/library    # same path Lidarr uses as its root folder
    environment:
      - TZ=America/Los_Angeles
```

Create `config/config.yml`:

```yaml
lidarr:
  url: http://lidarr:8686
  api_key: your-lidarr-api-key

downloads:
  path: /downloads
  library_path: /library
```

The `/library` volume must point to the same directory as Lidarr's root folder. Camparr moves downloaded albums there and triggers a Lidarr rescan.

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `lidarr.url` | `http://lidarr:8686` | Lidarr base URL |
| `lidarr.api_key` | (required) | Lidarr API key (Settings > General) |
| `bandcamp.format` | `FLAC` | Download format: FLAC, WAV, AIFF, ALAC, 320MP3, V0MP3, Ogg, AAC |
| `bandcamp.search_cooldown_hours` | `168` | Hours before re-searching a failed album (7 days) |
| `bandcamp.match_threshold` | `80` | Minimum fuzzy match score (0-100) |
| `bandcamp.rate_limit_seconds` | `2` | Delay between Bandcamp requests |
| `downloads.path` | `/downloads` | Temporary download directory (container path) |
| `downloads.library_path` | (empty) | Lidarr music library path. Leave empty to keep files in downloads only |
| `polling.interval_seconds` | `300` | How often to poll Lidarr (seconds) |
| `healthchecks.ping_url` | (empty) | Healthchecks ping URL for dead-man's-switch monitoring |

Environment variable overrides: `LIDARR_URL`, `LIDARR_API_KEY`.

## Web UI

Access at `http://localhost:8585`. Shows:

- Polling status and cycle results
- Download history with status
- Search history with match results
- Manual download by URL

## How matching works

Camparr searches Bandcamp's internal API for `{artist} {album title}` and uses fuzzy string matching ([rapidfuzz](https://github.com/rapidfuzz/RapidFuzz)) to score results. The score is a weighted combination of artist similarity (40%) and album title similarity (60%), with normalization for case, diacritics, and parenthetical suffixes.

Only albums scoring above the `match_threshold` (default 80) are considered. Only free or name-your-price albums with a $0 minimum are downloaded.

## Import flow

When `library_path` is configured, Camparr:

1. Downloads to the temporary `/downloads` directory
2. Queries Lidarr for the artist's library path (preserving Lidarr's folder naming)
3. Moves files into `<library>/<Artist>/<Album>/`
4. Triggers a Lidarr library rescan
5. Cleans up the empty download directory

## Limitations

- Only downloads albums that are free or name-your-price with $0 minimum on Bandcamp
- Sequential downloads (one at a time) to respect Bandcamp's servers
- Disposable email service used for email-gated downloads may occasionally be unavailable

## License

MIT
