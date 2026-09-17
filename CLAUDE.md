# QuietBroadcast

Three records a day, drawn from Gregor's Last.fm library. Static HTML, no
build step, no dependencies, no tracking. `README.md` is the public face — keep it
short. This file is the working document.

Live at **quietbroadcast.com** — GitHub Pages from `main` on `polyconic/quietbroadcast`,
`CNAME` in the repo root. **Pushing to `main` publishes**; there is no staging.

**If HTTPS ever stalls:** setting the custom domain in Pages settings *before* DNS points
at GitHub makes the certificate request fail, and GitHub sticks in that failed state
rather than retrying. Removing the custom domain, waiting, and re-adding it forces a
fresh attempt. DNS is four A records to 185.199.108–111.153 plus `www` CNAME to
`polyconic.github.io`, and there is deliberately no CAA record — a CAA that omits
Let's Encrypt would block issuance silently.

## The mechanic

The cadence comes in **eras**, listed as `SEGMENTS` in `tools/schedule.py` and written
into `schedule.json` as `segments`:

```
2026-09-10  6h   four a day   (blocks 0–31)
2026-09-18  8h   three a day  (block 32 onward: 00:00, 08:00, 16:00)
```

Blocks are numbered straight through the eras, and `record = records[slots[block]]`.
**To change the cadence, append an era starting at a future Chicago midnight — never
edit an existing one.** Changing a number in place renumbers every slot that has
already aired: the Log would put records on the wrong days and the live record would
jump mid-slot. `schedule.py` refuses a new era dated today or earlier for that reason.
The switch to three a day was checked by comparing every aired slot before and after.

**Station time is Chicago**, and a block is a Chicago calendar day plus a slot within
it — deliberately *not* arithmetic from a fixed instant. That way a local day keeps its
full count of slots, including the 23- and 25-hour days when the clocks move; fixed
arithmetic drifts an hour twice a year. `tz` is written into `schedule.json` and both
pages read it from there. `tools/schedule.py` uses `zoneinfo` and the pages use
`Intl.DateTimeFormat` with `formatToParts`, and **the two must agree on the block
number** or frozen slots land wrong. Display dates derive from the block number itself,
so nothing converts back. The countdown binary-searches the next boundary rather than
adding a fixed number of hours, which is what makes it correct across a DST change and
across an era change.

**Past the end of the written schedule the pages replay it** (`slots[block % length]`)
rather than erroring. Before this they threw "the schedule has run out", so a long gap
between refreshes would have taken the front page down, not just made it repeat.

Everyone gets the same record at the same moment, and nothing is stored in the browser.

## The one rule that matters

**`data/schedule.json` is written down, not computed.** `records` is **append-only**
and `slots` holds indexes into it. That is what lets the library grow without
disturbing anything that has already aired.

An earlier version recomputed the past from a clock-seeded shuffle over the pool.
It was tidier and completely wrong: changing the pool size reshuffled every past
slot, so the library could never grow. Don't reintroduce it.

`tools/schedule.py` freezes every slot up to the current block and rebuilds only
what comes after. Records that have never aired get priority; when that queue runs
dry the whole live pool reshuffles, so everything airs once before anything repeats.

**Never reorder or delete entries in `records`.** Slots are positional indexes into
it. Dropping a record from the filters is fine — it just stops being scheduled —
but removing it from the array corrupts every past slot.

## Rebuilding the pool

```bash
./refresh.sh
```

That is the whole thing — it runs the four stages, fetches sleeves, and prints which
records are new. The filter values live at the top of the script. Safe to run any time:
aired slots are frozen, only the future is rebuilt, and nothing publishes until you
commit and push.

**Nothing is automatic.** The site never calls Last.fm — the key would end up in the
browser — so new scrobbles do nothing until `refresh.sh` is run by hand. The schedule
holds 180 days, and the failure mode is quiet: it doesn't break when it runs out, it
just starts repeating. Run it every month or two.

The API key lives at `~/.lastfm-key` (mode 600) and is read only by `tools/pull.py`
on Gregor's machine. **It must never enter the repo or any client-side JS** — the site
makes zero API calls at runtime and should stay that way.

