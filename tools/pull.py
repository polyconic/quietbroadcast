#!/usr/bin/env python3
"""Pull a Last.fm library into static JSON. Run once, locally; the key never ships.

  python3 tools/pull.py albums              # stage 1 — the pool, with playcounts
  python3 tools/pull.py enrich --min 12     # stage 2 — tags, tracklists, durations
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request

API = "https://ws.audioscrobbler.com/2.0/"
KEY_FILE = os.path.expanduser("~/.lastfm-key")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, ".cache")


def key():
    if not os.path.exists(KEY_FILE):
        sys.exit("No key at ~/.lastfm-key — see add.html or the README.")
    k = open(KEY_FILE).read().strip()
    if len(k) < 20:
        sys.exit("That key looks too short.")
    return k


def call(method, retries=4, **params):
    params.update(method=method, api_key=key(), format="json")
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "QuietBroadcast/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError("lastfm error %s: %s" % (d["error"], d.get("message")))
            return d
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def albums(user):
    out, page, total = [], 1, None
    while True:
        d = call("user.getTopAlbums", user=user, period="overall", limit=1000, page=page)
        blk = d["topalbums"]
        attr = blk["@attr"]
        total = int(attr["totalPages"])
        for a in blk["album"]:
            out.append({
                "artist": a["artist"]["name"],
                "release": a["name"],
                "plays": int(a["playcount"]),
                "mbid": a.get("mbid") or "",
                "url": a.get("url") or "",
            })
        print("  page %d/%d — %d albums" % (page, total, len(out)), flush=True)
        if page >= total:
            break
        page += 1
        time.sleep(0.25)
    return out


def histogram(rows):
    buckets = [(1, 1), (2, 4), (5, 9), (10, 19), (20, 49), (50, 99), (100, 10 ** 9)]
    print("\n  plays        albums   cumulative (>= low)")
    for lo, hi in buckets:
        n = sum(1 for r in rows if lo <= r["plays"] <= hi)
        c = sum(1 for r in rows if r["plays"] >= lo)
        label = "%d+" % lo if hi > 10 ** 8 else "%d-%d" % (lo, hi)
        print("  %-10s %7d   %7d" % (label, n, c))


def listify(node, key):
    """Last.fm gives a list, a bare dict, an empty string or nothing at all."""
    if not isinstance(node, dict):
        return []
    v = node.get(key)
    if isinstance(v, dict):
        return [v]
    return v if isinstance(v, list) else []


def secs(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def enrich(rows, minplays):
    os.makedirs(CACHE, exist_ok=True)
    pool = [r for r in rows if r["plays"] >= minplays]
    print("  enriching %d albums (>= %d plays)" % (len(pool), minplays), flush=True)
    done = []
    for i, r in enumerate(pool, 1):
        slug = urllib.parse.quote((r["artist"] + "--" + r["release"]).replace("/", "_"), safe="")[:180]
        path = os.path.join(CACHE, slug + ".json")
        if os.path.exists(path):
            info = json.load(open(path))
        else:
            try:
                info = call("album.getInfo", artist=r["artist"], album=r["release"], autocorrect=1)
            except Exception as e:
                print("    ! %s — %s (%s)" % (r["artist"], r["release"], e), flush=True)
                info = {}
            json.dump(info, open(path, "w"))
            time.sleep(0.22)
        a = info.get("album") or {}
        tracks = listify(a.get("tracks"), "track")
        tags = listify(a.get("tags"), "tag")
        r = dict(r)
        r["tags"] = [t["name"].lower() for t in tags if isinstance(t, dict) and t.get("name")][:6]
        r["tracks"] = [{"title": t.get("name") or "", "secs": secs(t.get("duration"))}
                       for t in tracks if isinstance(t, dict)]
        r["secs"] = sum(t["secs"] for t in r["tracks"])
        r["listeners"] = int(a.get("listeners") or 0)
        done.append(r)
        if i % 25 == 0:
            print("    %d/%d" % (i, len(pool)), flush=True)
    return done


def artist_tags(rows):
    """Album tags are patchy; artist tags fill the gaps."""
    os.makedirs(CACHE, exist_ok=True)
    names = sorted({r["artist"] for r in rows})
    print("  fetching tags for %d artists" % len(names), flush=True)
    out = {}
    for i, nm in enumerate(names, 1):
        slug = "artist--" + urllib.parse.quote(nm.replace("/", "_"), safe="")[:170]
        path = os.path.join(CACHE, slug + ".json")
        if os.path.exists(path):
            info = json.load(open(path))
        else:
            try:
                info = call("artist.getTopTags", artist=nm, autocorrect=1)
            except Exception as e:
                print("    ! %s (%s)" % (nm, e), flush=True)
                info = {}
            json.dump(info, open(path, "w"))
            time.sleep(0.22)
        tags = listify(info.get("toptags"), "tag")
        # only tags a real share of listeners agree on
        out[nm] = [t["name"].lower() for t in tags
                   if isinstance(t, dict) and int(t.get("count") or 0) >= 15][:8]
        if i % 100 == 0:
            print("    %d/%d" % (i, len(names)), flush=True)
    return out


def similar_artists(rows):
    """Who actually sits near whom, from listening behavior rather than tags.
    Tag overlap is worthless here - nearly everything in the pool is tagged
    electronic, so it linked artists with nothing to do with each other."""
    os.makedirs(CACHE, exist_ok=True)
    names = sorted({r["artist"] for r in rows})
    print("  fetching similar artists for %d names" % len(names), flush=True)
    out = {}
    for i, nm in enumerate(names, 1):
        slug = "similar--" + urllib.parse.quote(nm.replace("/", "_"), safe="")[:170]
        path = os.path.join(CACHE, slug + ".json")
        if os.path.exists(path):
            info = json.load(open(path))
        else:
            try:
                info = call("artist.getSimilar", artist=nm, autocorrect=1, limit=40)
            except Exception as e:
                print("    ! %s (%s)" % (nm, e), flush=True)
                info = {}
            json.dump(info, open(path, "w"))
            time.sleep(0.22)
        sim = listify(info.get("similarartists"), "artist")
        pairs = []
        for x in sim:
            if not isinstance(x, dict) or not x.get("name"):
                continue
            try:
                m = float(x.get("match") or 0)
            except (TypeError, ValueError):
                m = 0.0
            if m > 0:
                pairs.append([x["name"], round(m, 3)])
        out[nm] = pairs
        if i % 100 == 0:
            print("    %d/%d" % (i, len(names)), flush=True)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["albums", "enrich", "artists", "similar"])
    p.add_argument("--user", default="greggorrr")
    p.add_argument("--min", type=int, default=10)
    a = p.parse_args()
    os.makedirs(DATA, exist_ok=True)
    raw = os.path.join(DATA, "albums.raw.json")

    if a.stage == "albums":
        print("pulling top albums for %s" % a.user, flush=True)
        rows = albums(a.user)
        json.dump(rows, open(raw, "w"), indent=1, ensure_ascii=False)
        print("\n  %d albums -> data/albums.raw.json" % len(rows))
        histogram(rows)
        print("\n  then: python3 tools/pull.py enrich --min N")
    elif a.stage == "similar":
        src = os.path.join(DATA, "albums.json")
        if not os.path.exists(src):
            sys.exit("Run the enrich stage first.")
        sim = similar_artists(json.load(open(src)))
        json.dump(sim, open(os.path.join(DATA, "similar.json"), "w"),
                  indent=0, ensure_ascii=False)
        n = sum(1 for v in sim.values() if v)
        print("\n  %d of %d artists have similarity data -> data/similar.json"
              % (n, len(sim)))
    elif a.stage == "artists":
        src = os.path.join(DATA, "albums.json")
        if not os.path.exists(src):
            sys.exit("Run the enrich stage first.")
        tags = artist_tags(json.load(open(src)))
        json.dump(tags, open(os.path.join(DATA, "artist_tags.json"), "w"),
                  indent=0, ensure_ascii=False)
        n = sum(1 for v in tags.values() if v)
        print("\n  %d of %d artists have tags -> data/artist_tags.json" % (n, len(tags)))
    else:
        if not os.path.exists(raw):
            sys.exit("Run the albums stage first.")
        rows = json.load(open(raw))
        out = enrich(rows, a.min)
        json.dump(out, open(os.path.join(DATA, "albums.json"), "w"), indent=1, ensure_ascii=False)
        print("\n  %d albums -> data/albums.json" % len(out))


if __name__ == "__main__":
    main()
