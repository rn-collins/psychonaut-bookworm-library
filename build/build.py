#!/usr/bin/env python3
"""
Generate index.html from data/library.json.

Why this exists
---------------
The page used to ship a 1,036,682-character `const D = {...}` object and build
every view with `el.innerHTML = ...` at load. A crawler, a share unfurler, or a
reader with JavaScript off saw 428 visible words and none of the 454 published
objects. This script renders those objects into the document, so the HTML that
leaves the server is the library.

Rules encoded here
------------------
* Every published count on the page is computed from the data, never typed.
  `verify()` fails the build when a claim in build/head.html or build/tail.html
  disagrees with data/library.json, so a number cannot drift silently.
* Word counts shown against a draft are the length of the text published here,
  measured at build time. The data file also carries a `wordCount` field that is
  larger than every body it labels; it is not displayed.
* The five withheld object types (quote cards, documents of the week, character
  profiles, passage spotlights, geography series) render their withholding
  notice and nothing else. They stay withheld.
* Controls that cannot work without JavaScript carry `data-js-only` and ship
  `hidden`; app.js reveals them. Nothing renders as a dead affordance.

Release gate (October 2026)
---------------------------
* data/releases.json is the only thing that decides what is public. A record
  is released when its `releasedAt` date (Pacific/Honolulu) is today or earlier
  and `hold` is false. Anything else, including a record with no entry at all,
  is left out of every file the build writes: the index, the item pages, the
  sitemap, the public ledger and the search text.
* The site is built into dist/. Vercel serves dist/ and nothing else, so the
  repository root (data/, provenance/, build/) is never served.
* Each released record gets its own page at /item/<corpus>/<id>, with links to
  its posts, its source page, its long-form draft, the gallery index, and the
  previous and next records.

Usage:
  python3 build/build.py                     build dist/ for today (Honolulu)
  python3 build/build.py --date 2026-10-20   build as if it were that date
  python3 build/build.py --out /tmp/x        build somewhere else
  python3 build/build.py --released-ids      print the released ids and exit
"""

import argparse
import datetime
import html
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
BASE = "https://psychonaut-bookworm.vercel.app"
PORTFOLIO = "https://rn-selected-work.vercel.app/work/psychonaut-bookworm"
# Each record's sources page on RN Collins Selected Work lives at
# /sources/psychonaut-bookworm/<slug>, and the shared id used in both repos'
# data/releases.json is psychonaut-bookworm/<slug>. The slug is the corpus,
# lower-cased, then the record's own id (writing-dmt-in-the-brain, thenvsnow-tvn-001).
ACCOUNT = "psychonaut-bookworm"
SOURCES_BASE = f"https://rn-selected-work.vercel.app/sources/{ACCOUNT}"
# Hawaii does not observe daylight saving time, so UTC-10 is exact all year.
HONOLULU = datetime.timezone(datetime.timedelta(hours=-10), "Pacific/Honolulu")

# library.json section key -> provenance corpus name (the id prefix).
KEY_TO_CORPUS = {"pieces": "writing", "eduModules": "modules"}
# Order of item pages, and of previous/next, follows the index.
ITEM_ORDER = ["pieces", "thenVsNow", "flashcards", "claimSorter", "bridges",
              "readingLists", "annotations", "notebookLM", "courseModules", "eduModules"]
TYPE_LABEL = {"pieces": "Editorial draft", "thenVsNow": "Then vs. Now comparison",
              "flashcards": "Flashcard", "claimSorter": "Claim", "bridges": "Bridge piece",
              "readingLists": "Reading list", "annotations": "Science annotation",
              "notebookLM": "NotebookLM source pack", "courseModules": "Course module",
              "eduModules": "Teaching module"}
# Internal workflow states, shown as what they are. "published" in the data
# meant "editorial complete"; the site is not an external publication.
STATUS_TEXT = {"published": "editorial complete", "ready": "editorial ready"}


def rid(key, item):
    """The shared id: the provenance ledger's recordId, <corpus>/<id>."""
    return f"{KEY_TO_CORPUS.get(key, key)}/{item['id']}"


def source_slug(record_id):
    corpus, own = record_id.split("/", 1)
    return f"{corpus.lower()}-{own}"


def shared_id(record_id):
    """The id this record carries in both repositories' data/releases.json."""
    return f"{ACCOUNT}/{source_slug(record_id)}"


def item_path(record_id):
    return f"/item/{record_id}"


def anchor(key, item):
    """The id of the item's element on the index page."""
    if key == "pieces":
        return f"draft-{item['id']}"
    if key == "notebookLM":
        return f"pack-{item['id']}"
    if key == "courseModules":
        return f"course-{item['id']}"
    return f"{KEY_TO_CORPUS.get(key, key)}-{item['id']}"


def permalink(record_id):
    return (f'<p class="mono permalink"><a href="{e(item_path(record_id))}">'
            'Open this item on its own page</a></p>')


def e(x):
    """Escape for HTML text and attribute context. The data is plain prose —
    'Moksha: Letters of Huxley & Osmond' was previously injected raw."""
    return html.escape("" if x is None else str(x), quote=True)


def words(text):
    return len((text or "").split())