## The filters, and why each exists

| Filter | Default | Why |
|---|---|---|
| `--min-plays-per-track` | 1.0 | A Last.fm "play" is one **track** scrobble, so raw play count is biased against short EPs. Dividing by tracklist length gives complete listens. |
| `--min-tracks` | 3 | A record, not a single. Without it 419 of 1,105 entries were 1-track singles. |
| `--max-listeners` | 100000 | Fame ceiling. Discovery means not airing what everyone has heard. |
| `--genre-fame-pct` | 0 | Trims each genre's canon. Only useful on a multi-genre pool; redundant now the pool is electronic-only. |
| `--max-minutes` | 120 | Above this it is a box set, not a record. |
| `--allow-artless` | off | By default a record with no sleeve is dropped — the front page is mostly the sleeve. |
| `--all-genres` | off | Turns off the electronic-adjacent gate. |

`ELECTRONIC_TAGS` is the gate. Trip-hop and sample-based instrumental beats are in
(same machines); vocal rap and guitar music are out unless also tagged electronic.
Two judgment calls worth knowing: disco and dub are in, because nu-disco and dub
techno are entangled with the rest; and Gorillaz and Fishmans get through on their
electronic tags, which is "adjacent" behaving as asked.

`EXCLUDE_ARTISTS` keeps records off the station entirely: Gregor's own (`gregor egan`)
and `goose`, which slipped the electronic gate on a stray tag. Exact artist match.

**Artless records are dropped.** `schedule.py` imports `url_map()` from `art.py` to see
what the local cache has a sleeve URL for, and also reads `data/art_failed.json` — the
handful whose URLs 404 on every size — so both are gone before scheduling. Run
`tools/art.py` after `tools/schedule.py`; if it records new failures, run the scheduler
once more to drop them. `art.py` also prunes sleeves nothing references any more.

**`Various Artists` is not an artist.** Compilations still air, but `NOT_AN_ARTIST` in
`log.html` keeps the label out of the artist count, the "keeps coming back" list and
the network graph.

## Last.fm quirks — do not rediscover these

- A **listener** is a distinct user; a **play** is a scrobble. The fame ceiling uses
  `listeners`, the taste filter uses Gregor's own `plays`. Global `playcount` is unused.
- Loved tracks are useless as a signal — he has 27.
- `duration` comes back as an int sometimes and a string others. `tags` is an empty
  **string**, not an empty object, when absent. Shape-check everything; `listify()`
  in `pull.py` exists for this.
- 434 albums have no tracklist at all and can't be scored.
- Album tags are patchy. `tools/pull.py artists` fetches artist-level tags as a
  fallback and filled 182 of 183 gaps. Only tags with 15+ votes are accepted.
- Durations under 60s per track are wrong, not short — `clean()` blanks the number
  and keeps the record rather than dropping a good album over bad metadata.
- **Last.fm often times only *some* of a record's tracks.** Summing those is confidently
  wrong — Contract Labour read "four minutes" for a 28-minute record because one of its
  four tracks had a duration. A runtime is only kept when *every* track is timed;
  otherwise it is suppressed. 51 of 319 records show no runtime for this reason, and
  `track.getInfo` does not fill the gaps — the data simply isn't there.
- **Tags are crowd-written and often wrong, not merely vague.** `album.getInfo` returns
  them unranked with no counts; `album.getTopTags` has counts but the crowd itself ranked
  Contract Labour ambient(100), electronica(100) above Acid(66), techno(23). No endpoint
  fixes that. `tidy_tags()` drops what isn't a genre (years, "loved", "catchy", radio
  slugs, the artist's own name, free-text phrases) and sinks uninformative umbrellas
  like "electronic" — on an electronic-only station that word says nothing. Where
  Last.fm is simply wrong, `data/tag_overrides.json` maps `"Artist - Release"` to a tag
  list and wins outright. That file is curation, not a workaround; expect it to grow.
