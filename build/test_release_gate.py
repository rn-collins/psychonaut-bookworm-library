#!/usr/bin/env python3
"""
Checks the release gate against real builds. Standard library only.

  python3 build/test_release_gate.py

1. Today's build: every released record has a page, nothing else does, and no
   withheld title, writing id or excerpt appears in any file the site serves
   (unless the same words are also part of published library text).
2. Every item page links to the gallery index, its place in the index, its
   neighbours, the project page, its sources page on RN Collins Selected Work,
   and its long-form draft. Every link between two item pages runs both ways.
   data/releases.json matches build/sync_releases.py.
3. A record dated in the future, put on hold, or missing from releases.json is
   absent from the index, the item pages, the sitemap and the public ledger,
   and it appears on its release date.
4. data/citation-links.json: every mapped citation occurs in the released data,
   every DOI, PubMed and web address is well formed, nothing under review is
   linked, every link on a built page comes from the map, and a citation with no
   entry is printed as plain text (the pages are identical to a build with an
   empty map once the links are taken out).
"""

import datetime
import html
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build", "build.py")
failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def build(out, releases=None, date=None, citation_links=None):
    cmd = [sys.executable, BUILD, "--out", out]
    if releases:
        cmd += ["--releases", releases]
    if date:
        cmd += ["--date", date]
    if citation_links:
        cmd += ["--citation-links", citation_links]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def served_text(out):
    text = {}
    for dp, _, fs in os.walk(out):
        for fn in fs:
            p = os.path.join(dp, fn)
            if fn.endswith((".html", ".json", ".xml", ".js", ".txt")):
                text[os.path.relpath(p, out)] = html.unescape(open(p, encoding="utf-8").read())
    return text


def ledger_records():
    out = []
    for fn in sorted(os.listdir(os.path.join(ROOT, "provenance"))):
        if fn.endswith(".json") and fn not in ("manifest.json", "withheld.json", "quotations.json"):
            out += json.load(open(os.path.join(ROOT, "provenance", fn), encoding="utf-8"))["records"]
    return out


DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s\"<>]+$")
PUBMED_RE = re.compile(r"^https://pubmed\.ncbi\.nlm\.nih\.gov/\d+/$")
CITE_LINK_RE = re.compile(r'<a class="cite-link" href="([^"]*)" rel="noopener" data-cite="([^"]*)">(.*?)</a>', re.S)


def check_citation_links(today, released_library, text_linked, text_plain, site):
    path = os.path.join(ROOT, "data", "citation-links.json")
    check(os.path.exists(path), "data/citation-links.json is missing")
    if not os.path.exists(path):
        return 0
    links = site.load_citation_links(path)
    units = site.citation_units(released_library)
    today_d = datetime.date.fromisoformat(today)
    for text, link in links.items():
        short = text[:70]
        check(text in units, f"citation link for a string that is not in the released data: {short!r}")
        check("Source not found" not in text and "under review" not in text,
              f"a citation marked as under review is linked: {short!r}")
        url, kind = link["url"], link["kind"]
        if kind == "doi":
            doi = url[len("https://doi.org/"):] if url.startswith("https://doi.org/") else ""
            check(bool(DOI_RE.match(doi)), f"not a valid DOI link for {short!r}: {url}")
        elif kind == "pubmed":
            check(bool(PUBMED_RE.match(url)), f"not a PubMed link for {short!r}: {url}")
        else:
            check(url.startswith("https://") and not url.startswith("https://doi.org/"),
                  f"url-kind link for {short!r} must be an https address that is not a DOI: {url}")
        check(datetime.date.fromisoformat(link["verified"]) <= today_d,
              f"verified date is in the future for {short!r}")
    # Pages: every link comes from the map, with the cited text as its label.
    shown = set()
    for name, page in text_linked.items():
        if not name.endswith(".html"):
            continue
        for href, kind, label in CITE_LINK_RE.findall(page):
            label = html.unescape(label)
            link = links.get(label)
            check(link is not None and link["url"] == html.unescape(href) and link["kind"] == kind,
                  f"{name}: link on {label[:60]!r} is not in data/citation-links.json")
            check("Source not found" not in label, f"{name}: a citation under review is linked")
            shown.add(label)
        check(page.count("<a class=\"cite-link\"") == len(CITE_LINK_RE.findall(page)),
              f"{name}: a citation link has unexpected markup")
    check(len(shown) > 0, "no citation link appears on any built page")
    # An unmapped citation stays plain text, and a build with an empty map has no links at all.
    for name, page in text_plain.items():
        check('<a class="cite-link"' not in page, f"{name}: a link appears although the citation map is empty")
        if name.endswith(".html") and name in text_linked:
            stripped = CITE_LINK_RE.sub(lambda m: m.group(3), text_linked[name])
            check(stripped == page, f"{name}: linking changed more than the citations")
    saved = dict(site.CITATION_LINKS)
    try:
        site.CITATION_LINKS.clear()
        site.CITATION_LINKS["Known, Journal (2001)"] = {"url": "https://doi.org/10.1/x", "kind": "doi",
                                                        "verified": "2026-10-13"}
        out = site.cite("Known, Journal (2001); Unknown, Journal (2002) [Source not found; under review]")
        check(out.count("<a ") == 1 and "Unknown, Journal (2002) [Source not found; under review]" in out
              and "</a>; Unknown" in out, f"cite() linked the wrong part: {out}")
        check("<a " not in site.cite("Unknown, Journal (2002)"), "cite() linked a citation that is not in the map")
        check(site.cite("A & B <c>") == "A &amp; B &lt;c&gt;", "cite() does not escape plain text")
    finally:
        site.CITATION_LINKS.clear()
        site.CITATION_LINKS.update(saved)
    return len(shown)