def paras(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def prose(text, cls=""):
    c = f' class="{cls}"' if cls else ""
    return "".join(f"<p{c}>{e(p)}</p>" for p in paras(text))


# ---------------------------------------------------------------- constants
# Lifted verbatim from the runtime renderers they replace.
FMT_LABELS = {"flagship": "Flagship", "series": "Series Article", "deep-dive": "Deep Dive",
              "policy": "Policy Piece", "mini-essay": "Mini-Essay",
              "science-journalism": "Science Journalism", "passage-spotlight": "Passage Spotlight"}
FMT_COLORS = {"flagship": "#8B3A0F", "series": "#2D5A1B", "deep-dive": "#4A4A8B",
              "policy": "#4A6741", "mini-essay": "#4A6741",
              "science-journalism": "#2D5A1B", "passage-spotlight": "#4A4A8B"}
STATUS_COLOR = {"confirmed": "#2D5A1B", "refuted": "#8B3A0F", "ongoing": "#4A4A8B",
                "complicated": "#8B6914"}
STATUS_LABEL = {"confirmed": "Confirmed by Science", "refuted": "Refuted by Evidence",
                "ongoing": "Still Open", "complicated": "It's Complicated"}
VERDICT_COLOR = {"confirmed": "#2D5A1B", "partially_confirmed": "#4A6741", "refuted": "#8B3A0F",
                 "unresolved": "#4A4A8B", "untestable": "#8B6914"}
VERDICT_LABEL = {"confirmed": "Confirmed", "partially_confirmed": "Partially Confirmed",
                 "refuted": "Refuted", "unresolved": "Unresolved", "untestable": "Untestable"}
DIFF_COLOR = {"basic": "#4A6741", "intermediate": "#8B6914", "advanced": "#6B4C9A"}
THEME_COLOR = {"ethnobotany": "#4A6741", "phenomenology": "#8B6914", "neuroscience": "#4A4A8B",
               "history": "#8B3A0F", "culture": "#6B4C9A", "policy": "#2D5A1B",
               "synthesis": "#1A1410"}
CAT_COLOR = {"mechanism": "#8B3A0F", "therapeutic": "#2D5A1B", "pharmacology": "#4A4A8B",
             "neuroplasticity": "#4A6741", "brain-regions": "#8B6914", "safety": "#6B5E52"}

BOOK_PILLS = [
    ("all", "All Books"), ("doors-of-perception", "Doors"),
    ("letters-huxley-osmond", "Moksha"), ("lsd-my-problem-child", "LSD"),
    ("food-of-the-gods", "Food"), ("chasing-the-scream", "Chasing"),
    ("road-to-eleusis", "Eleusis"), ("storming-heaven", "Storming"),
    ("emperor-wears-no-clothes", "Emperor"), ("true-hallucinations", "True Hall."),
    ("cosmic-serpent", "Cosmic"), ("plants-of-the-gods", "Plants"),
]

WITHHELD_NOTE = (
    "{what} are not published in this edition. Every record is counted in the "
    '<a href="/provenance/manifest.json">provenance ledger</a>; items are withheld where an '
    "item-level source or a publication basis for a rights-sensitive excerpt has not been "
    'recorded. <a href="/governance">Read the publication rules or request a correction</a>.'
)


def verdict_label(v):
    """The canonical verdict vocabulary. `gaining-traction` appears once in
    claimSorter and is not in the original VERDICT_LABEL map, so it fell back to
    the raw slug; it is titled here rather than dropped."""
    return VERDICT_LABEL.get(v) or (v or "").replace("_", " ").replace("-", " ").title()


def verdict_pills(records, key="verdict"):
    """Filter pills are derived from the data, so a verdict that exists cannot
    be unreachable from the filter bar."""
    order = ["confirmed", "partially_confirmed", "gaining-traction", "unresolved",
             "refuted", "untestable"]
    seen = []
    for r in records:
        v = r.get(key)
        if v and v not in seen:
            seen.append(v)
    seen.sort(key=lambda v: order.index(v) if v in order else len(order))
    return [(v, verdict_label(v)) for v in seen]


def book_pills(present):
    """Only offer a book pill when the section actually holds something from
    that book. The hardcoded 12-pill bar offered Cosmic Serpent on Bridge
    Pieces, which has none — a filter that can only ever say "no results"."""
    present = set(present)
    return [("all", "All Books")] + [(s, l) for s, l in BOOK_PILLS[1:] if s in present]


TOPIC_LABELS = {
    "brain-regions": "Brain Regions", "partially-confirmed": "~ Partial",
    "confirmed": "✓ Confirmed", "contested": "? Contested", "reversed": "✗ Reversed",
    "emerging": "◦ Emerging",
}


def topic_pills(values, labels=None):
    """Derived from the data, most common first. A hardcoded vocabulary put
    History, Philosophy and Policy on the flashcard bar — none of which any of
    the ten published cards carries — and left Safety, Neuroplasticity and
    Brain Regions, which they do carry, with no pill at all."""
    labels = labels or TOPIC_LABELS
    counts = {}
    for v in values:
        if v:
            counts[v] = counts.get(v, 0) + 1
    ordered = sorted(counts, key=lambda v: (-counts[v], v))
    return [(v, labels.get(v) or v.replace("-", " ").replace("_", " ").title()) for v in ordered]


def flat(records, key):
    out = []
    for r in records:
        v = r.get(key)
        if isinstance(v, list):
            out.extend(v)
        elif v:
            out.append(v)
    return out


def filter_bar(cid, target, books, topics=None, search=True, label="Filter"):
    """A filter bar is inert without JavaScript, so it ships hidden and app.js
    reveals it. The content it filters is already in the document."""
    out = [f'<div class="filter-bar" id="{cid}-filterbar" data-target="{target}" '
           f'data-js-only hidden role="group" aria-label="{e(label)}">']
    for slug, lab in books:
        active = " active" if slug == "all" else ""
        out.append(f'<button type="button" class="filter-pill{active}" data-group="book" '
                   f'data-val="{e(slug)}" data-cid="{cid}" '
                   f'aria-pressed="{"true" if slug=="all" else "false"}">{e(lab)}</button>')
    if topics:
        out.append('<div class="filter-sep"></div>')
        out.append(f'<button type="button" class="filter-pill active" data-group="topic" '
                   f'data-val="all" data-cid="{cid}" aria-pressed="true">All</button>')
        for slug, lab in topics:
            out.append(f'<button type="button" class="filter-pill" data-group="topic" '
                       f'data-val="{e(slug)}" data-cid="{cid}" aria-pressed="false">{e(lab)}</button>')
    if search:
        out.append('<div class="filter-sep"></div>'
                   f'<label class="filter-search-label" for="{cid}-search" '
                   f'style="position:absolute;left:-9999px">Search within this section</label>'
                   f'<input class="filter-search" id="{cid}-search" type="search" '
                   f'placeholder="Search…" data-cid="{cid}">')
    out.append('</div>')
    return "".join(out)


def hero(eyebrow, title, sub, count_note=""):
    return ('<div class="page-hero">'
            f'<p class="eyebrow">{eyebrow}</p>'
            f'<h2 class="page-title serif">{e(title)}</h2>'
            f'<p class="page-sub">{sub}</p>'
            + (f'<p class="sec-count">{count_note}</p>' if count_note else "")
            + '</div>')


def queue_button(key):
    """Saving to a reading queue is localStorage-only, so the control ships
    hidden and app.js reveals it."""
    return (f'<button type="button" class="queue-btn" data-queue="{e(key)}" '
            f'data-js-only hidden>Save</button>')


# ------------------------------------------------------------------ sections
def sec_overview(D, facts):
    cards = [
        (len(D["pieces"]), "Full Editorial Drafts", "original long-form drafts · status shown per item", "writing", False),
        (len(D["quoteCards"]), "Quote Cards", "30 to 50 per book planned", "quotes", True),
        (len(D["thenVsNow"]), "Then vs. Now", "scientific annotation layer", "thenVsNow", False),
        (len(D["flashcards"]), "Flashcards", "neuroscience quick reference", "flashcards", False),
        (facts["mini"], "Mini-Essays", "a view onto the drafts above, not extra objects", "miniEssays", False),
        (len(D["courseModules"]), "Free University", f'{facts["courses"]} courses · {facts["books"]} books · no gatekeeping', "course", False),
        (len(D["claimSorter"]), "Claim Sorter Deck", "verdicts with the evidence behind them", "claimSorter", False),
        (len(D["eduModules"]), "Teaching Modules", "syllabi for newsrooms and workshops", "modules", False),
        (len(D["documents"]), "Doc of the Week", "primary sources with commentary", "documents", True),
        (len(D["characters"]), "Character Profiles", "the people who made the history", "characters", True),
        (len(D["passages"]), "Passage Spotlights", "letters · chapters · plants", "passages", True),
        (len(D["geography"]), "Geography Series", "where things happened", "geography", True),
        (len(D["bridges"]), "Bridge Pieces", "cross-book connections", "bridges", False),
        (len(D["readingLists"]), "Reading Lists", "companion texts per book", "readingLists", False),
        (len(D["annotations"]), "Science Annotations", "right · wrong · unresolved", "annotations", False),
        (len(D["notebookLM"]), "NotebookLM Packs", "paste-ready for audio generation", "notebookLM", False),
    ]
    colors = ['var(--sienna)', 'var(--forest)', '#4A4A8B', '#4A6741', '#1A4A6B', '#8B6914',
              '#6B4C9A', '#8B3A0F', '#2D5A1B', '#4A4A8B', 'var(--forest)', 'var(--sienna)',
              '#4A6741', '#1A4A6B', '#6B4C9A', '#2D5A1B']
    grid = []
    for i, (n, label, sub, sec, held) in enumerate(cards):
        if held:
            grid.append(
                f'<a class="ov-card ov-card-held" href="#{sec}">'
                f'<span class="ov-n serif" style="color:var(--muted)">0</span>'
                f'<span class="ov-label">{e(label)}</span>'
                f'<span class="ov-sub">{e(sub)}</span>'
                f'<span class="ov-held">Not in this edition. Rights review open. Open for why.</span></a>')
        else:
            grid.append(
                f'<a class="ov-card" href="#{sec}">'
                f'<span class="ov-n serif" style="color:{colors[i]}">{n}</span>'
                f'<span class="ov-label">{e(label)}</span>'
                f'<span class="ov-sub">{e(sub)}</span></a>')

    return (
        '<section class="section" id="overview" aria-labelledby="h-overview">'
        '<div class="page-hero">'
        '<p class="eyebrow">Independent research &amp; learning library</p>'
        '<h1 class="page-title serif" id="h-overview">Psychonaut Bookworm</h1>'
        f'<p class="page-sub">{facts["total"]} published editorial objects in '
        f'{facts["formats"]} types, on {facts["books"]} books. Original drafts, evidence '
        'comparisons, study tools, reading lists and source packs. '
        '<strong>Education, not medical advice.</strong> '
        'What was checked on Oct 13, 2026: every citation on the released pages was checked against '
        'PubMed, Crossref or the known public record. Wrong journals, years, titles and authors were '
        'corrected; sources that could not be found are marked &ldquo;Source not found; under review&rdquo;; '
        'overstated claims, including Rat Park and the DMT entity survey, were regraded; dose amounts '
        'and drug brand names were removed. What remains: an independent check of every factual '
        'statement in the body text, of organizational and press sources, and of claims about 2025 '
        'and 2026 events. These are drafts and study material, not peer-reviewed or licensed work. '
        'Every item shows its own source count and status.</p></div>'
        '<div class="wrap">'
        '<div class="truth-panel"><strong>Everything below is on this page.</strong> '
        'The sections are stacked in reading order. Nothing is loaded on click, and nothing '
        'needs JavaScript to be read. Search, filtering and the saved reading queue are '
        'enhancements layered on top. Five object types are held back while excerpt rights '
        'review is open. The <a href="/provenance/manifest.json">public ledger</a> accounts for '
        f'all {facts["ledger_records"]:,} records: published ones in full, withheld ones counted '
        'by reason. <a href="/governance">The rules and the correction route</a> are public too. '
        'Every item has its own page, linked from the item.</div>'
        f'<div class="ov-grid">{"".join(grid)}</div>'
        f'<p class="page-sub">The counts above are the contents of this page. They sum to '
        f'{facts["card_sum"]} rather than {facts["total"]}, because Mini-Essays is a view onto '
        f'the {facts["mini"]} drafts of that format already counted under Full Editorial Drafts. '
        f'The {facts["total"]} figure counts each object once.</p>'
        '</div></section>')


def sec_research(D, facts):
    idx = facts["indexed"]
    rows = [
        ("Original editorial drafts", len(D["pieces"]),
         "Full text; internal editorial state and source count shown."),
        ("Quote cards", len(D["quoteCards"]),
         "Short excerpts only; item-level permission/fair-use review pending."),
        ("Passage spotlights", len(D["passages"]),
         "Short excerpts only; commentary retained."),
        ("Flashcards", len(D["flashcards"]),
         "Study prompts; citation presence is disclosed, not presumed."),
        ("Then vs. Now", len(D["thenVsNow"]),
         "Evidence comparisons with attached source entries."),
    ]
    table = "".join(f"<tr><td>{e(a)}</td><td>{b}</td><td>{e(c)}</td></tr>" for a, b, c in rows)
    books = sorted({p["book"] for p in D["pieces"] if p.get("book")})
    book_opts = "".join(f"<option>{e(b)}</option>" for b in books)
    return (
        '<section class="section" id="research" aria-labelledby="h-research">'
        + hero("Search · assess · save", "Research Desk",
               f"Search original drafts, evidence comparisons, flashcards, and science "
               f"annotations. Each result exposes its internal status and the number of source "
               f"entries currently attached.").replace('<h2 class="page-title serif">',
                                                       '<h2 class="page-title serif" id="h-research">')
        + '<div class="wrap">'
        '<div class="truth-panel"><strong>What you are searching.</strong> '
        f'{idx} objects are indexed here: original editorial drafts, evidence comparisons, '
        'flashcards and science annotations. Education, not medical advice. Citations were checked '
        'on Oct 13, 2026; body text claims and organizational sources are still under review. Each '
        'result shows its internal status and source count. Quotation cards and passage excerpts are '
        'withheld until an item-level publication basis is recorded.</div>'
        '<div class="research-controls" id="research-controls" data-js-only hidden>'
        '<label for="research-q" style="position:absolute;left:-9999px">Search the library</label>'
        '<input id="research-q" type="search" placeholder="Search titles, books, themes, and text…">'
        '<label for="research-type" style="position:absolute;left:-9999px">Object type</label>'
        '<select id="research-type"><option value="all">All object types</option>'
        '<option>Editorial draft</option><option>Then vs. Now</option>'
        '<option>Flashcard</option><option>Science annotation</option></select>'
        '<label for="research-book" style="position:absolute;left:-9999px">Book</label>'
        f'<select id="research-book"><option value="all">All books</option>{book_opts}</select>'
        '<button type="button" class="queue-btn" id="research-export">Export queue</button>'
        '<button type="button" class="queue-btn" id="research-clear">Clear saved queue</button>'
        '</div>'
        '<p class="research-meta" id="research-controls-note" data-js-only hidden>'
        'Searching filters the sections below in place. Saved items stay only in this browser on '
        'this device; there is no account sync. Use “Clear saved queue” to delete them.</p>'
        '<p class="research-meta" id="research-summary" data-js-only hidden></p>'
        '<p class="page-sub" id="research-noscript-note">Search and the saved reading queue need '
        'JavaScript. Without it the library is still complete on this page: every object is '
        'rendered below, in section order, and your browser’s own find-in-page will search all of '
        'it.</p>'
        '<h3 class="serif" style="margin-top:2.25rem;font-size:1.3rem">Evidence &amp; rights ledger</h3>'
        '<table class="ledger"><thead><tr><th>Object type</th><th>Count</th>'
        f'<th>Public treatment</th></tr></thead><tbody>{table}</tbody></table>'
        '<p class="page-sub" style="margin-top:1rem">Rights note: fair use depends on context and '
        'multiple factors; there is no automatic safe word count. This release uses conservative '
        'excerpts while rights review is incomplete.</p>'
        '</div></section>')


def article(p, i, page=False):
    fmt = p.get("format", "")
    wc = words(p.get("body"))
    themes = " ".join(p.get("themes") or [])
    pull = p.get("pullQuote")
    src = p.get("sources") or []
    summary_pull = ""
    if pull:
        short = pull if len(pull) <= 75 else pull[:75] + "…"
        summary_pull = f'<span class="art-pull">&ldquo;{e(short)}&rdquo;</span>'
    themepills = "".join(f'<span class="theme-pill">{e(t)}</span>'
                         for t in (p.get("themes") or [])[:2])
    body = "".join(f"<p>{e(x)}</p>" for x in paras(p.get("body")))
    srchtml = ""
    if src:
        srchtml = ('<h4 class="card-label">Sources</h4><ul class="src-list">'
                   + "".join(f"<li>{e(s)}</li>" for s in src) + "</ul>")
    return (
        f'<details class="art"{" open" if page else ""} id="draft-{e(p["id"])}" data-obj="Editorial draft" '
        f'data-book="{e(p.get("book",""))}" data-bookslug="{e(p.get("bookSlug",""))}" '
        f'data-format="{e(fmt)}" data-topic="{e(themes)}" data-key="piece:{i}">'
        '<summary>'
        f'<span class="art-spine" style="background:{e(p.get("bookColor","var(--tan)"))}"></span>'
        '<span class="art-body">'
        '<span class="art-meta">'
        f'<span class="art-badge" style="background:{FMT_COLORS.get(fmt,"#6B5E52")}">'
        f'{e(FMT_LABELS.get(fmt, fmt))}</span>'
        f'<span class="art-book">{e(p.get("book",""))}</span>'
        f'<span class="mono">{wc:,} words</span>'
        f'<span class="mono">{len(src)} source entr{"y" if len(src)==1 else "ies"}</span>'
        f'<span class="mono">status: {e(STATUS_TEXT.get(p.get("status"), p.get("status") or "unlabelled"))}</span>'
        '</span>'
        f'<h3 class="art-title serif">{e(p.get("title",""))}</h3>'
        f'{summary_pull}</span>'
        f'<span class="art-right">{themepills}'
        f'<span class="art-open-cue"></span></span>'
        '</summary>'
        '<div class="art-full">'
        + (f'<blockquote>&ldquo;{e(pull)}&rdquo;</blockquote>' if pull else "")
        + body + srchtml
        + ("" if page else queue_button(f"piece:{i}") + permalink(rid("pieces", p)))
        + '</div></details>')


def sec_writing(D, facts):
    fmts = [("all", "All")] + [(f, FMT_LABELS.get(f, f)) for f in facts["format_order"]]
    tabs = []
    for f, lab in fmts:
        n = len(D["pieces"]) if f == "all" else facts["format_counts"][f]
        dot = "" if f == "all" else f'<span class="fmt-dot" style="background:{FMT_COLORS.get(f,"#6B5E52")}"></span>'
        active = " active" if f == "all" else ""
        tabs.append(f'<button type="button" class="fmt-tab{active}" data-cid="writing-f" '
                    f'data-group="format" data-val="{f}" aria-pressed="{"true" if f=="all" else "false"}">'
                    f'{dot}{e(lab)} <span class="tab-count">{n}</span></button>')
    items = "".join(article(p, i) for i, p in enumerate(D["pieces"]))
    return (
        '<section class="section" id="writing" aria-labelledby="h-writing">'
        '<div class="page-hero"><p class="eyebrow">Original Editorial Drafts</p>'
        '<h2 class="page-title serif" id="h-writing">Writing</h2>'
        f'<p class="page-sub">{len(D["pieces"])} full drafts across '
        f'{len(facts["format_order"])} formats, every one of them open on this page. '
        '“Editorial complete” and “editorial ready” are internal workflow states, not '
        'independent proof of publication. The length shown against each draft is the word '
        'count of the text published here, measured at build time.</p></div>'
        f'<div class="fmt-bar" id="writing-f-filterbar" data-target="writing-list" data-js-only '
        f'hidden role="group" aria-label="Filter drafts by format">{"".join(tabs)}</div>'
        + filter_bar("writing-b", "writing-list", book_pills(p["bookSlug"] for p in D["pieces"]), topic_pills(flat(D["pieces"], "themes")), True, "Filter drafts by book and theme")
        + f'<div class="wrap" id="writing-list" data-filterable>{items}'
        '<p class="no-results" data-empty hidden>No drafts match this filter.</p></div></section>')


def sec_mini(D, facts):
    minis = [(i, p) for i, p in enumerate(D["pieces"]) if p.get("format") == "mini-essay"]
    out = []
    for i, m in minis:
        color = m.get("bookColor") or "var(--sienna)"
        out.append(
            f'<article class="card" style="border-left-color:{e(color)}" '
            f'data-book="{e(m.get("book",""))}" data-bookslug="{e(m.get("bookSlug",""))}" '
            f'data-topic="{e(" ".join(m.get("themes") or []))}">'
            '<div style="display:flex;gap:0.75rem;align-items:center;margin-bottom:0.4rem;flex-wrap:wrap">'
            f'<span class="mono" style="color:{e(color)}">{e(m.get("book",""))}</span>'
            f'<span class="mono" style="color:var(--muted)">{words(m.get("body")):,} words</span></div>'
            f'<h3 class="card-title serif">{e(m.get("title",""))}</h3>'
            + (f'<p style="font-style:italic;font-size:0.85rem;color:var(--sienna);line-height:1.55;'
               f'margin-bottom:0.9rem">{e(m["pullQuote"])}</p>' if m.get("pullQuote") else "")
            + "".join(f'<p style="font-size:0.83rem;line-height:1.7;color:var(--muted);'
                      f'margin-bottom:0.7rem">{e(x)}</p>' for x in paras(m.get("body")))
            + f'<p class="mono"><a href="#draft-{e(m["id"])}">Open in Writing</a> &middot; '
            f'<a href="{e(item_path(rid("pieces", m)))}">Open on its own page</a></p>'
            + '</article>')
    lo, hi = facts["mini_words"]
    per_book = facts["mini_per_book"]
    short = [b for b, n in per_book.items() if n < max(per_book.values())]
    perbook_note = (f'{max(per_book.values())} per book for {len(per_book)-len(short)} of the '
                    f'{len(per_book)} books, and {min(per_book.values())} for '
                    f'{e(", ".join(sorted(short)))}, whose fifth is withheld in the ledger for a '
                    'missing item-level source'
                    ) if short else f"{max(per_book.values())} per book"
    return (
        '<section class="section" id="miniEssays" aria-labelledby="h-mini">'
        f'<div class="page-hero"><p class="eyebrow">{len(minis)} essays · {lo} to {hi} words each</p>'
        '<h2 class="page-title serif" id="h-mini">Mini-Essays</h2>'
        f'<p class="page-sub">{len(minis)} essays across {facts["books"]} books, reprinted here '
        f'in full: {perbook_note}. These are the mini-essay-format drafts from Writing shown on '
        f'their own; they are already counted in the {len(D["pieces"])} drafts, not additional '
        'objects.</p></div>'
        + filter_bar("me-f", "me-list", book_pills(m["bookSlug"] for _, m in minis), topic_pills(flat([m for _, m in minis], "themes")), True, "Filter mini-essays")
        + f'<div class="wrap" id="me-list" data-filterable>{"".join(out)}'
        '<p class="no-results" data-empty hidden>No mini-essays match this filter.</p></div></section>')


def tvn_html(t, i, page=False):
        col = STATUS_COLOR.get(t.get("nowStatus"), "var(--muted)")
        lab = STATUS_LABEL.get(t.get("nowStatus")) or t.get("nowStatusBucket") or t.get("nowStatus") or ""
        src = t.get("sources") or []
        return (
            f'<article class="tvn" id="{e(anchor("thenVsNow", t))}" data-obj="Then vs. Now" data-book="{e(t.get("book",""))}" '
            f'data-bookslug="{e(t.get("bookSlug",""))}" data-topic="{e(t.get("nowStatusBucket",""))}" '
            f'data-key="then:{i}">'
            f'<div class="tvn-spine" style="background:{e(t.get("bookColor","var(--tan)"))}"></div>'
            '<div class="tvn-grid">'
            '<div class="tvn-col tvn-col-then">'
            f'<div class="mono" style="margin-bottom:0.35rem">Then ({e(t.get("thenYear",""))}), '
            f'{e(t.get("book",""))}</div>'
            f'<h3 class="tvn-title serif">{e(t.get("title",""))}</h3>'
            f'<div class="tvn-text">{e(t.get("thenClaim",""))}</div></div>'
            '<div class="tvn-col"><div class="tvn-status">'
            f'<div class="tvn-dot" style="background:{col}"></div>'
            f'<span class="mono" style="color:{col}">{e(lab)}</span></div>'
            f'<div class="tvn-now">{e(t.get("nowAssessment") or t.get("nowEvidence") or "")}</div>'
            + ('<h4 class="card-label">Sources</h4><ul class="src-list">'
               + "".join(f"<li>{e(s)}</li>" for s in src) + "</ul>" if src else "")
            + ("" if page else queue_button(f"then:{i}") + permalink(rid("thenVsNow", t)))
            + '</div></div></article>')


def sec_tvn(D, facts):
    out = [tvn_html(t, i) for i, t in enumerate(D["thenVsNow"])]
    return (
        '<section class="section" id="thenVsNow" aria-labelledby="h-tvn">'
        '<div class="page-hero"><p class="eyebrow">The Scientific Annotation Layer</p>'
        '<h2 class="page-title serif" id="h-tvn">Then vs. Now</h2>'
        f'<p class="page-sub">What the books claimed vs. what the science shows now: '
        f'{len(D["thenVsNow"])} comparisons across {facts["books"]} books, each with the source '
        'entries attached to it.</p></div>'
        + filter_bar("tvn-f", "tvn-list", book_pills(t.get("bookSlug") for t in D["thenVsNow"]), topic_pills(flat(D["thenVsNow"], "nowStatusBucket")), True, "Filter evidence comparisons")
        + f'<div class="wrap" id="tvn-list" data-filterable>{"".join(out)}'
        '<p class="no-results" data-empty hidden>No comparisons match this filter.</p></div></section>')


def fc_html(fc, i, page=False):
        bg = "var(--paper)" if i % 2 == 0 else "var(--cream)"
        return (
            f'<tr class="fc-row" id="{e(anchor("flashcards", fc))}" style="background:{bg}" data-obj="Flashcard" '
            f'data-book="{e(fc.get("book",""))}" data-bookslug="{e(fc.get("bookSlug",""))}" '
            f'data-topic="{e(fc.get("category",""))}" data-key="card:{i}">'
            f'<td><div class="fc-q">{e(fc.get("front",""))}</div>'
            f'<div class="fc-cite">{e(fc.get("category",""))}</div></td>'
            f'<td><div class="fc-a">{e(fc.get("back",""))}</div>'
            f'<div class="fc-cite">{e(fc.get("citation","") or "no citation recorded")}</div></td>'
            f'<td><span class="fc-diff" style="background:{DIFF_COLOR.get(fc.get("difficulty"),"var(--muted)")}">'
            f'{e(fc.get("difficulty",""))}</span>'
            + ("" if page else queue_button(f"card:{i}") + permalink(rid("flashcards", fc)))
            + '</td></tr>')


def fc_table(rows_html, tbody_id=""):
    tid = f' id="{tbody_id}" data-filterable' if tbody_id else ""
    return ('<table class="fc-table"><thead><tr>'
            '<th class="fc-th" style="width:35%">Question</th><th class="fc-th">Answer</th>'
            '<th class="fc-th" style="width:130px">Level</th></tr></thead>'
            f'<tbody{tid}>{rows_html}</tbody></table>')


def sec_flashcards(D, facts):
    rows = [fc_html(fc, i) for i, fc in enumerate(D["flashcards"])]
    held = facts["ledger"]["flashcards"]
    return (
        '<section class="section" id="flashcards" aria-labelledby="h-fc">'
        f'<div class="page-hero"><p class="eyebrow">{len(D["flashcards"])} Cards Published</p>'
        '<h2 class="page-title serif" id="h-fc">Flashcards</h2>'
        '<p class="page-sub">Study prompts for review, not a substitute for source checking. '
        'Citations appear only where present; question and answer are both printed below. '
        f'The ledger holds {held["records"]} flashcard records; the other {held["withheld"]} are '
        'withheld until each carries an item-level source.</p></div>'
        + filter_bar("fc-f", "fc-list", book_pills(fc.get("bookSlug") for fc in D["flashcards"]), topic_pills(flat(D["flashcards"], "category")), True, "Filter flashcards")
        + '<div class="wrap">' + fc_table("".join(rows), "fc-list") +
        '<p class="no-results" data-empty hidden>No cards match this filter.</p>'
        '<p class="page-sub" style="margin-top:1.25rem">A timed sprint over these cards is '
        'available under Free University; it shuffles the rows printed here.</p>'
        '</div></section>')


def bridge_html(b, page=False):
        slug_label = dict(BOOK_PILLS)
        tags = "".join(
            f'<span class="bridge-book-tag" style="border-left-color:'
            f'{e((b.get("bookColors") or ["var(--tan)"])[i] if i < len(b.get("bookColors") or []) else "var(--tan)")}">'
            f'{e(slug_label.get(s, s))}</span>' for i, s in enumerate(b.get("books") or []))
        src = b.get("sources") or []
        return (
            f'<article class="bridge" id="{e(anchor("bridges", b))}" data-obj="Bridge piece" '
            f'data-bookslug="{e(" ".join(b.get("books") or []))}" '
            f'data-topic="{e(" ".join(b.get("themes") or []))}">'
            f'<div class="bridge-head"><div class="bridge-books">{tags}</div>'
            f'<h3 class="card-title serif">{e(b.get("title",""))}</h3></div>'
            f'<p class="bridge-premise" style="padding-top:1rem">{e(b.get("premise",""))}</p>'
            f'<div class="bridge-body">{"".join(f"<p>{e(x)}</p>" for x in paras(b.get("body")))}'
            + ('<h4 class="card-label">Sources</h4><ul class="src-list">'
               + "".join(f"<li>{e(s)}</li>" for s in src) + "</ul>" if src else "")
            + ("" if page else permalink(rid("bridges", b)))
            + '</div></article>')


def sec_bridges(D, facts):
    out = [bridge_html(b) for b in D["bridges"]]
    return (
        '<section class="section" id="bridges" aria-labelledby="h-bridges">'
        '<div class="page-hero"><p class="eyebrow">Cross-Book Connections</p>'
        '<h2 class="page-title serif" id="h-bridges">Bridge Pieces</h2>'
        f'<p class="page-sub">{len(D["bridges"])} pieces connecting books to each other: the '
        'arguments that only become visible when two books are read together. Printed in '
        'full.</p></div>'
        + filter_bar("bridges-f", "bridges-list", book_pills(flat(D["bridges"], "books")), topic_pills(flat(D["bridges"], "themes")), True, "Filter bridge pieces")
        + f'<div class="wrap" id="bridges-list" data-filterable>{"".join(out)}'
        '<p class="no-results" data-empty hidden>No bridge pieces match this filter.</p>'
        '</div></section>')


def rl_html(r, page=False):
        entries = "".join(
            '<div class="rl-entry">'
            f'<span class="rl-order">{e(en.get("type","text"))}</span><div>'
            f'<div class="rl-title">{e(en.get("title",""))}</div>'
            f'<div class="rl-author">{e(en.get("author",""))}'
            + (f' &middot; {e(en["year"])}' if en.get("year") else "")
            + f'</div><div class="rl-why">{e(en.get("whyRead",""))}</div></div></div>'
            for en in (r.get("entries") or []))
        return (
            f'<article class="rl" id="{e(anchor("readingLists", r))}" style="border-left:3px solid {e(r.get("bookColor","var(--tan)"))}" '
            f'data-obj="Reading list" data-book="{e(r.get("book",""))}" '
            f'data-bookslug="{e(r.get("bookSlug",""))}">'
            f'<div class="rl-head"><h3 class="card-title serif">{e(r.get("book",""))}</h3>'
            f'<p class="sec-count">{len(r.get("entries") or [])} companion texts</p></div>'
            f'<div class="rl-intro">{e(r.get("introduction",""))}</div>{entries}'
            + ("" if page else permalink(rid("readingLists", r)))
            + '</article>')


def sec_reading_lists(D, facts):
    out = [rl_html(r) for r in D["readingLists"]]
    return (
        '<section class="section" id="readingLists" aria-labelledby="h-rl">'
        f'<div class="page-hero"><p class="eyebrow">1 Per Book: Companion Texts</p>'
        '<h2 class="page-title serif" id="h-rl">Companion Reading Lists</h2>'
        f'<p class="page-sub">What to read before, alongside, and after each of the '
        f'{facts["books"]} books, with a specific reason for every pairing. '
        f'{facts["rl_entries"]} entries in all.</p></div>'
        + filter_bar("readinglists-f", "rl-list", book_pills(r["bookSlug"] for r in D["readingLists"]), None, True, "Filter reading lists")
        + f'<div class="wrap" id="rl-list" data-filterable>{"".join(out)}'
        '<p class="no-results" data-empty hidden>No reading lists match this filter.</p>'
        '</div></section>')


def ann_html(a, i, page=False):
        return (
            f'<article class="ann" id="{e(anchor("annotations", a))}" data-obj="Science annotation" '
            f'data-bookslug="{e(a.get("bookSlug",""))}" data-topic="{e(a.get("verdict",""))}" '
            f'data-key="annotation:{i}">'
            '<div class="ann-head">'
            f'<span class="ann-verdict" style="background:{VERDICT_COLOR.get(a.get("verdict"),"var(--muted)")}">'
            f'{e(verdict_label(a.get("verdict")))}</span>'
            f'<h3 class="ann-claim">{e(a.get("claim",""))}</h3></div>'
            '<div class="ann-grid">'
            f'<div class="ann-col"><div class="ann-col-label">Claim source</div>'
            f'{e(a.get("claimSource",""))}</div>'
            '<div class="ann-col"><div class="ann-col-label">Current evidence &middot; confidence: '
            f'{e(a.get("confidence",""))}</div>{e(a.get("currentEvidence",""))}'
            + (f'<div class="ann-col-label" style="margin-top:.6rem">Citation</div>{e(a["citation"])}'
               if a.get("citation") else "")
            + ("" if page else queue_button(f"annotation:{i}") + permalink(rid("annotations", a)))
            + '</div></div></article>')


def sec_annotations(D, facts):
    out = [ann_html(a, i) for i, a in enumerate(D["annotations"])]
    topics = verdict_pills(D["annotations"])
    return (
        '<section class="section" id="annotations" aria-labelledby="h-ann">'
        '<div class="page-hero"><p class="eyebrow">Right / Wrong / Unresolved</p>'
        '<h2 class="page-title serif" id="h-ann">Scientific Annotation Layer</h2>'
        f'<p class="page-sub">{len(D["annotations"])} claims, one drawn from each of the '
        f'{facts["books"]} books, checked against current evidence and marked confirmed, '
        'partially confirmed, refuted, unresolved or untestable, with the confidence stated. '
        'The verdicts are editorial readings of the cited literature, not a systematic '
        'review.</p></div>'
        + filter_bar("annotations-f", "ann-list", book_pills(a.get("bookSlug") for a in D["annotations"]), topics, True, "Filter annotations")
        + f'<div class="wrap" id="ann-list" data-filterable>{"".join(out)}'
        '<p class="no-results" data-empty hidden>No annotations match this filter.</p>'
        '</div></section>')


def nlm_html(n, page=False):
        qs = "".join(
            f'<li class="nlm-q"><span class="nlm-q-num">{i+1}</span>'
            f'<span class="nlm-q-text">{e(q)}</span></li>'
            for i, q in enumerate(n.get("focusQuestions") or []))
        return (
            f'<article class="nlm" id="pack-{e(n["id"])}" '
            f'style="border-left:3px solid {e(n.get("bookColor","var(--tan)"))}" '
            f'data-obj="NotebookLM pack" data-book="{e(n.get("book",""))}" '
            f'data-bookslug="{e(n.get("bookSlug",""))}">'
            '<div class="nlm-head"><div>'
            f'<div class="nlm-series">{e(n.get("series",""))}'
            + (f' &middot; Episode {e(n["episodeNumber"])}' if n.get("episodeNumber") else "")
            + '</div>'
            f'<h3 class="nlm-title">{e(n.get("episodeTitle",""))}</h3></div>'
            f'<span class="nlm-len">{e(n.get("targetLength",""))}</span></div>'
            '<div class="nlm-body">'
            f'<div class="nlm-instructions">{e(n.get("notebookLMInstructions",""))}</div>'
            + (('<details class="nlm-src"><summary>Full source material</summary>'
                f'<div class="nlm-src-body">{e(n.get("sourceMaterial",""))}</div></details>')
               if (n.get("sourceMaterial") or "").strip() else
               '<p class="card-body"><strong>Source material pending review.</strong> The sources this brief names are listed below.</p>')
            + ('<h4 class="card-label">Sources</h4><ul class="src-list">'
               + "".join(f"<li>{e(s)}</li>" for s in n["sources"]) + "</ul>" if n.get("sources") else "")
            + 
            f'<div class="nlm-qs"><h4 class="card-label">Focus questions</h4><ol style="list-style:none;padding:0;margin:0">{qs}</ol></div>'
            + (f'<div class="nlm-guest">Suggested guests: {e(n["suggestedGuests"])}</div>'
               if n.get("suggestedGuests") else "")
            + ("" if page else permalink(rid("notebookLM", n)))
            + '</div></article>')


def sec_notebooklm(D, facts):
    out = [nlm_html(n) for n in D["notebookLM"]]
    return (
        '<section class="section" id="notebookLM" aria-labelledby="h-nlm">'
        '<div class="page-hero"><p class="eyebrow">Paste → Generate → Audio</p>'
        '<h2 class="page-title serif" id="h-nlm">NotebookLM Source Packs</h2>'
        f'<p class="page-sub">{len(D["notebookLM"])} packs. Paste one into NotebookLM as a source '
        'document, then use the focus questions to generate an audio conversation. Each pack is '
        'self-contained and printed in full here (instructions, source material and questions), '
        'so it can be copied without JavaScript.</p></div>'
        + filter_bar("nlm-f", "nlm-list", book_pills(n.get("bookSlug") for n in D["notebookLM"]), None, True, "Filter source packs")
        + f'<div class="wrap" id="nlm-list" data-filterable>{"".join(out)}'
        '<p class="no-results" data-empty hidden>No packs match this filter.</p>'
        '</div></section>')


def mod_html(m, D, facts, page=False):
    by_id = {p["id"]: p for p in D["pieces"]}
    by_title = {(p.get("title") or "").strip().lower(): p for p in D["pieces"]}
    fc_by = {c["id"]: c for c in D["flashcards"]}
    cs_by = {c["id"]: c for c in D["claimSorter"]}
    color = THEME_COLOR.get(m.get("theme"), "var(--ink)")
    readings = []
    for i, r in enumerate(m.get("readings") or []):
        p = by_id.get(r.get("id"))
        if not p and r.get("id"):
            # A few readings carry an older id for a draft that is released
            # under another one. Match on title, against released drafts only.
            p = by_title.get((r.get("title") or "").strip().lower())
        if r.get("id") and not p:
            # The reading points at a draft that is not released. Print
            # nothing of it: no title, no book, no note.
            readings.append(
                '<li class="reading-row">'
                f'<span class="reading-n" style="color:{color}">{i+1}</span>'
                '<span style="flex:1;min-width:0;color:var(--muted)">'
                'A reading that is not published in this edition.</span></li>')
            continue
        title = p["title"] if p else (r.get("title") or "")
        book = p["book"] if p else (r.get("book") or r.get("bookSlug") or "")
        href = item_path(rid("pieces", p)) if (p and page) else (f"#draft-{p['id']}" if p else "")
        link = (f'<a href="{e(href)}">{e(title)}</a>' if p else e(title))
        readings.append(
            '<li class="reading-row">'
            f'<span class="reading-n" style="color:{color}">{i+1}</span>'
            '<span style="flex:1;min-width:0">'
            f'<span class="art-badge" style="background:'
            f'{FMT_COLORS.get(r.get("type"),"#6B5E52")}">{e(r.get("type","reading"))}</span> '
            f'<strong class="serif">{link}</strong>'
            + (f'<span class="mono" style="display:block">&rarr; {e(book)}</span>' if book else "")
            + (f'<span style="font-size:0.82rem;color:var(--muted);font-style:italic;'
               f'line-height:1.5;display:block">{e(r["note"])}</span>' if r.get("note") else "")
            + '</span></li>')

    mod_fc = [fc_by[i] for i in (m.get("flashcardIds") or []) if i in fc_by]
    mod_cs = [cs_by[i] for i in (m.get("claimIds") or []) if i in cs_by]
    tools = []
    if mod_fc:
        tools.append('<h4>Flashcards for this module</h4><ul class="src-list" '
                     'style="margin-bottom:1.25rem">' + "".join(
            f'<li style="font-family:inherit;font-size:0.85rem;color:var(--ink);'
            f'margin-bottom:.5rem"><strong>{e(c["front"])}</strong><br>'
            f'<span style="color:var(--muted)">{e(c["back"])}</span>'
            + (f'<br><span class="fc-cite">{e(c["citation"])}</span>' if c.get("citation") else "")
            + f' <a class="mono" href="#flashcards">see all cards</a></li>'
            for c in mod_fc) + '</ul>')
    if mod_cs:
        tools.append('<h4>Claims to sort</h4>' + "".join(
            f'<details class="cs-item"><summary>{e(c["claim"])}</summary>'
            f'<p style="margin-top:.6rem"><span class="ann-verdict" style="background:'
            f'{VERDICT_COLOR.get(c.get("verdict"),"var(--muted)")}">'
            f'{e(verdict_label(c.get("verdict")))}</span></p>'
            f'<p style="font-size:.85rem;line-height:1.7;color:var(--muted)">{e(c.get("explanation",""))}</p>'
            f'<p class="fc-cite">{e(c.get("source",""))}</p></details>'
            for c in mod_cs))
    tools.append(
        '<p class="held-note">The cards and claims above are the whole of this module\u2019s '
        'practice material. Timed versions of both drills are in '
        '<a href="#drills">Study drills</a> at the end of this section; they shuffle exactly '
        'what is printed here and add nothing. The timeline, comparison and '
        'source-identifier drills are not available in this edition: they run on the '
        f'timeline ({facts["ledger"]["timeline"]["records"]} records) and quote-card '
        f'({facts["ledger"]["quoteCards"]["records"]} records) corpora, which are withheld '
        'in full. <a href="/governance">See the publication rules</a>.</p>')

    packs = []
    for label, pack in (("Preview Podcast", m.get("previewPack")),
                        ("Evidence Podcast", m.get("evidencePack"))):
        if not pack:
            continue
        packs.append(
            '<details class="pack">'
            f'<summary>{e(pack.get("label") or label)}: {e(pack.get("format",""))}</summary>'
            f'<pre>{e(pack.get("text",""))}</pre></details>')
    book_packs = [p for p in D["notebookLM"] if p.get("bookSlug") in (m.get("bookSlugs") or [])]
    if book_packs:
        # The full text of these lives once, in the NotebookLM section. Reprinting it
        # inside every module that touches the same book only duplicates the page.
        packs.append(
            '<p style="font-size:0.82rem;color:var(--muted);margin:1rem 0 .4rem">'
            'Book-specific deep dives for this module\u2019s texts, printed in full under '
            '<a href="#notebookLM">NotebookLM Source Packs</a>:</p><ul class="src-list">'
            + "".join(f'<li style="font-family:inherit;font-size:0.85rem;margin-bottom:.3rem">'
                      f'<a href="#pack-{e(p["id"])}">{e(p.get("episodeTitle",""))}</a>, '
                      f'{e(p.get("book",""))} · {e(p.get("series",""))}</li>'
                      for p in book_packs) + '</ul>')

    html_out = (
        f'<details class="mod" id="course-{e(m["id"])}" data-obj="Course module" '
        f'data-bookslug="{e(" ".join(m.get("bookSlugs") or []))}" '
        f'data-topic="{e(m.get("theme",""))}">'
        '<summary>'
        f'<span style="width:6px;flex-shrink:0;background:{color}"></span>'
        f'<span style="width:48px;flex-shrink:0;display:flex;align-items:center;'
        f'justify-content:center;font-family:monospace;font-size:0.75rem;font-weight:700;'
        f'color:{color};border-right:1px solid var(--rule)">{e(m.get("number",""))}</span>'
        '<span style="flex:1;padding:1rem 1.25rem">'
        f'<h3 class="serif" style="font-size:1rem;font-weight:700;margin-bottom:0.2rem">'
        f'{e(m.get("title",""))}</h3>'
        f'<span style="font-size:0.82rem;color:var(--muted);font-style:italic;display:block;'
        f'margin-bottom:0.3rem">{e(m.get("subtitle",""))}</span>'
        f'<span class="mono" style="color:{color}">{e(m.get("theme",""))} · '
        f'{e(m.get("duration",""))} · {len(m.get("readings") or [])} readings</span></span>'
        '</summary>'
        '<div class="mod-panel"><h4>Central question</h4>'
        f'<p style="font-size:0.95rem;line-height:1.75;max-width:720px">{e(m.get("question",""))}</p></div>'
        f'<div class="mod-panel"><h4>Curated readings: {len(m.get("readings") or [])} pieces</h4>'
        '<p style="font-size:0.82rem;color:var(--muted);margin-bottom:1rem">Read in order. '
        'Every published piece is on this page, and the titles link straight to the draft.</p>'
        f'<ol style="list-style:none;padding:0;margin:0">{"".join(readings)}</ol></div>'
        f'<div class="mod-panel"><h4>Practice</h4>{"".join(tools)}</div>'
        '<div class="mod-panel"><h4>Discussion provocation</h4>'
        f'<p style="font-size:0.95rem;line-height:1.75;font-style:italic;max-width:720px">'
        f'{e(m.get("discussionProvocation",""))}</p>'
        '<p class="mono">Write 150 words. Share with one colleague before opening the next module.</p>'
        '<h4 style="margin-top:1.25rem">Production artifact</h4>'
        f'<p style="font-size:0.9rem;line-height:1.7;max-width:720px">{e(m.get("artifactPrompt",""))}</p>'
        f'<label for="art-{e(m["id"])}" class="mono">Draft it here. This stays in your browser</label>'
        f'<textarea id="art-{e(m["id"])}" data-artifact="{e(m["id"])}" rows="8" '
        'style="width:100%;max-width:720px;padding:0.875rem;background:#fff;'
        'border:1px solid var(--rule);font-family:inherit;font-size:0.875rem;line-height:1.7;'
        'resize:vertical;box-sizing:border-box"></textarea>'
        f'<p class="mono" data-wordcount-for="{e(m["id"])}" data-js-only hidden>0 words</p>'
        f'<p data-js-only hidden><label class="mono"><input type="checkbox" '
        f'data-module-complete="{e(m["id"])}"> Mark this module complete '
        '(remembered in this browser)</label></p></div>'
        f'<div class="mod-panel"><h4>NotebookLM podcast packs</h4>'
        '<p style="font-size:0.82rem;color:var(--muted);margin-bottom:1rem;max-width:640px">'
        'Copy any pack below, paste it into '
        '<a href="https://notebooklm.google.com" rel="noopener">NotebookLM</a> as a source, '
        'then generate the conversation. Module packs frame the course question; book packs '
        'go deep on individual texts.</p>'
        f'{"".join(packs)}</div>'
        + ("" if page else permalink(rid("courseModules", m)))
        + '</details>')
    if page:
        html_out = html_out.replace(' class="mod" ', ' class="mod" open ', 1)
        html_out = html_out.replace('href="#', 'href="/#')
    return html_out


def sec_course(D, facts):
    mods = D["courseModules"]
    blocks = [mod_html(m, D, facts) for m in mods]

    lo, hi = facts["reading_range"]
    return (
        '<section class="section" id="course" aria-labelledby="h-course">'
        '<div style="background:linear-gradient(135deg,#1A1410 0%,#2D5A1B 100%);padding:3rem 2rem 2.5rem">'
        f'<p style="font-family:monospace;font-size:0.6rem;letter-spacing:0.12em;'
        f'text-transform:uppercase;color:#D4C0A5;margin-bottom:0.5rem">The Psychonaut Bookworm · '
        f'Free University · {facts["books"]} Books · {len(mods)} Courses</p>'
        '<h2 id="h-course" style="font-family:\'Playfair Display\',serif;'
        'font-size:clamp(1.6rem,4vw,2.6rem);color:#F2EDE4;margin-bottom:0.75rem;line-height:1.2">'
        'Free University</h2>'
        f'<p style="color:rgba(242,237,228,0.75);max-width:640px;line-height:1.7;font-size:0.95rem">'
        f'{len(mods)} courses across {facts["books"]} books. Each course has a central question, '
        f'{lo} to {hi} curated readings, the flashcards and claims it draws on, a discussion '
        'provocation, a writing artifact, and two NotebookLM podcast packs. Free. Permanent. '
        'No gatekeeping. Every word of it is on this page.</p></div>'
        '<p class="mono" id="course-progress" data-js-only hidden '
        'style="padding:1rem 2.5rem 0"></p>'
        f'<div class="wrap" id="course-list" data-filterable>{"".join(blocks)}'
        '<div id="drills" style="margin-top:3rem;padding-top:2rem;border-top:1px solid var(--rule)">'
        '<h3 class="serif" style="font-size:1.3rem;margin-bottom:.5rem">Study drills</h3>'
        '<p class="page-sub">Two timed drills run over the material already printed on this '
        f'page: the {len(D["flashcards"])} flashcards in the Flashcards section, and the '
        f'{len(D["claimSorter"])} claims in the Claim Sorter Deck. They shuffle and quiz; they '
        'publish nothing new. Drills that ran on the withheld timeline and quote-card corpora '
        'are not offered, because that material is not published.</p>'
        '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:1rem" data-js-only hidden>'
        '<button type="button" class="queue-btn" id="drill-flashcards">⚡ Flashcard sprint</button>'
        '<button type="button" class="queue-btn" id="drill-claims">🎯 Claim sorter</button>'
        '</div>'
        '<div id="drill-stage" style="margin-top:1.25rem"></div>'
        '</div></div>'
        '</section>')


def claim_html(c, page=False):
        canon = verdict_label(c.get("verdict"))
        own = (c.get("verdictLabel") or "").strip()
        nuance = (f' <span class="mono">recorded as “{e(own)}”</span>'
                  if own and own.lower() != canon.lower() else "")
        return (
            f'<details class="cs-item"{" open" if page else ""} id="{e(anchor("claimSorter", c))}" data-obj="Claim" data-book="{e(c.get("book",""))}" '
            f'data-bookslug="{e(c.get("bookSlug",""))}" data-topic="{e(c.get("verdict",""))}" '
            f'data-verdict="{e(canon)}">'
            f'<summary>{e(c.get("claim",""))}</summary>'
            f'<p style="margin-top:.6rem"><span class="ann-verdict" style="background:'
            f'{VERDICT_COLOR.get(c.get("verdict"),"var(--muted)")}">{e(canon)}</span>'
            f'{nuance} <span class="mono">{e(c.get("book",""))}</span></p>'
            f'<p style="font-size:.85rem;line-height:1.7;color:var(--muted)">'
            f'{e(c.get("explanation",""))}</p>'
            f'<p class="fc-cite">{e(c.get("source",""))}</p>'
            + ("" if page else permalink(rid("claimSorter", c)))
            + '</details>')


def sec_claimsorter(D, facts):
    items = "".join(claim_html(c) for c in D["claimSorter"])
    topics = verdict_pills(D["claimSorter"])
    return (
        '<section class="section" id="claimSorter" aria-labelledby="h-cs">'
        '<div class="page-hero"><p class="eyebrow">The deck behind the sorting drill</p>'
        '<h2 class="page-title serif" id="h-cs">Claim Sorter Deck</h2>'
        f'<p class="page-sub">{len(D["claimSorter"])} claims taken from the books, each with the '
        'verdict, the reasoning, and the source it rests on. These are counted in the '
        f'{facts["total"]} published objects and used to be reachable only inside the Free '
        'University drill; they are printed here so they can be read, cited and checked. Open a '
        'claim to see the verdict, or read it cold first and sort it yourself.</p></div>'
        + filter_bar("cs-f", "cs-list", book_pills(c.get("bookSlug") for c in D["claimSorter"]), topics, True, "Filter claims")
        + f'<div class="wrap" id="cs-list" data-filterable>{items}'
        '<p class="no-results" data-empty hidden>No claims match this filter.</p></div></section>')


def edu_html(m, page=False):
        return (
            f'<article class="card" id="{e(anchor("eduModules", m))}" style="border-left-color:{e(m.get("bookColor","var(--tan)"))}" '
            f'data-obj="Teaching module" data-book="{e(m.get("book",""))}" '
            f'data-bookslug="{e(m.get("bookSlug",""))}">'
            '<div style="display:flex;gap:0.75rem;align-items:center;margin-bottom:0.4rem;flex-wrap:wrap">'
            f'<span class="mono">{e(m.get("format",""))}</span>'
            f'<span class="mono">{e(m.get("audience",""))}</span>'
            f'<span class="mono">{e(m.get("book",""))}</span></div>'
            f'<h3 class="card-title serif">{e(m.get("title",""))}</h3>'
            '<h4 class="card-label">Objectives</h4><ul class="src-list">'
            + "".join(f'<li style="font-family:inherit;font-size:0.85rem;line-height:1.6;'
                      f'color:var(--muted);margin-bottom:.3rem">{e(o)}</li>'
                      for o in (m.get("objectives") or []))
            + '</ul><h4 class="card-label">Outline</h4>'
            + "".join(f'<p class="card-body"><strong>{e(s.get("section",""))}</strong>: '
                      f'{e(s.get("content",""))}</p>' for s in (m.get("outline") or []))
            + ('<h4 class="card-label">Required reading</h4><ul class="src-list">'
               + "".join(f"<li>{e(s)}</li>" for s in m["requiredReading"]) + "</ul>"
               if m.get("requiredReading") else "")
            + ("" if page else permalink(rid("eduModules", m)))
            + '</article>')


def sec_edumodules(D, facts):
    out = [edu_html(m) for m in D["eduModules"]]
    return (
        '<section class="section" id="modules" aria-labelledby="h-mods">'
        '<div class="page-hero"><p class="eyebrow">Workshops &amp; Reading Guides</p>'
        '<h2 class="page-title serif" id="h-mods">Teaching Modules</h2>'
        f'<p class="page-sub">{len(D["eduModules"])} syllabi with objectives, section outlines '
        f'and required reading. They are counted in the {facts["total"]} published objects and '
        'were previously not reachable from any tab on this site; they are published here.</p></div>'
        + f'<div class="wrap" id="edu-list" data-filterable>{"".join(out)}</div></section>')


def sec_withheld(sec_id, eyebrow, title, sub, what, ledger):
    return (
        f'<section class="section" id="{sec_id}" aria-labelledby="h-{sec_id}">'
        f'<div class="page-hero"><p class="eyebrow">{eyebrow}</p>'
        f'<h2 class="page-title serif" id="h-{sec_id}">{e(title)}</h2>'
        f'<p class="page-sub">{sub}</p></div>'
        '<div class="wrap"><p class="held-note">'
        + WITHHELD_NOTE.format(what=what)
        + f' The ledger holds {ledger["records"]} records of this type: '
          f'{ledger["published"]} published in this edition, {ledger["withheld"]} withheld.'
          '</p></div></section>')


# --------------------------------------------------------------- release gate
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RELEASE_FIELDS = ("id", "recordId", "releasedAt", "hold", "postUrls", "longFormUrl", "sourcePageUrl")


def today_honolulu():
    return datetime.datetime.now(HONOLULU).date()


def load_releases(path):
    """Read data/releases.json and refuse anything malformed, so a typo can
    never release a record by accident."""
    rows = json.load(open(path, encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit(f"{path}: expected a list of release records")
    out, problems, seen = {}, [], set()
    for n, row in enumerate(rows):
        missing = [f for f in RELEASE_FIELDS if f not in row]
        if missing:
            problems.append(f"entry {n}: missing {', '.join(missing)}")
            continue
        if row["recordId"] in out:
            problems.append(f"entry {n}: duplicate recordId {row['recordId']}")
        if row["id"] in seen:
            problems.append(f"entry {n}: duplicate id {row['id']}")
        seen.add(row["id"])
        if row["id"] != shared_id(row["recordId"]):
            problems.append(f"entry {n}: id {row['id']} should be {shared_id(row['recordId'])}")
        if row["releasedAt"] and not DATE_RE.match(row["releasedAt"]):
            problems.append(f"{row['id']}: releasedAt must be YYYY-MM-DD or empty")
        if not isinstance(row["hold"], bool):
            problems.append(f"{row['id']}: hold must be true or false")
        if not isinstance(row["postUrls"], list):
            problems.append(f"{row['id']}: postUrls must be a list")
        out[row["recordId"]] = row
    if problems:
        raise SystemExit(f"{path} is invalid:\n  " + "\n  ".join(problems))
    return out


def is_released(row, today):
    """Released means: an entry exists, hold is false, and releasedAt is a
    date on or before today in Honolulu. No entry, or no date, means hidden."""
    if not row or row.get("hold") is not False:
        return False
    d = row.get("releasedAt") or ""
    if not DATE_RE.match(d):
        return False
    return datetime.date.fromisoformat(d) <= today


def gate(D, releases, today):
    return {k: ([x for x in v if is_released(releases.get(rid(k, x)), today)]
                if isinstance(v, list) else v)
            for k, v in D.items()}


def released_ids(releases, today):
    return sorted(i for i, row in releases.items() if is_released(row, today))


# ------------------------------------------------------------ public ledger
def public_ledger(manifest, releases, today, out_dir):
    """The served ledger lists released records in full. Withheld records are
    counted by reason and nothing else: no id, no title, no excerpt, no
    sources. Ids are left out because a writing id is its title as a slug."""
    os.makedirs(os.path.join(out_dir, "provenance"), exist_ok=True)
    # The public edition of this repository (build/export_public.py) carries only released
    # records and records the withheld ones as counts by reason in provenance/withheld.json.
    extra_path = os.path.join(ROOT, "provenance", "withheld.json")
    extra = (json.load(open(extra_path, encoding="utf-8")).get("corpora", {})
             if os.path.exists(extra_path) else {})
    corpora = []
    for c in manifest["corpora"]:
        name = c["corpus"]
        src = json.load(open(os.path.join(ROOT, "provenance", f"{name}.json"), encoding="utf-8"))
        shown, reasons = [], {}
        for r in src["records"]:
            if is_released(releases.get(r["recordId"]), today):
                shown.append(r)
            else:
                why = r.get("suppressionReason") or "not released yet"
                reasons[why] = reasons.get(why, 0) + 1
        carried = extra.get(name, {})
        for why, n in carried.get("byReason", {}).items():
            reasons[why] = reasons.get(why, 0) + n
        held = sum(reasons.values())
        doc = {
            "schemaVersion": src.get("schemaVersion"),
            "corpus": name,
            "records": shown,
            "withheld": {
                "count": held,
                "byReason": reasons,
                "note": "Withheld records are counted here and not listed. Their ids, titles, "
                        "excerpts and sources are not published.",
            },
        }
        with open(os.path.join(out_dir, "provenance", f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        corpora.append({**c, "records": len(src["records"]) + carried.get("count", 0), "published": len(shown),
                        "withheld": held})
    m = dict(manifest)
    m["corpora"] = corpora
    m["publicLedger"] = ("Each corpus file lists its released records in full and counts its "
                         "withheld records by reason. Release is decided by data/releases.json "
                         "in the source repository.")
    with open(os.path.join(out_dir, "provenance", "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    return {c["corpus"]: c for c in corpora}


# --------------------------------------------------------------- item pages
def item_title(key, x):
    t = {"pieces": x.get("title"), "thenVsNow": x.get("title"), "flashcards": x.get("front"),
         "claimSorter": x.get("claim"), "bridges": x.get("title"),
         "readingLists": f"Reading list: {x.get('book', '')}", "annotations": x.get("claim"),
         "notebookLM": x.get("episodeTitle"), "courseModules": x.get("title"),
         "eduModules": x.get("title")}.get(key)
    return (t or x["id"]).strip()


def short(text, n=90):
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "..."


def books_of(x):
    out = []
    for k in ("bookSlug", "books", "bookSlugs"):
        v = x.get(k)
        if isinstance(v, list):
            out.extend(v)
        elif v:
            out.append(v)
    return [b for b in out if b]


def has_sources(key, x):
    """True when the record names at least one source of its own."""
    for f in ("sources", "citation", "source", "requiredReading"):
        v = x.get(f)
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, list) and any(isinstance(s, str) and s.strip() for s in v):
            return True
    if key == "readingLists":
        return bool(x.get("entries"))
    if key == "courseModules":
        return bool(x.get("readings"))
    if key == "notebookLM":
        return bool((x.get("sourceMaterial") or "").strip())
    return False


def item_body(key, x, i, D, facts):
    if key == "pieces":
        return article(x, i, page=True)
    if key == "thenVsNow":
        return tvn_html(x, i, page=True)
    if key == "flashcards":
        return fc_table(fc_html(x, 0, page=True))
    if key == "claimSorter":
        return claim_html(x, page=True)
    if key == "bridges":
        return bridge_html(x, page=True)
    if key == "readingLists":
        return rl_html(x, page=True)
    if key == "annotations":
        return ann_html(x, i, page=True)
    if key == "notebookLM":
        return nlm_html(x, page=True)
    if key == "courseModules":
        return mod_html(x, D, facts, page=True)
    if key == "eduModules":
        return edu_html(x, page=True)
    raise KeyError(key)


def related(key, x, D):
    """Cross-links between released records only. Each entry: (heading, [(key, item)])."""
    groups = []
    books = set(books_of(x))
    by_title = {(p.get("title") or "").strip().lower(): p for p in D["pieces"]}
    by_id = {p["id"]: p for p in D["pieces"]}

    def module_drafts(m):
        out = []
        for r in m.get("readings") or []:
            p = by_id.get(r.get("id")) or (by_title.get((r.get("title") or "").strip().lower())
                                           if r.get("id") else None)
            if p and p not in out:
                out.append(p)
        return out

    if key == "pieces":
        mods = [m for m in D["courseModules"] if x in module_drafts(m)]
        groups.append(("Course modules that assign this draft", [("courseModules", m) for m in mods]))
    if key == "courseModules":
        groups.append(("Drafts assigned in this module", [("pieces", p) for p in module_drafts(x)]))
        fcs = [c for c in D["flashcards"] if c["id"] in (x.get("flashcardIds") or [])]
        groups.append(("Flashcards in this module", [("flashcards", c) for c in fcs]))
        css = [c for c in D["claimSorter"] if c["id"] in (x.get("claimIds") or [])]
        groups.append(("Claims in this module", [("claimSorter", c) for c in css]))
    if key == "flashcards":
        mods = [m for m in D["courseModules"] if x["id"] in (m.get("flashcardIds") or [])]
        groups.append(("Course modules that use this card", [("courseModules", m) for m in mods]))
    if key == "claimSorter":
        mods = [m for m in D["courseModules"] if x["id"] in (m.get("claimIds") or [])]
        groups.append(("Course modules that use this claim", [("courseModules", m) for m in mods]))
    if books:
        if key != "pieces":
            groups.append(("Drafts on the same book",
                           [("pieces", p) for p in D["pieces"] if p.get("bookSlug") in books]))
        for k, label in (("readingLists", "Reading list for this book"),
                         ("notebookLM", "NotebookLM packs on this book"),
                         ("bridges", "Bridge pieces that use this book"),
                         ("annotations", "Science annotations on this book"),
                         ("thenVsNow", "Then vs. Now comparisons on this book"),
                         ("claimSorter", "Claims from this book")):
            if k == key:
                continue
            hits = [y for y in D[k] if books & set(books_of(y))]
            groups.append((label, [(k, y) for y in hits]))
    return [(h, items) for h, items in groups if items]


def page_shell(head_src, title, desc, canonical):
    style = re.search(r"<style>.*?</style>", head_src, re.S).group(0)
    fonts = re.search(r'<link href="https://fonts.googleapis.com[^>]*>', head_src).group(0)
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>{e(title)}</title>\n'
        f'<meta name="description" content="{e(desc)}">\n'
        f'<link rel="canonical" href="{e(canonical)}">\n'
        '<link rel="icon" type="image/png" sizes="64x64" href="/favicon.png">\n'
        '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">\n'
        '<meta property="og:type" content="article">\n'
        '<meta property="og:site_name" content="The Psychonaut Bookworm">\n'
        f'<meta property="og:title" content="{e(title)}">\n'
        f'<meta property="og:description" content="{e(desc)}">\n'
        f'<meta property="og:url" content="{e(canonical)}">\n'
        f'<meta property="og:image" content="{BASE}/og-image.png">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        f'{fonts}\n{style}\n'
        '<style>.item-links{max-width:860px;margin:2.5rem auto 0;padding:0 2rem}'
        '.item-links h2{font-family:\'Playfair Display\',serif;font-size:1.3rem;margin:1.5rem 0 .6rem}'
        '.item-links dl{display:grid;grid-template-columns:minmax(110px,160px) 1fr;gap:.55rem 1rem;'
        'font-size:.88rem;line-height:1.6}.item-links dt{font-family:\'JetBrains Mono\',monospace;'
        'font-size:.62rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding-top:.2rem}'
        '.item-links ul{list-style:none;padding:0;margin:0 0 .4rem}.item-links li{font-size:.86rem;'
        'line-height:1.55;margin-bottom:.3rem}.item-links a,.item-wrap a{color:var(--forest)}'
        '.pager{display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap;margin:2rem 0;'
        'font-size:.85rem}.item-wrap{max-width:1100px;margin:0 auto;padding:1.5rem 2rem}'
        '@media (max-width:600px){.item-links,.item-wrap{padding:0 16px}.item-links dl{grid-template-columns:1fr}}'
        '</style>\n</head>\n<body>\n')


def item_page(key, x, i, D, facts, releases, prev, nxt, head_src, backlinks=()):
    record_id = rid(key, x)
    row = releases[record_id]
    title = item_title(key, x)
    label = TYPE_LABEL[key]
    url = BASE + item_path(record_id)
    desc = f"{label} in the Psychonaut Bookworm library by RN Collins: {short(title, 140)}"

    def li_link(k, y):
        return (f'<li><a href="{e(item_path(rid(k, y)))}">{e(short(item_title(k, y), 110))}</a> '
                f'<span class="mono">{e(TYPE_LABEL[k])}</span></li>')

    posts = [u for u in row.get("postUrls") or [] if u]
    posts_html = ("<ul>" + "".join(f'<li><a href="{e(u)}" rel="noopener">{e(u)}</a></li>'
                                   for u in posts) + "</ul>"
                  if posts else "No post is recorded for this item yet.")
    src = row.get("sourcePageUrl") or ""
    src_html = (f'<a href="{e(src)}" rel="noopener">The sources for this item on RN Collins '
                'Selected Work</a>' if src else
                "There is no source page for this item on RN Collins Selected Work yet. "
                "The sources it rests on are listed on this page.")
    lf = row.get("longFormUrl") or ""
    drafts_by_path = {item_path(rid("pieces", p)): p for p in D["pieces"]}
    lf_path = lf[len(BASE):] if lf.startswith(BASE + "/") else ""
    if key == "pieces":
        lf_html = "This page is the full draft."
    elif lf_path in drafts_by_path:
        lf_html = (f'<a href="{e(lf_path)}">{e(drafts_by_path[lf_path]["title"])}</a>, '
                   'the editorial draft this item belongs with')
    elif lf and not lf_path:
        lf_html = f'<a href="{e(lf)}" rel="noopener">{e(lf)}</a>'
    else:
        lf_html = ("No single long-form draft is recorded for this item. "
                   "Related drafts, where there are any, are listed below.")
    pager = (
        '<nav class="pager" aria-label="Previous and next items">'
        + (f'<a href="{e(item_path(rid(*prev)))}">Previous: {e(short(item_title(*prev), 70))}</a>'
           if prev else '<span></span>')
        + '<a href="/">Gallery index</a>'
        + (f'<a href="{e(item_path(rid(*nxt)))}">Next: {e(short(item_title(*nxt), 70))}</a>'
           if nxt else '<span></span>')
        + '</nav>')
    groups = related(key, x, D)
    if backlinks:
        groups.append(("Other pages in this library that link here", list(backlinks)))
    rel = "".join(f'<h2>{e(h)}</h2><ul>{"".join(li_link(k, y) for k, y in items)}</ul>'
                  for h, items in groups)
    body = (
        '<a class="skip-link" href="#main-content">Skip to the item</a>'
        '<nav aria-label="Site"><a href="/" style="text-decoration:none;color:inherit">'
        '<span class="brand serif">Psychonaut Bookworm</span></a>'
        f'<a class="mono" href="/" style="color:var(--muted)">Gallery index, '
        f'{facts["total"]} published objects</a></nav>'
        '<main id="main-content">'
        '<div class="page-hero">'
        f'<p class="eyebrow">{e(label)} &middot; <span class="mono">{e(record_id)}</span></p>'
        f'<h1 class="page-title serif">{e(title)}</h1>'
        '<p class="page-sub"><strong>Education, not medical advice.</strong> Drafts and study '
        'material from an independent research library. Citations on this page were checked on '
        'Oct 13, 2026; claims in the body text and organizational sources are still under review. '
        '<a href="/governance">What was checked</a>.</p>'
        + ('' if has_sources(key, x) else '<p class="page-sub"><strong>Sources pending review.</strong></p>')
        + '</div>'
        f'<div class="item-wrap">{item_body(key, x, i, D, facts)}</div>'
        '<section class="item-links" aria-label="Links for this item">'
        + pager
        + '<h2>Links for this item</h2><dl>'
        f'<dt>Posts</dt><dd>{posts_html}</dd>'
        f'<dt>Source page</dt><dd>{src_html}</dd>'
        f'<dt>Long-form</dt><dd>{lf_html}</dd>'
        f'<dt>Gallery</dt><dd><a href="/#{e(anchor(key, x))}">See it in the gallery index</a></dd>'
        f'<dt>Project</dt><dd><a href="{PORTFOLIO}">About this library on RN Collins Selected '
        'Work</a></dd>'
        f'<dt>Corrections</dt><dd><a href="/governance">Publication rules and the correction '
        'form</a></dd></dl>'
        + rel + pager +
        '</section></main>'
        '<footer style="background:var(--ink);color:var(--paper);padding:2rem;margin-top:3rem;'
        'font-size:.8rem;line-height:1.7"><div style="max-width:1100px;margin:0 auto">'
        'Education, not medical advice. Psychonaut Bookworm, an independent editorial project built and published by RN Collins. '
        'All book titles, author names and quotations remain the property of their rights holders. '
        f'<a style="color:var(--tan)" href="{PORTFOLIO}">RN Collins Selected Work</a></div></footer>'
        '</body>\n</html>\n')
    return page_shell(head_src, f"{short(title, 80)} | Psychonaut Bookworm", desc, url) + body


PAGER_RE = re.compile(r'<nav class="pager".*?</nav>', re.S)


def item_links(page):
    """The item pages a page links to, leaving out the previous/next pager."""
    return set(re.findall(r'href="(/item/[^"#?]+)"', PAGER_RE.sub("", page)))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def sitemap(seq, releases, today):
    rows = [(f"{BASE}/", today.isoformat(), "1.0"), (f"{BASE}/governance", today.isoformat(), "0.8")]
    for k, x in seq:
        rows.append((BASE + item_path(rid(k, x)), releases[rid(k, x)]["releasedAt"], "0.6"))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"  <url><loc>{e(u)}</loc><lastmod>{d}</lastmod><priority>{p}</priority></url>\n"
                      for u, d, p in rows)
            + "</urlset>\n")


NOT_FOUND = (
    '<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    '<meta name="robots" content="noindex"><title>Not found | Psychonaut Bookworm</title>'
    '<style>body{margin:0;background:#F2EDE4;color:#1A1410;font:16px/1.6 Georgia,serif}'
    'main{max-width:640px;margin:0 auto;padding:80px 16px}a{color:#2D5A1B}</style></head>'
    '<body><main><h1>Not found</h1><p>There is no published page at this address.</p>'
    '<p><a href="/">Go to the gallery index</a></p></main></body></html>\n')

STATIC = ["app.js", "favicon.png", "apple-touch-icon.png", "og-image.png", "robots.txt",
          "governance.html"]


# ------------------------------------------------------------------- verify
def verify(head, tail, D, facts):
    """A published number that disagrees with the data is a build failure, not
    a thing to be noticed later by a reader."""
    problems = []
    total = facts["total"]
    for label, text in (("build/head.html", head), ("build/tail.html", tail)):
        for n in re.findall(r"(\d[\d,]*) published (?:editorial )?objects", text):
            if int(n.replace(",", "")) != total:
                problems.append(f'{label}: claims "{n} published objects", data has {total}')
        for n in re.findall(r"(\d+) books", text):
            if int(n) != facts["books"]:
                problems.append(f'{label}: claims "{n} books", data has {facts["books"]}')
    if problems:
        raise SystemExit("build aborted — published counts disagree with the data:\n  "
                         + "\n  ".join(problems))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the Psychonaut Bookworm site into dist/.")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--releases", default=os.path.join(ROOT, "data", "releases.json"))
    ap.add_argument("--date", help="build as of this Honolulu date, YYYY-MM-DD")
    ap.add_argument("--released-ids", action="store_true",
                    help="print the ids released as of the date, one per line, and exit")
    args = ap.parse_args(argv)
    today = datetime.date.fromisoformat(args.date) if args.date else today_honolulu()
    releases = load_releases(args.releases)

    if args.released_ids:
        print("\n".join(released_ids(releases, today)))
        return

    full = json.load(open(os.path.join(ROOT, "data", "library.json"), encoding="utf-8"))
    unknown = [rid(k, x) for k, v in full.items() if isinstance(v, list) for x in v
               if rid(k, x) not in releases]
    if unknown:
        print(f"note: {len(unknown)} library records have no entry in releases.json and stay "
              f"hidden: {', '.join(unknown[:10])}", file=sys.stderr)
    D = gate(full, releases, today)
    manifest = json.load(open(os.path.join(ROOT, "provenance", "manifest.json"), encoding="utf-8"))

    out_dir = os.path.abspath(args.out)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    ledger = public_ledger(manifest, releases, today, out_dir)

    minis = [p for p in D["pieces"] if p.get("format") == "mini-essay"]
    mini_counts = {}
    for p in minis:
        mini_counts[p["book"]] = mini_counts.get(p["book"], 0) + 1
    fmt_counts = {}
    for p in D["pieces"]:
        fmt_counts[p["format"]] = fmt_counts.get(p["format"], 0) + 1
    order = ["flagship", "series", "deep-dive", "policy", "mini-essay",
             "science-journalism", "passage-spotlight"]
    fmt_order = [f for f in order if f in fmt_counts] + \
                [f for f in fmt_counts if f not in order]

    facts = {
        "total": sum(len(v) for v in D.values() if isinstance(v, list)),
        "formats": len([v for v in D.values() if isinstance(v, list) and v]),
        "books": len({p["book"] for p in D["pieces"]}),
        "courses": len(D["courseModules"]),
        "mini": len(minis),
        "mini_per_book": mini_counts,
        "mini_words": (min((words(p["body"]) for p in minis), default=0),
                       max((words(p["body"]) for p in minis), default=0)),
        "format_counts": fmt_counts,
        "format_order": fmt_order,
        "reading_range": (min((len(m["readings"]) for m in D["courseModules"]), default=0),
                          max((len(m["readings"]) for m in D["courseModules"]), default=0)),
        "rl_entries": sum(len(r.get("entries") or []) for r in D["readingLists"]),
        "indexed": len(D["pieces"]) + len(D["thenVsNow"]) + len(D["flashcards"]) + len(D["annotations"]),
        "card_sum": sum(len(v) for v in D.values() if isinstance(v, list)) + len(minis),
        "ledger": ledger,
        "ledger_records": sum(c["records"] for c in ledger.values()),
    }

    head = open(os.path.join(BUILD, "head.html"), encoding="utf-8").read()
    tail = open(os.path.join(BUILD, "tail.html"), encoding="utf-8").read()
    head = head.replace("{{TOTAL}}", str(facts["total"]))
    tail = tail.replace("{{TOTAL}}", str(facts["total"]))
    verify(head, tail, D, facts)

    nav_items = [
        ("overview", "🌿 Overview", None),
        ("research", "🔎 Research Desk", None),
        ("writing", "✏️ Writing", len(D["pieces"])),
        ("miniEssays", "📝 Mini-Essays", facts["mini"]),
        ("thenVsNow", "🔬 Then vs. Now", len(D["thenVsNow"])),
        ("flashcards", "🃏 Flashcards", len(D["flashcards"])),
        ("claimSorter", "🎯 Claim Deck", len(D["claimSorter"])),
        ("bridges", "🌉 Bridge Pieces", len(D["bridges"])),
        ("readingLists", "📋 Reading Lists", len(D["readingLists"])),
        ("annotations", "🧪 Science Annotations", len(D["annotations"])),
        ("notebookLM", "🎙️ NotebookLM Packs", len(D["notebookLM"])),
        ("course", "📚 Free University", len(D["courseModules"])),
        ("modules", "🎓 Teaching Modules", len(D["eduModules"])),
        ("held", "🔒 Held Back", 5),
    ]
    tabs = "".join(
        f'<a class="tab" href="#{sid}">{label}'
        + (f' <span class="tab-count">{n}</span>' if n is not None else "")
        + "</a>" for sid, label, n in nav_items)

    nav = (
        '<a class="skip-link" href="#main-content">Skip to the library</a>'
        '<nav aria-label="Site">'
        '<a href="#overview" style="display:flex;flex-direction:column;gap:0.05rem;'
        'text-decoration:none;color:inherit">'
        '<span class="brand serif" style="font-size:1rem;font-weight:900;letter-spacing:-0.01em">'
        'RN Collins</span>'
        '<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.5rem;'
        'letter-spacing:0.12em;text-transform:uppercase;color:var(--muted)">🍄 Psychonaut '
        'Bookworm &nbsp;·&nbsp; Independent RN Collins research library</span></a>'
        f'<span class="mono" style="color:var(--muted)">{facts["total"]} published objects · '
        f'{facts["books"]} books</span></nav>'
        f'<div class="tab-bar" id="tabBar" role="navigation" aria-label="Library sections">{tabs}</div>')

    held_intro = (
        '<section class="section" id="held" aria-labelledby="h-held">'
        '<div class="page-hero"><p class="eyebrow">Five object types, none of them published</p>'
        '<h2 class="page-title serif" id="h-held">Held Back Pending Rights Review</h2>'
        '<p class="page-sub">These five types exist in the provenance ledger and are not '
        'published in this edition. The sections below say what each one is and why it is '
        'withheld; none of them renders withheld material.</p></div></section>')

    withheld = held_intro + "".join([
        sec_withheld("quotes", "Withheld", "Quote Cards",
                     "The lines that make people stop scrolling, with the context that makes "
                     "them mean something.", "Quote cards", ledger["quoteCards"]),
        sec_withheld("documents", "Withheld", "Document of the Week",
                     "The primary sources the books are built on: congressional testimony, "
                     "laboratory notebooks and ancient hymns, with editorial context.",
                     "Documents of the Week", ledger["documents"]),
        sec_withheld("characters", "Withheld", "Character Profiles",
                     "Not bios. Close readings of why each figure is essential to understanding "
                     "their book.", "Character profiles", ledger["characters"]),
        sec_withheld("passages", "Withheld", "Passage Spotlights",
                     "Individual passages given their own editorial treatment: context, "
                     "significance, and commentary.", "Passage spotlights", ledger["passages"]),
        sec_withheld("geography", "Withheld", "Geography Series",
                     "The physical places in these books: what happened there and what they "
                     "look like now.", "Geography series entries", ledger["geography"]),
    ])

    body = (
        nav
        + '<main id="main-content">'
        + sec_overview(D, facts)
        + sec_research(D, facts)
        + sec_writing(D, facts)
        + sec_mini(D, facts)
        + sec_tvn(D, facts)
        + sec_flashcards(D, facts)
        + sec_claimsorter(D, facts)
        + sec_bridges(D, facts)
        + sec_reading_lists(D, facts)
        + sec_annotations(D, facts)
        + sec_notebooklm(D, facts)
        + sec_course(D, facts)
        + sec_edumodules(D, facts)
        + withheld
        + '</main>'
    )

    out = head + body + tail + '<script src="/app.js" defer></script>\n</body>\n</html>'
    write(os.path.join(out_dir, "index.html"), out)

    seq = [(k, x) for k in ITEM_ORDER for x in D[k]]
    positions = {k: {id(x): n for n, x in enumerate(D[k])} for k in ITEM_ORDER}

    def render(n, backlinks=()):
        k, x = seq[n]
        prev = seq[n - 1] if n > 0 else None
        nxt = seq[n + 1] if n + 1 < len(seq) else None
        return item_page(k, x, positions[k][id(x)], D, facts, releases, prev, nxt, head, backlinks)

    # Two passes, so every link between item pages runs both ways. The first
    # pass renders each page; any page that another page links to, without
    # linking back, then gets a list of those pages. The previous and next
    # links are left out of this: they are the reading order, not a reference.
    paths = [item_path(rid(k, x)) for k, x in seq]
    at = {p: n for n, p in enumerate(paths)}
    pages = [render(n) for n in range(len(seq))]
    out_links = [item_links(pg) for pg in pages]
    incoming = {n: set() for n in range(len(seq))}
    for n, links in enumerate(out_links):
        for target in links:
            if target in at and at[target] != n:
                incoming[at[target]].add(n)
    for n in range(len(seq)):
        missing = sorted(src for src in incoming[n] if paths[src] not in out_links[n])
        if missing:
            pages[n] = render(n, [seq[src] for src in missing])
    for n, (k, x) in enumerate(seq):
        write(os.path.join(out_dir, "item", rid(k, x) + ".html"), pages[n])

    for name in STATIC:
        shutil.copyfile(os.path.join(ROOT, name), os.path.join(out_dir, name))
    write(os.path.join(out_dir, "sitemap.xml"), sitemap(seq, releases, today))
    write(os.path.join(out_dir, "404.html"), NOT_FOUND)

    size = len(out)
    print(f"build date (Honolulu): {today.isoformat()}")
    print(f"released: {len(seq)} of {len(releases)} records in data/releases.json")
    print(f"dist/index.html: {size:,} bytes; {len(seq)} item pages")
    print(f"objects rendered: {facts['total']} "
          f"(pieces {len(D['pieces'])}, thenVsNow {len(D['thenVsNow'])}, "
          f"flashcards {len(D['flashcards'])}, claimSorter {len(D['claimSorter'])}, "
          f"bridges {len(D['bridges'])}, readingLists {len(D['readingLists'])}, "
          f"annotations {len(D['annotations'])}, notebookLM {len(D['notebookLM'])}, "
          f"courseModules {len(D['courseModules'])}, eduModules {len(D['eduModules'])})")


if __name__ == "__main__":
    main()
