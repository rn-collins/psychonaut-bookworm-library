#!/usr/bin/env python3
"""
Fill the link fields of data/releases.json, and write the sources data for
RN Collins Selected Work. Standard library only.

  python3 build/sync_releases.py                  rewrite data/releases.json
  python3 build/sync_releases.py --check          exit 1 if data/releases.json is out of date
  python3 build/sync_releases.py --sources PATH   also write the sources data for
                                                  rn-selected-work (data/sources-psychonaut-bookworm.json)

What it changes, and what it never changes
------------------------------------------
* releasedAt, hold and postUrls are RN's decisions. This script never changes them.
* id is the shared id, psychonaut-bookworm/<slug>, the same id rn-selected-work uses
  for the record's sources page. recordId is the provenance ledger id, <corpus>/<id>.
* For a record released as of today (Honolulu):
  - sourcePageUrl is its page on RN Collins Selected Work,
    https://rn-selected-work.vercel.app/sources/psychonaut-bookworm/<slug>.
  - longFormUrl is the editorial draft it belongs with. A draft is its own long-form.
    A course module's long-form is the first released draft it assigns. Any other
    record's long-form is the released draft, on the same book where the record names
    a book, whose words are closest to the record's own (a TF-IDF cosine match). The
    result is fixed by the data, so it only changes when the library changes.
  A record that is not released has both fields empty.
* --sources writes only released records, so nothing unreleased leaves this repo.
  When a record is released later, run this script with --sources again and commit
  the sources file to rn-selected-work, so its sources page exists on its day.
"""

import argparse
import collections
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "build"))
import build as B  # noqa: E402

RELEASES = os.path.join(ROOT, "data", "releases.json")
LIBRARY = os.path.join(ROOT, "data", "library.json")
STOP = set("""a an and are as at be been but by can did do does for from had has have he her his how
i if in into is it its may more most not of on or our she so than that the their them then there
these they this those to was were what when where which who why will with would you your about after
also any because before between both could each even every first had just like many much new no now
one only other out over same some such through under up very well""".split())


def tokens(text):
    return [w for w in re.findall(r"[a-z][a-z0-9'-]{2,}", (text or "").lower()) if w not in STOP]


def text_of(key, x):
    """The words that say what a record is about."""
    parts = [B.item_title(key, x)]
    for f in ("title", "claim", "thenClaim", "nowEvidence", "premise", "explanation", "front", "back",
              "introduction", "currentEvidence", "episodeTitle", "body"):
        v = x.get(f)
        if isinstance(v, str):
            parts.append(v)
    for f in ("focusQuestions", "objectives"):
        v = x.get(f)
        if isinstance(v, list):
            parts += [s for s in v if isinstance(s, str)]
    return " ".join(parts)


class Matcher:
    def __init__(self, drafts):
        self.drafts = drafts
        docs = [tokens((p["title"] + " ") * 3 + p.get("body", "")) for p in drafts]
        df = collections.Counter(w for d in docs for w in set(d))
        n = len(docs)
        self.idf = {w: math.log((1 + n) / (1 + c)) + 1 for w, c in df.items()}
        self.vecs = [self.vec(d) for d in docs]

    def vec(self, toks):
        tf = collections.Counter(toks)
        v = {w: c * self.idf.get(w, 0.0) for w, c in tf.items() if w in self.idf}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / norm for w, x in v.items()}

    def best(self, text, allowed):
        q = self.vec(tokens(text))
        scored = []
        for n, p in enumerate(self.drafts):
            if p["id"] not in allowed:
                continue
            s = sum(x * self.vecs[n].get(w, 0.0) for w, x in q.items())
            scored.append((-s, n))
        if not scored:
            return None
        scored.sort()
        return self.drafts[scored[0][1]]


def long_forms(D):
    """record id -> the released draft that is its long-form."""
    drafts = D["pieces"]
    m = Matcher(drafts)
    all_ids = {p["id"] for p in drafts}
    by_title = {(p.get("title") or "").strip().lower(): p for p in drafts}
    by_id = {p["id"]: p for p in drafts}
    out = {}
    for key in B.ITEM_ORDER:
        for x in D[key]:
            if key == "pieces":
                out[B.rid(key, x)] = x
                continue
            choice = None
            if key == "courseModules":
                for r in x.get("readings") or []:
                    choice = by_id.get(r.get("id")) or by_title.get((r.get("title") or "").strip().lower())
                    if choice:
                        break
            if not choice:
                books = set(B.books_of(x))
                same_book = {p["id"] for p in drafts if p.get("bookSlug") in books}
                choice = m.best(text_of(key, x), same_book or all_ids)
            if choice:
                out[B.rid(key, x)] = choice
    return out


