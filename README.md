# London Golf Reservation System

Automated tee time booking for City of London golf courses (TeeItUp / Kenna API).

## Layout

| Path | Purpose |
|------|---------|
| `londonGolfBook.py` | CLI entry (calls `london_golf.cli.main`) |
| `london_golf/` | Application package (browser, API, schedule, config) |
| `common.py` | Legacy `getLogger` / `getConfig` shim |
| `example.yaml` | Copy to `londonGolfBook.yaml` and edit (real config is gitignored) |
| `scripts/mac/` | Optional macOS clamshell helpers (`clamshell-on.sh` / `clamshell-off.sh`) |

## Requirements

- Python 3.9+
- Google Chrome (Selenium Manager can fetch a matching ChromeDriver)
- Optional: Redis for shared deduplication cache; if Redis is unavailable, a local `tee_time_cache.json` is used

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### macOS notes

- Chrome: install from [Google Chrome](https://www.google.com/chrome/) or `brew install --cask google-chrome`.
- Clamshell (run with lid closed on battery): see `scripts/mac/clamshell-on.sh` (requires `sudo`).

### Linux (server / cron) notes

- Install Chrome/Chromium and system dependencies Selenium expects for your distro.
- Redis is optional; see `example.yaml` for host/port.

## Configuration

```bash
cp example.yaml londonGolfBook.yaml
# Edit londonGolfBook.yaml: authentication, schedule tasks, courses, optional redis
```

Environment overrides:

- `LONDON_GOLF_CONFIG` — absolute path to YAML config
- `LONDON_GOLF_LOG_STDERR=1` — also log to stderr (debugging)

`weekday` in each task may be a comma-separated string (`MON,TUE,...`) or a YAML list of day codes.

## Usage

```bash
source .venv/bin/activate
python londonGolfBook.py -d yes -t pro_song
```

Arguments:

| Flag | Meaning |
|------|---------|
| `-d yes` / `-d no` | Show browser vs headless |
| `-t NAME` | Task name under `schedule:` in YAML |
| `-c PATH` | Config file (default: `londonGolfBook.yaml` in repo root) |
| `--sequential` | Run schedule entries one after another in the main process (same session; avoids parallel API calls) |
| `--workers N` | Process pool size when not `--sequential` (default: CPU count) |

Example:

```bash
python londonGolfBook.py -d no -t pro_song --sequential
```

Module entry (equivalent):

```bash
python -m london_golf -d yes -t pro_song
# or
python -m london_golf.cli -d yes -t pro_song
```

## Development

```bash
pip install -r requirements-dev.txt
ruff check london_golf
ruff format london_golf
```

**Note:** `selenium-wire` pins an older `blinker` (see `requirements.txt`); upgrading `blinker` to 1.8+ breaks imports until upstream fixes compatibility.

## Troubleshooting

- **Chrome / driver**: Update Chrome; Selenium 4 resolves drivers automatically in many setups.
- **Redis**: If Redis is down, the app falls back to file cache (see logs).
- **Parallel booking / session errors**: Try `--sequential` so only one worker uses the cart/login session at a time.

## References

- [Selenium Python API](https://www.selenium.dev/selenium/docs/api/py/api.html)
- [selenium-wire](https://pypi.org/project/selenium-wire/)
- [Tee times API example](https://phx-api-be-east-1b.kenna.io/v2/tee-times?date=2023-07-01&facilityIds=9710)
