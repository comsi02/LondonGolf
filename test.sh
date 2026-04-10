#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Activate venv if present
if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
python londonGolfBook.py -d yes -t pro_song &
#python londonGolfBook.py -d yes -t pro_yh &
wait
