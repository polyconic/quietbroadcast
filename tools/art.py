#!/usr/bin/env python3
"""Pull sleeve art for every scheduled record into art/, and record the filename
on each entry in data/schedule.json.

The URLs come out of the local album.getInfo cache, so this makes no Last.fm API
calls. Images are downloaded once and served from the repo - the site never asks
a third party for anything at runtime.
"""
import glob, hashlib, json, os, re, shutil, subprocess, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, ".cache")
ART = os.path.join(HERE, "art")
SCHED = os.path.join(DATA, "schedule.json")

# Last.fm's placeholder star, served when a release has no real sleeve.
PLACEHOLDER = "2a96cbd8b46e442fc41c2b86b821562f"
HAVE_MAGICK = False
ORDER = ("mega", "extralarge", "large", "medium")
SIZE_SEG = re.compile(r"(/i/u/)[^/]+/")
WEBP_Q = "85"          # same setting as the portfolio
MAX_PX = "800x800>"    # the sleeve renders ~360px; 800 covers retina, ">" never upscales


def candidates(images):
    """Largest first. Dropping the size segment gives the original - usually 600px,
    against 300 for `mega`. Last.fm 404s some sizes, so keep the rest as fallbacks
    rather than giving up on the sleeve."""
    by = {i.get("size"): i.get("#text") for i in images if i.get("#text")}
    out = []
    for s in ORDER:
        u = by.get(s)
        if not u or PLACEHOLDER in u:
            continue
        original = SIZE_SEG.sub(r"\1", u)
        for cand in (original, u):
            if cand not in out:
                out.append(cand)
    return out


def url_map(stores=True):
    """(artist, release) -> sleeve URLs, largest first. Last.fm's own image wins;
    with stores=True, Deezer or Apple fill in where Last.fm has none."""
    out = {}
    for f in glob.glob(os.path.join(CACHE, "*.json")):
        if os.path.basename(f).startswith(("artist--", "similar--", "deezer--")):
            continue
        try:
            a = (json.load(open(f)).get("album") or {})
        except Exception:
            continue
        if not a.get("name"):
            continue
        us = candidates(a.get("image") or [])
        if us:
            out[(a.get("artist", ""), a["name"])] = us
    if stores:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from stores import cached
        for k, d in cached().items():
            if k not in out:
                us = [u for u in (d.get("cover"), d.get("cover_big")) if u]
                if us:
                    out[k] = us
    return out


def main():
    if not os.path.exists(SCHED):
        sys.exit("No data/schedule.json - run tools/schedule.py first.")
    sched = json.load(open(SCHED))
    urls = url_map()
    os.makedirs(ART, exist_ok=True)

    global HAVE_MAGICK
    HAVE_MAGICK = bool(shutil.which("magick"))
    if not HAVE_MAGICK:
        print("  (no imagemagick - sleeves stay in their original format)")

    jobs, miss = [], 0
    for r in sched["records"]:
        us = urls.get((r["artist"], r["release"]))
        if not us:
            r["art"] = ""
            miss += 1
            continue
        u = us[0]
        ext = os.path.splitext(u)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            ext = ".jpg"
        name = hashlib.sha1(u.encode()).hexdigest()[:16] + ".webp"
        r["art"] = "art/" + name
        if not os.path.exists(os.path.join(ART, name)):
            jobs.append((r, us, os.path.join(ART, name)))

    print("  %d sleeves to fetch (%d already local, %d have none)"
          % (len(jobs), len(sched["records"]) - len(jobs) - miss, miss), flush=True)

    failed = []

    def grab(job):
        r, us, path = job
        last = None
        tmp = path + ".src"
        for u in us:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "QuietBroadcast/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    blob = resp.read()
                if len(blob) < 500:
                    raise ValueError("suspiciously small")
                open(tmp, "wb").write(blob)
                if HAVE_MAGICK:
                    subprocess.run(["magick", tmp, "-resize", MAX_PX,
                                    "-quality", WEBP_Q,
                                    "-define", "webp:method=6", path],
                                   check=True, capture_output=True)
                    os.remove(tmp)
                else:
                    shutil.move(tmp, path)
                return
            except Exception as e:
                last = e
                if os.path.exists(tmp):
                    os.remove(tmp)
        failed.append((r, last))
        r["art"] = ""

    with ThreadPoolExecutor(max_workers=12) as pool:
        for i, _ in enumerate(pool.map(grab, jobs), 1):
            if i % 100 == 0:
                print("    %d/%d" % (i, len(jobs)), flush=True)

    failed_pairs = list(failed)
    for r, e in failed_pairs[:5]:
        print("    ! %s - %s (%s)" % (r["artist"], r["release"], e))
    fetched = len(jobs) - len(failed_pairs)
    failed = len(failed_pairs)

    fail_path = os.path.join(DATA, "art_failed.json")
    prior = []
    if os.path.exists(fail_path):
        prior = json.load(open(fail_path))
    dead = {tuple(x) for x in prior} | {(r["artist"], r["release"]) for r, _ in failed_pairs}
    json.dump(sorted(dead), open(fail_path, "w"), ensure_ascii=False, indent=0)

    json.dump(sched, open(SCHED, "w"), ensure_ascii=False, separators=(",", ":"))
    # drop sleeves nothing references any more (a record left the pool before airing)
    keep = {os.path.basename(r["art"]) for r in sched["records"] if r.get("art")}
    orphans = [f for f in os.listdir(ART) if f not in keep and not f.startswith(".")]
    for f in orphans:
        os.remove(os.path.join(ART, f))
    if orphans:
        print("  pruned %d unreferenced sleeves" % len(orphans))

    total = sum(os.path.getsize(os.path.join(ART, f)) for f in os.listdir(ART))
    withart = sum(1 for r in sched["records"] if r.get("art"))
    print("\n  %d of %d records have a sleeve (%d had none on Last.fm, %d failed)"
          % (withart, len(sched["records"]), miss, failed))
    print("  %d downloaded this run, art/ is %.1f MB" % (fetched, total / 1e6))


if __name__ == "__main__":
    main()
