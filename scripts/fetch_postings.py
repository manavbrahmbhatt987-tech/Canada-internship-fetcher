#!/usr/bin/env python3
"""Overnight internship fetcher for the Canada Internship Board.

Reads data/companies.json (company -> public ATS board id), pulls the
Greenhouse / Lever / Ashby public JSON APIs, keeps only intern/co-op/student
postings located in Canada, and writes data/postings.json +
data/meta.json. Runs on GitHub Actions overnight (Toronto time).

Stdlib only - no pip install needed.
"""

import json
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta

ROOT = __file__.rsplit("/scripts/", 1)[0]
COMPANIES = f"{ROOT}/data/companies.json"
POSTINGS = f"{ROOT}/data/postings.json"
META = f"{ROOT}/data/meta.json"

UA = {"User-Agent": "canada-internship-fetcher/1.0 (+github-actions)"}

# ---------------------------------------------------------------- filters

TITLE_RE = re.compile(r"\bintern(ship)?s?\b|\bco-?ops?\b|\bstudents?\b", re.I)

PROVINCES = [
    "ontario", "quebec", "british columbia", "alberta", "manitoba",
    "saskatchewan", "nova scotia", "new brunswick",
    "newfoundland and labrador", "newfoundland", "prince edward island",
    "yukon", "northwest territories", "nunavut",
]
PROV_ABBR = ["on", "qc", "bc", "ab", "mb", "sk", "ns", "nb", "nl", "pe",
             "yt", "nt", "nu"]
CITIES = [
    "toronto", "vancouver", "montreal", "calgary", "ottawa", "edmonton",
    "winnipeg", "mississauga", "hamilton", "kitchener", "waterloo",
    "london", "markham", "vaughan", "richmond hill", "richmond", "burnaby",
    "surrey", "victoria", "halifax", "quebec city", "laval", "gatineau",
    "saskatoon", "regina", "moncton", "fredericton", "kelowna", "guelph",
    "kingston", "windsor", "oakville", "burlington", "oshawa", "barrie",
    "st john", "saint john", "st john's", "saint john's", "red deer",
    "lethbridge", "kamloops", "nanaimo", "sherbrooke", "trois-rivieres",
    "trois-rivières", "longueuil", "brossard", "kanata", "ajax",
    "whitby", "pickering", "newmarket", "aurora", "brampton", "etobicoke",
    "scarborough", "north york", "thesis", "coquitlam", "langley",
    "abbotsford", "saanich", "nanaimo",
]
US_STATES = ["al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
             "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
             "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
             "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
             "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
             "dc"]


def is_canada_location(loc: str) -> bool:
    """Hard Canada-only gate: remote counts only if open to Canada."""
    if not loc:
        return False
    l = loc.lower()
    # Remote - Canada counts; Remote - US does not.
    if "remote" in l:
        if "canada" in l or re.search(r"\bca\b", l):
            return True
        if re.search(r"u\.?s\.?a?\.?|united states", l):
            return False
        return False  # bare "remote" with no country -> not verifiably Canada
    if "canada" in l:
        return True
    if any(p in l for p in PROVINCES):
        return True
    if re.search(r"[,\(]\s*(" + "|".join(PROV_ABBR) + r")\b", l):
        return True
    if any(re.search(r"\b" + re.escape(c) + r"\b", l) for c in CITIES):
        # make sure a US state tag doesn't override, e.g. "Portland, ON" is fine,
        # but "Austin, TX" must not sneak in via a city substring
        if re.search(r",\s*(" + "|".join(US_STATES) + r")\b", l):
            return False
        return True
    return False


SECTOR_KEYWORDS = [
    ("Cybersecurity", ["cyber", "security analyst", "infosec", "penetration"]),
    ("Hardware & Embedded", ["hardware", "firmware", "embedded", "fpga",
                             "rtl", "asic", "semiconductor", "pcb",
                             "validation engineer", "silicon"]),
    ("Data & AI", ["data", "machine learning", " ml ", "artificial intelligence",
                   "analytics", "scientist", "llm"]),
    ("Software & IT", ["software", "backend", "front end", "frontend",
                       "full stack", "fullstack", "mobile", "ios", "android",
                       "devops", "qa", "sdet", "site reliability", "platform",
                       "cloud", "sde"]),
    ("Product & Design", ["product", "ux", "ui ", "design", "designer"]),
    ("Business & Finance", ["finance", "banking", "account", "audit", "trader",
                            "investment", "consulting", "business analyst"]),
    ("Marketing & Communications", ["marketing", "communications", "social media",
                                    "content", "brand"]),
    ("Engineering", ["mechanical", "civil", "electrical", "chemical",
                     "engineering"]),
    ("Life Sciences & Healthcare", ["pharma", "biotech", "clinical", "health",
                                    "life sciences", "medical"]),
    ("Government & Policy", ["government", "policy", "public sector"]),
    ("Legal", ["legal", "law ", "counsel", "paralegal"]),
]


