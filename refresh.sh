#!/usr/bin/env bash
#
# Pull the latest listening from Last.fm and extend the broadcast schedule.
#
#   ./refresh.sh
#
# Safe to run whenever. Slots that have already aired are frozen; only the
# future is rebuilt, and new records join the queue of things not yet played.
# Nothing is published until you commit and push.
#
# The schedule runs 180 days ahead, three records a day. Run this every month or two and records
# trickle in; leave it and the station eventually starts repeating itself,
# which is the quiet failure mode - it never breaks, it just goes stale.

set -euo pipefail
cd "$(dirname "$0")"

KEY=~/.lastfm-key
USER=greggorrr

# The filters, and why each number is what it is, are in CLAUDE.md.
MIN_PLAYS_PER_TRACK=1
MIN_TRACKS=3
MAX_LISTENERS=100000
GENRE_FAME_PCT=0

if [ ! -f "$KEY" ]; then
  echo "No Last.fm API key at $KEY"
  echo "Make one at https://www.last.fm/api/account/create, then:"
  echo "  echo 'YOUR_KEY' > $KEY && chmod 600 $KEY"
  exit 1
fi

command -v magick >/dev/null || {
  echo "ImageMagick not found - sleeves can't be converted. brew install imagemagick"
  exit 1
}

before=$(python3 -c "import json;print(len(json.load(open('data/schedule.json'))['records']))" 2>/dev/null || echo 0)

echo
echo "1/5  albums ......... every release you've scrobbled, with play counts"
python3 tools/pull.py albums --user "$USER"

echo
echo "2/5  enrich ......... tracklists, durations and tags (cached; only new ones fetch)"
python3 tools/pull.py enrich --min 2

echo
echo "3/5  artists ........ artist-level tags, to fill gaps where an album has none"
python3 tools/pull.py artists

echo
echo "4/5  similar ........ who actually sits near whom, for the network graph"
python3 tools/pull.py similar

echo
echo "5/5  schedule ....... filter the pool and extend the broadcast"
python3 tools/schedule.py \
  --min-plays-per-track "$MIN_PLAYS_PER_TRACK" \
  --min-tracks "$MIN_TRACKS" \
  --max-listeners "$MAX_LISTENERS" \
  --genre-fame-pct "$GENRE_FAME_PCT"

echo
echo "     sleeves ........ artwork for anything newly scheduled"
python3 tools/art.py

after=$(python3 -c "import json;print(len(json.load(open('data/schedule.json'))['records']))")
echo
echo "───────────────────────────────────────────────"
python3 - <<'PY'
import json, subprocess
d = json.load(open("data/schedule.json"))
import sys
sys.path.insert(0, "tools")
from schedule import now_block, SEGMENTS
ahead = len(d["slots"]) - 1 - now_block(SEGMENTS)
per_day = 24 // SEGMENTS[-1][1]
print("  %d records in the pool, %d days scheduled ahead, a full rotation every %d days"
      % (len(d["records"]), ahead // per_day, len(d["records"]) // per_day))
diff = subprocess.run(["git", "diff", "--stat", "--", "data/", "art/"],
                      capture_output=True, text=True).stdout.strip()
print("  " + (diff.splitlines()[-1].strip() if diff else "no files changed"))
PY

if [ "$after" -gt "$before" ]; then
  echo "  $((after - before)) new record(s) since last time:"
  python3 - <<'PY'
import json, subprocess
old = subprocess.run(["git", "show", "HEAD:data/schedule.json"],
                     capture_output=True, text=True).stdout
try:
    seen = {(r["artist"], r["release"]) for r in json.loads(old)["records"]}
except Exception:
    seen = set()
for r in json.load(open("data/schedule.json"))["records"]:
    if (r["artist"], r["release"]) not in seen:
        print("    %s — %s" % (r["artist"], r["release"]))
PY
else
  echo "  No new records qualified. Something has to be played through at least"
  echo "  once, have 3+ tracks, be electronic-tagged, sit under 100k listeners"
  echo "  and have sleeve art."
fi

echo "───────────────────────────────────────────────"
echo
echo "Nothing is live yet. Review, then commit and push to publish:"
echo "  git add -A && git commit -m 'Refresh the pool' && git push"
echo