- **The crowd spells the same genre several ways.** `oldschool techno` and
  `oldschool-techno` were appearing side by side on the same record, and the tag cloud
  counted them separately. `canon_tag()` folds `&`→`and`, turns `-_/` into spaces and
  collapses whitespace, then `tidy_tags()` dedupes. **`ELECTRONIC_TAGS` and
  `GENRE_FAMILIES` are folded through the same function when compared** — without that,
  normalizing the tags would silently drop `lo-fi`, `2-step` and friends out of the pool,
  because the gate would be matching hyphenated spellings that no longer exist.

## Pages

| File | What it is |
|---|---|
| `index.html` | The slot. Sleeve, one record, its tracklist, where to get it. |
| `log.html` | Everything aired, in prose; the artist network; a journal of recent days. |
| `404.html` | Off air. GitHub Pages serves this for any unknown path. `noindex`. |
| `tools/art.py` | Sleeve art from the local cache into `art/`. |

Pages move with **cross-document view transitions** — `@view-transition{navigation:auto}`
plus `view-transition-name:masthead` on `.top`, so the wordmark holds still while the rest
crossfades. No JS, no library. Browsers without it get a plain fade via
`@supports not (view-transition-name:none)`, and both paths are disabled under
`prefers-reduced-motion`. Any new page needs that same block or it will jump-cut.

**Social and search metadata** lives in each page's head: Open Graph, Twitter card,
canonical, and WebSite JSON-LD on the front page, with `robots.txt` and `sitemap.xml` in
the root. Images live in `assets/` — `assets/og.png` is `assets/meta.png` padded to
978x512 (exactly 1.91:1), since the raw 630x512 gets letterboxed or cropped by iMessage
and Twitter. Favicons are generated from `assets/FAVICON.png`; the 180px apple-touch icon
is flattened onto black because iOS ignores transparency and fringes it. **`favicon.ico`
stays at the repo root on purpose** — browsers, crawlers and link previewers probe
`/favicon.ico` directly without reading the `<link>` tags. `art/` is separate: that's
record sleeves, referenced by relative path from `schedule.json`.

The network graph is a hand-rolled force simulation on canvas — no library. **Edges come
from `artist.getSimilar` (`data/similar.json`), never from tags.** Tag overlap was the
first attempt and it was worthless: nearly every record here is tagged "electronic", so
it drew lines between Felly and Cut Chemist, and Orbe and Mouse on Mars. Listening data
gets it right — Orbe joins Luigi Tozzi at 0.64 and neither bad pair connects at all.
Similarity isn't symmetrical, so the two directions are max'd; the floor is 0.2 match.
An artist with no link inside the pool correctly floats alone — don't "fix" that.

The node detail deliberately lists only the records, **no genre line**. It used to say
"Mostly techno, sludge, post-metal" about Orbe, from the same tags that can't be trusted.
It pre-runs 600 steps so it opens settled. Three things it needs to stay readable, all
of which it got wrong first time round:

- **Repulsion must have a cutoff** (`spacing*2.2`). Applied to every pair it sums
  outward, inflating the layout until the walls stop it and every node ends up lined
  along the edges.
- **Hard separation after integration**, so circles never overlap, plus a soft inward
  nudge near the walls rather than only a clamp — a clamp alone makes nodes slide along
  the edge and queue up.
- **Labels are placed biggest-first and skipped on collision**, trying right, left,
  above, below. Without that, names print straight through one another. Hover or
  selection forces a label through with a background plate.

Dragging works on touch as well as mouse. `touchstart` only grabs when the finger lands
on a node, and `touchmove` is registered `{passive:false}` so it can `preventDefault`
**only while a node is held** — a canvas this tall that swallowed every swipe would trap
the page scroll. The caption says "tap" instead of "click" when `(hover:none)` matches.

`?preview=N` renders slot N on either page. Undocumented dev affordance, not a feature.

## Voice and look

The pages are meant to read like the back of a sleeve, not an instrument panel.
Gregor asked for "organic, less dashboard" after a first pass that was all
monospace caps, pills, bordered buttons, stat tiles and bar charts. So:

- **System serif** for nearly everything (`--serif`: Iowan Old Style / Palatino /
  Georgia — nothing is fetched). Sans only for artist names and durations.
- **Prose where there were labels.** "Four tracks, twenty-two minutes — techno, dub
  techno." Small numbers are spelled out (`words()`). The countdown is a sentence
  that updates every 30s, not a ticking clock.
