#!/usr/bin/env python3
"""
Re-check data/citation-links.json against the live sources. Standard library only.

  python3 build/verify_citation_links.py                 check every link
  python3 build/verify_citation_links.py --only doi      check one kind (doi, pubmed, url)
  python3 build/verify_citation_links.py --delay 2       wait longer between requests

This needs the network, so it is not part of the release-gate test. Run it before adding
links to the map, and from time to time afterwards, since links rot.

* doi: Crossref must return the work (api.crossref.org/works/<doi>), the DOI resolver must
  know the DOI (doi.org/api/handles/<doi>), and the first author, year and title must still
  match what the map recorded in "matched".
* pubmed: the PubMed record must still have the recorded first author and year.
* url: the address must load (HTTP 200). A site that refuses scripted requests (403, 429)
  is reported as unchecked, not as broken.

Exit status is 1 when any link is broken or no longer matches.
"""
import argparse
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "psychonaut-bookworm-citation-check/1.0 (+https://github.com/rn-collins/psychonaut-bookworm-library)"
_last = [0.0]


def get(url, delay, json_body=True):
    wait = delay - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(4):
        _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read(2_000_000)
                return r.status, (json.loads(body) if json_body else body)
        except urllib.error.HTTPError as err:
            if err.code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            return err.code, None
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            time.sleep(3)
    return 0, None


def norm(s):
    s = unicodedata.normalize("NFKD", html.unescape(s or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s)


def check_doi(text, link, delay):
    doi = link["url"][len("https://doi.org/"):]
    status, doc = get("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/()"), delay)
    if status != 200:
        return "broken", f"Crossref returned {status}"
    msg = doc["message"]
    status, handle = get("https://doi.org/api/handles/" + urllib.parse.quote(doi, safe="/()"), delay)
    if status != 200 or handle.get("responseCode") != 1:
        return "broken", "the DOI resolver does not know this DOI"
    m = link.get("matched", {})
    author = (msg.get("author") or [{}])[0]
    years = {d["date-parts"][0][0] for k in ("issued", "published-print", "published-online")
             if (d := msg.get(k)) and d.get("date-parts") and d["date-parts"][0][0]}
    if m.get("firstAuthor") and norm(m["firstAuthor"]) != norm(author.get("family") or author.get("name")):
        return "mismatch", f"first author is now {author.get('family')!r}"
    if m.get("year") and m["year"] not in years:
        return "mismatch", f"year {m['year']} not among {sorted(years)}"
    if m.get("title") and norm(m["title"]) != norm((msg.get("title") or [""])[0]):
        return "mismatch", "title changed"
    return "ok", ""


def check_pubmed(text, link, delay):
    pmid = link["url"].rstrip("/").rsplit("/", 1)[1]
    status, doc = get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id=" + pmid, delay)
    rec = (doc or {}).get("result", {}).get(pmid)
    if status != 200 or not rec:
        return "broken", f"PubMed returned {status}"
    m = link.get("matched", {})
    first = (rec.get("authors") or [{"name": ""}])[0]["name"]
    if m.get("firstAuthor") and norm(m["firstAuthor"]) not in norm(first):
        return "mismatch", f"first author is now {first!r}"
    if m.get("year") and str(m["year"]) not in rec.get("pubdate", ""):
        return "mismatch", f"year is now {rec.get('pubdate')!r}"
    return "ok", ""


def check_url(text, link, delay):
    status, body = get(link["url"], delay, json_body=False)
    if status in (403, 429, 0):
        return "unchecked", f"the site did not answer a scripted request ({status})"
    if status != 200:
        return "broken", f"HTTP {status}"
    return "ok", ""


CHECKS = {"doi": check_doi, "pubmed": check_pubmed, "url": check_url}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=os.path.join(ROOT, "data", "citation-links.json"))
    ap.add_argument("--only", choices=sorted(CHECKS))
    ap.add_argument("--delay", type=float, default=1.1, help="seconds between requests (default 1.1)")
    args = ap.parse_args(argv)
    links = json.load(open(args.file, encoding="utf-8"))["links"]
    tally = {"ok": 0, "unchecked": 0, "broken": 0, "mismatch": 0}
    done = {}
    for text, link in sorted(links.items()):
        if args.only and link["kind"] != args.only:
            continue
        key = (link["kind"], link["url"])
        if key not in done:  # many citations share one source
            done[key] = CHECKS[link["kind"]](text, link, args.delay)
        state, why = done[key]
        tally[state] += 1
        if state != "ok":
            print(f"{state.upper():9} {text[:80]} -> {link['url']} {why}")
    print(f"{tally['ok']} ok, {tally['unchecked']} unchecked, {tally['broken']} broken, {tally['mismatch']} mismatched")
    sys.exit(1 if tally["broken"] or tally["mismatch"] else 0)


if __name__ == "__main__":
    main()