def guess_sector(title: str):
    t = f" {title.lower()} "
    for sector, kws in SECTOR_KEYWORDS:
        if any(k in t for k in kws):
            return sector
    return None


def clean_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:400] or None


# ------------------------------------------------------------------ fetch

def get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if attempt == 2:
                print(f"  !! failed {url}: {e}")
                return None
            time.sleep(2 * (attempt + 1))
    return None


def fetch_greenhouse(board: str):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
    if not d:
        return []
    out = []
    for j in d.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append({
            "title": j.get("title", ""),
            "location": loc,
            "url": j.get("absolute_url", ""),
            "posted_date": None,
            "description": None,
        })
    return out


def fetch_lever(board: str):
    d = get_json(f"https://api.lever.co/v0/postings/{board}")
    if not d:
        return []
    out = []
    for j in d:
        loc = j.get("location", "") or ""
        cats = j.get("categories") or {}
        if cats.get("location"):
            loc = cats["location"]
        ts = j.get("createdAt")
        posted = None
        if ts:
            posted = datetime.fromtimestamp(ts / 1000, tz=timezone.utc
                                            ).date().isoformat()
        out.append({
            "title": j.get("text", ""),
            "location": loc,
            "url": j.get("hostedUrl", ""),
            "posted_date": posted,
            "description": clean_html(j.get("descriptionPlain", "")),
        })
    return out


def fetch_ashby(board: str):
    from urllib.parse import quote
    d = get_json(
        f"https://api.ashbyhq.com/posting-api/job-board/{quote(board, safe='')}")
    if not d:
        return []
    out = []
    for j in d.get("jobs", []):
        loc = j.get("locationName", "") or ""
        if j.get("isRemote"):
            loc = (loc + " Remote").strip()
        out.append({
            "title": j.get("title", ""),
            "location": loc,
            "url": j.get("jobUrl", ""),
            "posted_date": (j.get("publishedAt") or "")[:10] or None,
            "description": None,
        })
    return out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever,
            "ashby": fetch_ashby}

# ------------------------------------------------------------------- main

def main():
    companies = json.load(open(COMPANIES))
    try:
        prev = {p["posting_url"]: p for p in json.load(open(POSTINGS))}
    except FileNotFoundError:
        prev = {}

    now_utc = datetime.now(timezone.utc)
    toronto = now_utc - timedelta(hours=4)  # EDT; EST is -5, close enough
    today = now_utc.date().isoformat()

    kept, scanned, new = {}, 0, 0
    for c in companies:
        name, ats, board = c["company"], c["ats"], c["board"]
        print(f"[{name}] {ats}/{board}")
        jobs = FETCHERS[ats](board)
        scanned += len(jobs)
        time.sleep(1)  # polite per-host pacing
        for j in jobs:
            if not TITLE_RE.search(j["title"]):
                continue
            if not is_canada_location(j["location"]):
                continue
            if not j["url"]:
                continue
            url = j["url"]
            if url in prev:
                row = prev[url]
                row["last_seen"] = today
            else:
                row = {
                    "company": name,
                    "title": j["title"][:240],
                    "location": j["location"][:320],
                    "posting_url": url,
                    "source": f"{name} official careers ({ats})",
                    "sector": guess_sector(j["title"]),
                    "posted_date": j["posted_date"],
                    "description": j["description"],
                    "deadline": None,
                    "first_seen": today,
                    "last_seen": today,
                }
                new += 1
            kept[url] = row

    # drop listings unseen for 14+ days (dead-link pruning lite)
    fresh = [r for r in kept.values()
             if (now_utc.date() -
                 datetime.fromisoformat(r["last_seen"]).date()).days <= 14]
    fresh.sort(key=lambda r: (r["company"], r["title"]))

    json.dump(fresh, open(POSTINGS, "w"), indent=1, ensure_ascii=False)
    meta = {
        "last_run_utc": now_utc.isoformat(timespec="seconds"),
        "last_run_toronto": toronto.isoformat(timespec="seconds"),
        "companies_checked": len(companies),
        "jobs_scanned": scanned,
        "canada_internships": len(fresh),
        "new_since_last_run": new,
    }
    json.dump(meta, open(META, "w"), indent=1)
    print(f"done: {len(fresh)} live Canada internships "
          f"({new} new), {scanned} jobs scanned")


if __name__ == "__main__":
    main()
