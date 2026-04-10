# London Golf Reservation System

Batch tool that automates tee-time booking for City of London golf courses via TeeItUp / Kenna.

## What it does

1. Signs in with **Chrome** using your **YAML** config and captures session and shopping-cart identifiers.
2. Queries **Kenna** for tee times matching the configured date, course(s), and time window.
3. When a slot matches, calls the **lock** then **cart** APIs to hold the tee time.
4. Completes **checkout / confirm reservation** in the browser (`set_reservation_with_retry`).

You can run headless (`-d no`) or with a visible browser (`-d yes`). If a task has multiple schedule rows, workers can poll the API in parallel (default worker count: number of CPUs).

## Layout

| Path | Purpose |
|------|---------|
| `londonGolfBook.py` | Entry point; calls `london_golf.cli.main` |
| `london_golf/` | Application package (API, browser, schedule, config, etc.) |
| `example.yaml` | Sample config—copy to `londonGolfBook.yaml` and edit (real configs are usually gitignored) |
| `common.py` | Legacy shim for `getLogger` / `getConfig` |
| `scripts/mac/` | Optional macOS helpers (`clamshell-on.sh` / `clamshell-off.sh`) |

## Requirements

- Python 3.9+
- Google Chrome (Selenium 4 usually resolves a matching ChromeDriver)
- Optional: Redis for shared deduplication cache; if Redis is unavailable, a local `tee_time_cache.json` (and similar) is used

## Install

### pip + venv

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### uv (optional)

```bash
uv sync
```

## Configuration

```bash
cp example.yaml londonGolfBook.yaml
# Edit londonGolfBook.yaml: course, authentication, schedule, optional redis
```

- **`course`**: Per course code, facility `code` and display `name`
- **`authentication`**: Named login bundles (e.g. `userinfo1`)
- **`redis`**: Optional host and port
- **`schedule.<taskName>`**: Booking rules. Two shapes are supported:
  - **Recommended (nested):** `auth: <key in authentication>` plus `tasks: [ { weekday, start_time, course, ... }, ... ]`
  - **Legacy:** `schedule.<taskName>` is a bare list of rows, with credentials under `authentication.<taskName>`

`weekday` may be a comma-separated string (`MON,TUE,...`) or a YAML list (`[MON, TUE]`).  
`course` may be a list of course codes or a single string (normalized to a one-element list).

## Environment variables

| Variable | Meaning |
|----------|---------|
| `LONDON_GOLF_CONFIG` | Absolute path to the YAML config file |
| `LONDON_GOLF_LOG_STDERR=1` | Also write logs to **stderr** (in addition to `logs/`; useful for debugging) |

## Usage

Activate the virtualenv, then pass **display mode** (`-d`) and **task name** (`-t`); both are required.

```bash
source .venv/bin/activate
python londonGolfBook.py -d yes -t pro_song
```

### CLI flags

| Flag | Meaning |
|------|---------|
| `-d yes` / `-d no` | `yes` = show browser window, `no` = headless |
| `-t NAME` | Task name defined under `schedule:` in YAML |
| `-c PATH` | Config file path (default: `londonGolfBook.yaml` in the repo root, or `LONDON_GOLF_CONFIG`) |
| `--sequential` | Run schedule rows **in-process, one after another** (fewer API/session conflicts) |
| `--workers N` | Pool size when not `--sequential` (default: CPU count) |

### Examples

```bash
# Headless, task pro_song
python londonGolfBook.py -d no -t pro_song

# API polling in a single session (sequential)
python londonGolfBook.py -d no -t pro_song --sequential
```

### Module entry (equivalent)

```bash
python -m london_golf -d yes -t pro_song
```

## Logging

By default logs go to `logs/londonGolfBook.log` with daily rotation. Lines prefixed with `[DEBUG]` are for detailed tracing.

## macOS notes

- Chrome: [Google Chrome](https://www.google.com/chrome/) or `brew install --cask google-chrome`
- Running with the lid closed on battery: see `scripts/mac/clamshell-on.sh` (may require `sudo`)

## Linux / cron

- Install Chrome/Chromium and system libraries Selenium depends on for your distro.
- Example `crontab`: `cd` to the project, activate the venv, then run `python londonGolfBook.py -d no -t <task>`.
- Prefer a **space** between `-d` and `no` in cron lines (`-d no`) so arguments are unambiguous.

## Development

```bash
pip install -r requirements-dev.txt
ruff check london_golf
ruff format london_golf
```

`selenium-wire` expects an older `blinker` range; see comments in `requirements.txt` / `pyproject.toml`.

## Troubleshooting

- **Chrome / driver:** Keep Chrome reasonably current; Selenium 4 often resolves drivers automatically.
- **Redis:** If Redis is unreachable, the app falls back to file cache (see logs).
- **Parallel booking / session errors:** Try `--sequential` so only one worker uses the cart/login session at a time.
- **urllib3 / LibreSSL warning (macOS):** Usually harmless; the CLI suppresses the noisy warning.

## References

- [Selenium Python API](https://www.selenium.dev/selenium/docs/api/py/api.html)
- [selenium-wire](https://pypi.org/project/selenium-wire/)
- [Tee times API example](https://phx-api-be-east-1b.kenna.io/v2/tee-times?date=2023-07-01&facilityIds=9710)