def sync(rows, D, today):
    released = {B.rid(k, x) for k in B.ITEM_ORDER for x in D[k]}
    lf = long_forms(D)
    out = []
    for row in rows:
        rec = row.get("recordId") or row["id"]
        new = {
            "id": B.shared_id(rec),
            "recordId": rec,
            "releasedAt": row["releasedAt"],
            "hold": row["hold"],
            "postUrls": row.get("postUrls") or [],
            "longFormUrl": "",
            "sourcePageUrl": "",
        }
        if rec in released and B.is_released(row, today):
            new["sourcePageUrl"] = f"{B.SOURCES_BASE}/{B.source_slug(rec)}"
            if rec in lf:
                new["longFormUrl"] = B.BASE + B.item_path(B.rid("pieces", lf[rec]))
        out.append(new)
    return out


DASHES = str.maketrans({"—": "-", "–": "-"})


def clean(label):
    label = re.sub(r"\s*—\s*", ": ", label or "")
    return re.sub(r"\s+", " ", label.translate(DASHES)).strip()


def research(key, x):
    """The sources a record names, as it names them. None of them carries a URL."""
    if key in ("pieces", "thenVsNow", "bridges"):
        items = x.get("sources") or []
    elif key in ("flashcards", "annotations"):
        items = [x.get("citation")]
    elif key == "claimSorter":
        items = [x.get("source")]
    elif key == "eduModules":
        items = x.get("requiredReading") or []
    elif key == "readingLists":
        items = []
        for en in x.get("entries") or []:
            who = en.get("author") or ""
            yr = f" ({en['year']})" if en.get("year") else ""
            items.append(f"{who}, {en.get('title', '')}{yr}" if who else f"{en.get('title', '')}{yr}")
    elif key == "notebookLM":
        items = [m.group(1) for m in re.finditer(r"^SOURCE \d+\s*[—:-]+\s*(.+?):?\s*$",
                                                 x.get("sourceMaterial") or "", re.M)]
    elif key == "courseModules":
        items = [f"{b} (book in this module)" for b in x.get("books") or []]
    else:
        items = []
    seen, out = set(), []
    for s in items:
        s = clean(s if isinstance(s, str) else "")
        if s and s not in seen:
            seen.add(s)
            out.append({"label": s, "url": ""})
    return out


def series(key, x):
    label = B.TYPE_LABEL[key]
    books = x.get("books") if isinstance(x.get("books"), list) else ([x["book"]] if x.get("book") else [])
    return f"Psychonaut Bookworm, {label.lower() if key != 'notebookLM' else label}" + (
        f" on {', '.join(books)}" if books else "")


def sources_data(D, releases):
    lf = long_forms(D)
    posts = []
    for key in B.ITEM_ORDER:
        corpus = B.KEY_TO_CORPUS.get(key, key)
        for x in D[key]:
            rec = B.rid(key, x)
            row = releases[rec]
            draft = lf.get(rec)
            origin = None
            if draft:
                origin = {"kind": "article", "label": clean(draft["title"]),
                          "url": B.BASE + B.item_path(B.rid("pieces", draft))}
            posts.append({
                "slug": B.source_slug(rec),
                "date": row["releasedAt"],
                "id": rec,
                "title": clean(B.item_title(key, x)),
                "series": clean(series(key, x)),
                "origin": origin,
                "research": research(key, x),
                "other": [{"label": f"The public provenance ledger for this corpus, which lists "
                                    f"record {rec} and the sources it was checked against",
                           "url": f"{B.BASE}/provenance/{corpus}.json"}],
                "images": [],
            })
    return {
        "note": "Generated by rn-collins/psychonaut-bookworm build/sync_releases.py --sources from that "
                "repository's data/library.json and data/releases.json. Released records only. Do not edit "
                "by hand.",
        "posts": posts,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--sources")
    ap.add_argument("--date")
    args = ap.parse_args(argv)
    import datetime
    today = datetime.date.fromisoformat(args.date) if args.date else B.today_honolulu()
    rows = json.load(open(RELEASES, encoding="utf-8"))
    full = json.load(open(LIBRARY, encoding="utf-8"))
    gate_rows = {(r.get("recordId") or r["id"]): r for r in rows}
    D = B.gate(full, gate_rows, today)
    new = sync(rows, D, today)
    # One entry per line, as RN's file has always been written.
    text = "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in new) + "\n]\n"
    if args.check:
        if open(RELEASES, encoding="utf-8").read() != text:
            sys.exit("data/releases.json is out of date: run python3 build/sync_releases.py")
        print("data/releases.json is up to date")
    else:
        open(RELEASES, "w", encoding="utf-8").write(text)
        print(f"wrote data/releases.json ({len(new)} entries, "
              f"{sum(1 for r in new if r['sourcePageUrl'])} released)")
    if args.sources:
        data = sources_data(D, {r["recordId"]: r for r in new})
        with open(args.sources, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
        print(f"wrote {args.sources} ({len(data['posts'])} posts)")


if __name__ == "__main__":
    main()