def check_quotations(records, released):
    """Direct quotations need a deterministic source mapping (provenance/quotations.json)."""
    path = os.path.join(ROOT, "provenance", "quotations.json")
    if not os.path.exists(path):
        return
    doc = json.load(open(path, encoding="utf-8"))
    library = json.load(open(os.path.join(ROOT, "data", "library.json"), encoding="utf-8"))
    items = {f"{k}/{x['id']}": json.dumps(x, ensure_ascii=False)
             for k, v in library.items() if isinstance(v, list) for x in v}
    everything = "\n".join(items.values())
    matches = []
    for q in doc["quotations"]:
        if q["status"] == "not_traced":
            check(q["absent"] not in everything, f"{q['id']}: a quotation that could not be traced is back in released data")
            continue
        check(q["status"] in ("verified", "corrected"), f"{q['id']}: unknown status {q['status']}")
        check(bool(q["source"].get("work")) and bool(q["source"].get("locator")),
              f"{q['id']}: a mapped quotation needs a work and a locator")
        matches.append(q["match"])
        for item in q["appearsIn"]:
            check(item in items and q["match"] in items[item],
                  f"{q['id']}: '{q['match'][:50]}' is not in {item}")
    # A quotation recorded on a withheld ledger record must not sit in released data unmapped.
    for r in records:
        if r["recordId"] in released:
            continue
        for ex in r.get("quotationExcerpts") or []:
            if len(ex) >= 25 and ex in everything:
                check(any(m in ex or ex in m for m in matches),
                      f"{r['recordId']}: quotation in released data has no source mapping: {ex[:60]}")


