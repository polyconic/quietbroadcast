#!/usr/bin/env python3
"""Record stores fill what Last.fm lacks: sleeves for underground releases Last.fm
has no image for, and tracklists for records Gregor adds by hand. Deezer first, then
Apple's iTunes catalog, which has some small-label EPs Deezer doesn't. Both are
public APIs with no key.

Matches are strict - same artist and same title once "EP", bracketed notes and
punctuation are folded away - because a wrong sleeve is worse than none.
Results, misses included, are cached in data/.cache as deezer--*.json (the prefix
predates the Apple fallback).
"""
import json, os, re, threading, time, unicodedata, urllib.parse, urllib.request

API = "https://api.deezer.com"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, "data", ".cache")


def get(path, retries=4, **params):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "QuietBroadcast/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.load(r)
            if isinstance(d, dict) and "error" in d:
                # code 4 is their rate limit; anything else is a real answer
                if (d["error"] or {}).get("code") == 4 and attempt < retries - 1:
                    time.sleep(2 + 2 ** attempt)
                    continue
                return {}
            return d
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1 + 2 ** attempt)


def norm(s):
    # accents fold away but non-Latin letters survive, so Cyrillic or Japanese
    # names still compare instead of all collapsing to ""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).casefold()
    bare = re.sub(r"[\(\[][^)\]]*[\)\]]", " ", s)       # (Incl. Remix), [V35007]
    if re.sub(r"[\W_]+", "", bare):
        s = bare                                       # but "[KRTM]" is the whole name
    s = re.sub(r"\s*-\s*(ep|single)\s*$", " ", s)
    s = re.sub(r"\s+(ep|single)\s*$", " ", s)
    s = s.replace("&", "and")
    return re.sub(r"[\W_]+", "", s)


def same_artist(ours, theirs):
    if not norm(ours):
        return False
    if norm(ours) == norm(theirs):
        return True
    # "Dkult, Sandro Galli" against "Dkult", "Rrose & Luigi Tozzi" against "Luigi Tozzi"
    parts = lambda s: {norm(x) for x in re.split(r",|&| x | feat\.? | and ", s or "", flags=re.I)
                       if len(norm(x)) > 2}
    return bool(parts(ours) & parts(theirs))


def _pick(rows, artist, release):
    want = norm(release)
    if not want:
        return None
    for x in rows or []:
        if norm(x.get("title")) == want and same_artist(artist, (x.get("artist") or {}).get("name")):
            return x
    return None


def find(artist, release):
    hit = None
    for q in ('artist:"%s" album:"%s"' % (artist, release), "%s %s" % (artist, release)):
        hit = _pick(get("/search/album", q=q, limit=25).get("data"), artist, release)
        if hit:
            break
    if not hit:
        # last resort: walk the artist's own discography
        for a in (get("/search/artist", q=artist, limit=5).get("data") or [])[:2]:
            if not same_artist(artist, a.get("name")):
                continue
            albums = get("/artist/%d/albums" % a["id"], limit=300).get("data") or []
            for x in albums:
                x.setdefault("artist", {"name": a["name"]})
            hit = _pick(albums, artist, release)
            if hit:
                break
    if not hit:
        return apple(artist, release)
    full = get("/album/%d" % hit["id"])
    tracks = [{"title": t.get("title") or "", "secs": int(t.get("duration") or 0)}
              for t in ((full.get("tracks") or {}).get("data") or [])]
    return {
        "id": hit["id"],
        "artist": (full.get("artist") or {}).get("name") or "",
        "title": full.get("title") or hit.get("title") or "",
        "cover": full.get("cover_xl") or hit.get("cover_xl") or "",
        "cover_big": full.get("cover_big") or "",
        "link": full.get("link") or "",
        "tracks": tracks,
    }


_apple_lock = threading.Lock()
_apple_last = [0.0]


def apple(artist, release):
    def itunes(**params):
        url = "https://itunes.apple.com/" + params.pop("_") + "?" + urllib.parse.urlencode(params)
        # Apple allows roughly 20 calls a minute; space them out across threads
        with _apple_lock:
            wait = _apple_last[0] + 3.2 - time.time()
            if wait > 0:
                time.sleep(wait)
            _apple_last[0] = time.time()
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "QuietBroadcast/1.0"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.load(r).get("results") or []
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(1 + 2 ** attempt)
    rows = itunes(_="search", term=artist + " " + release, entity="album", limit=25)
    hit = None
    for x in rows:
        if norm(release) and norm(x.get("collectionName")) == norm(release) \
                and same_artist(artist, x.get("artistName")):
            hit = x
            break
    if not hit:
        return {}
    songs = [t for t in itunes(_="lookup", id=hit["collectionId"], entity="song")
             if t.get("wrapperType") == "track"]
    art = hit.get("artworkUrl100") or ""
    return {
        "id": "itunes:%d" % hit["collectionId"],
        "artist": hit.get("artistName") or "",
        "title": hit.get("collectionName") or "",
        # Apple serves any size from the same path; 1000 matches Deezer's cover_xl
        "cover": art.replace("100x100bb", "1000x1000bb"),
        "cover_big": art.replace("100x100bb", "600x600bb"),
        "link": hit.get("collectionViewUrl") or "",
        "tracks": [{"title": t.get("trackName") or "", "secs": int((t.get("trackTimeMillis") or 0) / 1000)}
                   for t in sorted(songs, key=lambda t: (t.get("discNumber") or 1, t.get("trackNumber") or 0))],
    }


def path_for(artist, release):
    slug = urllib.parse.quote((artist + "--" + release).replace("/", "_"), safe="")[:170]
    return os.path.join(CACHE, "deezer--" + slug + ".json")


def lookup(artist, release, fetch=True):
    """Cached. Returns {} when Deezer has no confident match."""
    p = path_for(artist, release)
    if os.path.exists(p):
        return json.load(open(p))
    if not fetch:
        return {}
    os.makedirs(CACHE, exist_ok=True)
    d = find(artist, release)
    d["for"] = [artist, release]
    json.dump(d, open(p, "w"), ensure_ascii=False)
    time.sleep(0.15)
    return d


def cached():
    """(artist, release) -> entry, for every confident match already cached."""
    out = {}
    if not os.path.isdir(CACHE):
        return out
    for f in os.listdir(CACHE):
        if f.startswith("deezer--"):
            try:
                d = json.load(open(os.path.join(CACHE, f)))
            except Exception:
                continue
            if d.get("id") and d.get("for"):
                out[tuple(d["for"])] = d
    return out