- **Slots are named**, not numbered. Three a day: *overnight* (00:00), *during the
  day* (08:00, "daytime" in the Log's journal), *evening* (16:00). The four-a-day era
  keeps its own names — *in the small hours*, *morning*, *afternoon*, *evening* — so the
  Log's older days still read correctly. `slotName()` picks by era. Chicago time.
- The log's stats are a paragraph, tags are a weighted type cloud, recent slots are
  a journal grouped by day. No tiles, no bars.
- Tracklist uses dotted leaders and CSS counters — no hairlines, no mono numbers.

**Color:** the chrome is grayscale; `--accent` `#e02b1d` (the vault's red) is only the
on-air lamp and "on air now". Everything else colorful on the page is **sampled from
the sleeve currently on air** — `tint()` averages the image (weighted toward saturated
pixels, pushed away from gray) and sets `--glow`, which feeds two slow-drifting blurred
blobs and the sleeve's shadow. The art is served from this origin, so the canvas read
is untainted. A near-gray sleeve still yields something; a missing sleeve leaves the
default gray.

Film grain is an inline SVG turbulence, ~4.5% opacity. All motion respects
`prefers-reduced-motion`.

**Sleeves** live in `art/` via `tools/art.py` — it reads the local API cache and makes
no API calls, downloads 12-wide, and converts with ImageMagick to **webp q85, capped at
800px** (the sleeve renders ~360px, so 800 covers retina; `>` never upscales).

Two things about Last.fm images worth keeping: `mega` and `extralarge` are the *same*
300px file, but **stripping the size segment from the URL** (`/i/u/300x300/x.png` →
`/i/u/x.png`) returns the original, usually 600–1400px. And some sizes 404 per release,
so `candidates()` keeps the whole ladder as fallbacks. Records with no usable sleeve are
dropped from the pool entirely.

## Licensing and attribution

Last.fm's API terms grant a **non-commercial** license to copy, publish and distribute
their data, conditional on crediting them. Two things follow, and neither should be
quietly dropped:

- **"Data from Last.fm" links in every footer.** This is required, not decorative.
  Clause 2.7 also wants album links pointing at the specific catalog page, which the
  per-record Last.fm link already does.
- **No Last.fm logo anywhere, deliberately.** Clause 2.7 demands one of their
  "powered by AudioScrobbler" buttons from `last.fm/resources` — that page is a 404 and
  the branding is long retired, so the clause is unfulfillable as written. Clause 7.1
  requires *prior written approval* for any use of their marks, so plain text is strictly
  safer than a logo. Don't add one.
- **The license dies the moment the site earns money.** Ads, a tip jar, anything — that
  needs a commercial agreement from `partners@last.fm` first.
- There is a **100 MB "Reasonable Usage Cap"** on Last.fm data stored or published.
  The repo publishes ~48 MB; `data/.cache` is another ~94 MB locally. The cache is
  disposable — `refresh.sh` refetches what it needs — so prune it if this ever matters.

**Sleeve art is the real exposure, and Last.fm's license does not cover it.** Labels and
designers own those covers; Last.fm can only license what it holds. The fair-use posture
is reasonable — non-commercial, editorial, 800px cap, and every entry links out to buy —
but it rests on staying non-commercial and on being reachable, which is what the
`gregor.art@pm.me` contact link is for. Keep it.

Every footer also says **"Artwork belongs to its labels and artists"**. That notice
grants nothing and is not a defence — it disclaims ownership and shows good faith, which
is largely what decides whether a label sends a friendly email or something worse. The
colophon is deliberately **inline text, not flex**: as a flex row it wrapped mid-phrase
into a ragged grid on narrow screens, and a `white-space:nowrap` "fix" then pushed the
page into horizontal scroll on a 375px screen.

## Theme

Shared `localStorage` key `theme`, `light`/`dark`, dark by default, same as the other
sites. Light is warm paper (`#efece6`), not white. Reads and writes are wrapped in
try/catch — `localStorage` throws on `file:` and `data:` origins.

## Local preview

```bash
python3 -m http.server 8733 --directory .
```