def main():
    releases = json.load(open(os.path.join(ROOT, "data", "releases.json"), encoding="utf-8"))
    rel = {r["recordId"]: r for r in releases}
    sync = subprocess.run([sys.executable, os.path.join(ROOT, "build", "sync_releases.py"), "--check"],
                          capture_output=True, text=True)
    check(sync.returncode == 0, f"sync_releases.py --check: {sync.stdout}{sync.stderr}".strip())
    today = subprocess.run([sys.executable, "-c",
                            "import sys;sys.path.insert(0,'build');import build;"
                            "print(build.today_honolulu())"],
                           cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    released = set(subprocess.run([sys.executable, BUILD, "--released-ids"], capture_output=True,
                                  text=True, check=True).stdout.split())
    library_text = open(os.path.join(ROOT, "data", "library.json"), encoding="utf-8").read()
    library_text = json.dumps(json.loads(library_text), ensure_ascii=False)
    records = ledger_records()
    check_quotations(records, released)
    check(len(records) == len(rel), f"releases.json has {len(rel)} entries, ledger has {len(records)}")

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "dist")
        build(out)
        text = served_text(out)
        everything = "\n".join(text.values())
        pages = {p[len("item/"):-len(".html")] for p in text if p.startswith("item/")}
        check(pages == released, f"item pages {len(pages)} != released ids {len(released)}")
        for name in ("data/library.json", "data/releases.json", "build/build.py", "README.md"):
            check(name not in text and not os.path.exists(os.path.join(out, name)),
                  f"{name} is in the build output")

        # 1. withheld content
        for r in records:
            if r["recordId"] in released:
                continue
            probes = []
            if r.get("title") and len(r["title"]) >= 12:
                probes.append(r["title"])
            probes += [x for x in (r.get("quotationExcerpts") or []) if len(x) >= 25]
            if r["corpus"] == "writing":
                probes.append(r["canonicalWorkId"])
            check(r["recordId"] not in everything, f"withheld id {r['recordId']} is in the output")
            for t in probes:
                if t in everything and t not in library_text:
                    check(False, f"withheld text from {r['recordId']} is in the output: {t[:60]}")

        # 2. links on every item page
        index = text["index.html"]
        sitemap = text["sitemap.xml"]
        for i in sorted(pages):
            page = text[f"item/{i}.html"]
            check('href="/"' in page, f"{i}: no link to the gallery index")
            check("https://rn-selected-work.vercel.app/work/psychonaut-bookworm" in page,
                  f"{i}: no project page link")
            m = re.search(r'href="/#([^"]+)">See it in the gallery index', page)
            check(bool(m) and f'id="{m.group(1)}"' in index if m else False,
                  f"{i}: gallery anchor missing or not in the index")
            check(f"/item/{i}\"" in index, f"{i}: index does not link to its page")
            check(f"/item/{i}</loc>" in sitemap, f"{i}: not in the sitemap")
            for u in rel[i]["postUrls"]:
                check(u in page, f"{i}: post link {u} missing")
            src = rel[i]["sourcePageUrl"]
            check(src.startswith("https://rn-selected-work.vercel.app/sources/psychonaut-bookworm/")
                  and f'href="{src}"' in page, f"{i}: source page link missing")
            lf = rel[i]["longFormUrl"]
            check(lf.startswith("https://psychonaut-bookworm.vercel.app/item/writing/"),
                  f"{i}: no long-form draft in releases.json")
            if not i.startswith("writing/"):
                lf_path = lf[len("https://psychonaut-bookworm.vercel.app"):]
                check(f'<dt>Long-form</dt><dd><a href="{lf_path}">' in page, f"{i}: long-form link missing")
                check(lf_path[len("/item/"):] in pages, f"{i}: long-form {lf_path} is not a released page")
            for target in re.findall(r'href="(/item/[^"#]+)"', page):
                check(target[len("/item/"):] in pages, f"{i}: links to unpublished {target}")
        # Every item-to-item link has a link back (the pager is reading order, not a reference).
        out_links = {}
        for i in pages:
            body = re.sub(r'<nav class="pager".*?</nav>', "", text[f"item/{i}.html"], flags=re.S)
            out_links[i] = {t[len("/item/"):] for t in re.findall(r'href="(/item/[^"#?]+)"', body)}
        oneway = [(a, b) for a, ts in out_links.items() for b in ts
                  if b != a and b in out_links and a not in out_links[b]]
        check(not oneway, f"{len(oneway)} one-way item links, e.g. {oneway[:3]}")
        # The pager is printed above and below the links, so each link appears twice.
        nav_counts = [len(re.findall(r">(Previous|Next): ", text[f"item/{i}.html"])) // 2
                      for i in pages]
        check(nav_counts.count(2) == len(pages) - 2 and nav_counts.count(1) == 2,
              "previous/next links are not one each side on every page")

    # 3. a future date, a hold and a missing entry, on copies of releases.json
    victims = sorted(released)[:3]
    future = "2099-01-01"
    edited = []
    for r in releases:
        r = dict(r)
        if r["recordId"] == victims[0]:
            r["releasedAt"] = future
        if r["recordId"] == victims[1]:
            r["hold"] = True
        if r["recordId"] == victims[2]:
            continue
        edited.append(r)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "releases.json")
        json.dump(edited, open(path, "w"))
        for date, should_show_future in ((today, False), (future, True)):
            out = os.path.join(tmp, f"dist-{date}")
            build(out, path, date)
            text = served_text(out)
            for v in victims:
                shows = os.path.exists(os.path.join(out, "item", v + ".html"))
                expect = should_show_future and v == victims[0]
                check(shows == expect, f"{v} on {date}: page present={shows}, expected {expect}")
                if not expect:
                    check(f"/item/{v}" not in "\n".join(text.values()),
                          f"{v} on {date}: still linked or listed somewhere")
                    corpus = v.split("/")[0]
                    ledger = json.loads(text[f"provenance/{corpus}.json"])
                    check(v not in [r["recordId"] for r in ledger["records"]],
                          f"{v} on {date}: still in the public ledger")

    # 4. citation links
    sys.path.insert(0, os.path.join(ROOT, "build"))
    import build as site
    full_library = json.load(open(os.path.join(ROOT, "data", "library.json"), encoding="utf-8"))
    released_library = site.gate(full_library, site.load_releases(os.path.join(ROOT, "data", "releases.json")),
                                 datetime.date.fromisoformat(today))
    with tempfile.TemporaryDirectory() as tmp:
        empty = os.path.join(tmp, "empty-citation-links.json")
        json.dump({"links": {}}, open(empty, "w"))
        build(os.path.join(tmp, "linked"))
        build(os.path.join(tmp, "plain"), citation_links=empty)
        linked_n = check_citation_links(today, released_library, served_text(os.path.join(tmp, "linked")),
                                        served_text(os.path.join(tmp, "plain")), site)

    if failures:
        print(f"FAIL: {len(failures)} problem(s)")
        for f in failures[:50]:
            print("  " + f)
        sys.exit(1)
    print(f"ok: {len(released)} released records checked as of {today}; "
          f"future date, hold and missing entry all stay hidden; "
          f"{linked_n} distinct citations are linked, the rest print as plain text")


if __name__ == "__main__":
    main()
