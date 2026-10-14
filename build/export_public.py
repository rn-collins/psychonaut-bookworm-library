#!/usr/bin/env python3
"""Write the public edition of this repository to a folder.

The source repository holds the whole 1,664-record ledger, including the records
the site withholds pending source and rights review. The public edition holds the
code, the tests, the documentation and only the records released as of the date.
Withheld records are carried as counts by reason in provenance/withheld.json and
nothing else: no id, no title, no excerpt, no source.

    python3 build/export_public.py --out ../psychonaut-bookworm-open
    python3 build/export_public.py --out /tmp/open --date 2026-11-01

Re-run it on any day a record is released, then commit the result in the public
repository. The script refuses to finish if any withheld id, or any withheld
record's text, appears in an exported file.
"""
import argparse
import datetime
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import build as site  # noqa: E402  (the site builder: gate, rid, load_releases)

# What the public edition carries. Anything not listed stays in the source repository.
INCLUDE_FILES = ["app.js", "governance.html", "robots.txt", "vercel.json", "LICENSE", "CITATIONS-Oct13.md",
                 "favicon.png", "apple-touch-icon.png", "og-image.png"]
INCLUDE_DIRS = ["build"]  # api/ forwards enquiries to a private service and stays in the source repository
README = "README.public.md"  # becomes README.md in the public edition


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="folder to write; its .git folder is kept")
    ap.add_argument("--date", help="release date to export as of, Honolulu, YYYY-MM-DD")
    args = ap.parse_args(argv)
    today = datetime.date.fromisoformat(args.date) if args.date else site.today_honolulu()
    out = os.path.abspath(args.out)
    if os.path.abspath(out) == ROOT:
        raise SystemExit("--out must not be the source repository")

    releases = site.load_releases(os.path.join(ROOT, "data", "releases.json"))
    released = {i for i, row in releases.items() if site.is_released(row, today)}
    withheld_rows = [row for i, row in releases.items() if i not in released]

    # Clear the target except for its git folder.
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):
        if name == ".git":
            continue
        p = os.path.join(out, name)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)

    for f in INCLUDE_FILES:
        if os.path.exists(os.path.join(ROOT, f)):
            shutil.copy2(os.path.join(ROOT, f), os.path.join(out, f))
    for d in INCLUDE_DIRS:
        shutil.copytree(os.path.join(ROOT, d), os.path.join(out, d),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "export_public.py"))
    shutil.copy2(os.path.join(HERE, "export_public.py"), os.path.join(out, "build", "export_public.py"))
    if os.path.exists(os.path.join(ROOT, README)):
        shutil.copy2(os.path.join(ROOT, README), os.path.join(out, "README.md"))

    # CI and housekeeping for the public edition.
    wf = os.path.join(out, ".github", "workflows")
    os.makedirs(wf, exist_ok=True)
    with open(os.path.join(wf, "ci.yml"), "w", encoding="utf-8") as f:
        f.write("""name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Release data matches the build
        run: python3 build/sync_releases.py --check
      - name: Release gate and withheld-content tests
        run: python3 build/test_release_gate.py
      - name: Build the site
        run: python3 build/build.py
""")
    # The Made-with commit rule belongs to the private repository. It would also fail
    # any outside contributor's pull request, so the open edition does not carry it.
    with open(os.path.join(out, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("dist/\n__pycache__/\n*.pyc\n.DS_Store\n")

    # Library: released records only.
    full = json.load(open(os.path.join(ROOT, "data", "library.json"), encoding="utf-8"))
    write_json(os.path.join(out, "data", "library.json"), site.gate(full, releases, today))

    # Citation links: only the entries whose citation occurs in the exported library, so the map
    # never carries a string from a record that is not released. The site built from this edition
    # links exactly the same citations as the source repository's build.
    links_path = os.path.join(ROOT, "data", "citation-links.json")
    if os.path.exists(links_path):
        links_doc = json.load(open(links_path, encoding="utf-8"))
        units = site.citation_units(site.gate(full, releases, today))
        links_doc["links"] = {k: v for k, v in links_doc["links"].items() if k in units}
        write_json(os.path.join(out, "data", "citation-links.json"), links_doc)

    # Releases: released rows only.
    # One row per line, the layout build/sync_releases.py writes and checks for.
    rows = [row for row in json.load(open(os.path.join(ROOT, "data", "releases.json"), encoding="utf-8"))
            if row["recordId"] in released]
    with open(os.path.join(out, "data", "releases.json"), "w", encoding="utf-8") as f:
        f.write("[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]\n")
    with open(os.path.join(out, "data", "released-ids.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(released)) + "\n")

    # Provenance: released records in full; withheld records as counts by reason.
    manifest = json.load(open(os.path.join(ROOT, "provenance", "manifest.json"), encoding="utf-8"))
    counts = {}
    for c in manifest["corpora"]:
        name = c["corpus"]
        src = json.load(open(os.path.join(ROOT, "provenance", f"{name}.json"), encoding="utf-8"))
        shown, reasons = [], {}
        for r in src["records"]:
            if r["recordId"] in released:
                shown.append(r)
            else:
                why = r.get("suppressionReason") or "not released yet"
                reasons[why] = reasons.get(why, 0) + 1
        write_json(os.path.join(out, "provenance", f"{name}.json"), {**src, "records": shown})
        counts[name] = {"count": sum(reasons.values()), "byReason": reasons}
    write_json(os.path.join(out, "provenance", "withheld.json"),
               {"note": "Withheld records are counted by reason and not listed. Their ids, titles, "
                        "excerpts and sources are kept in the source repository.",
                "corpora": counts})
    # Quotation mapping: verified and corrected entries only. Entries for quotations that could not
    # be traced belong to withheld records and stay in the source repository, and ledger record ids
    # are listed only for records that are released.
    qpath = os.path.join(ROOT, "provenance", "quotations.json")
    if os.path.exists(qpath):
        qdoc = json.load(open(qpath, encoding="utf-8"))
        kept = []
        for q in qdoc["quotations"]:
            if q["status"] == "not_traced":
                continue
            kept.append({**q, "ledgerRecords": [r for r in q.get("ledgerRecords", []) if r in released]})
        write_json(os.path.join(out, "provenance", "quotations.json"), {**qdoc, "quotations": kept})
    shutil.copy2(os.path.join(ROOT, "provenance", "manifest.json"), os.path.join(out, "provenance", "manifest.json"))

    # Leak check: no withheld id and no withheld record text anywhere in the export.
    needles = set()
    for row in withheld_rows:
        needles.update([row["recordId"], row["id"]])
    for key, items in full.items():
        if isinstance(items, list):
            for x in items:
                if site.rid(key, x) in released:
                    continue
                for field in ("title", "front", "claim", "body", "back", "quote", "text"):
                    v = x.get(field)
                    if isinstance(v, str) and len(v) >= 40:
                        needles.add(v[:80])
    # Withheld ledger records (their text lives in provenance/): titles and quotation excerpts.
    # Text that already appears in released library content is public on the live site and is
    # reported, not treated as a leak.
    released_library = json.dumps(json.load(open(os.path.join(out, "data", "library.json"), encoding="utf-8")),
                                  ensure_ascii=False)
    already_public = 0
    for c in manifest["corpora"]:
        src = json.load(open(os.path.join(ROOT, "provenance", f"{c['corpus']}.json"), encoding="utf-8"))
        for r in src["records"]:
            if r["recordId"] in released:
                continue
            strings = [r["title"]] if len(r.get("title") or "") >= 12 else []
            strings += [q for q in (r.get("quotationExcerpts") or []) if len(q) >= 25]
            for s in strings:
                if s in released_library:
                    already_public += 1
                else:
                    needles.add(s)
    leaks = []
    for dirpath, dirs, files in os.walk(out):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            p = os.path.join(dirpath, fn)
            try:
                text = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for n in needles:
                if n in text:
                    leaks.append((os.path.relpath(p, out), n[:60]))
                    break
    if leaks:
        for name in os.listdir(out):  # clear the output, keep the target's git folder
            if name != ".git":
                p = os.path.join(out, name)
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
        raise SystemExit("Refusing to export; withheld material found in:\n  " +
                         "\n  ".join(f"{p}: {n!r}" for p, n in leaks[:20]))
    if already_public:
        print(f"note: {already_public} withheld titles or quotations also appear in released library "
              f"content, which the live site already serves")
    print(f"exported {len(released)} released records as of {today}; "
          f"{len(withheld_rows)} withheld records carried as counts only -> {out}")


if __name__ == "__main__":
    main()
