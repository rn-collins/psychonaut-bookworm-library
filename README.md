# The Psychonaut Bookworm: Research & Learning Library (open edition)

An independent research and learning library across psychedelic literature. The live site publishes 460 editorial objects drawn from a 1,664-record provenance ledger, each with its source visibility and rights-review state, plus a saved research queue and a correction form.

**Live site:** https://psychonaut-bookworm.vercel.app
**Governance and the ledger:** https://psychonaut-bookworm.vercel.app/governance
**Built by:** [RN Collins](https://rn-selected-work.vercel.app/work/psychonaut-bookworm)

It is drafts and study material, not peer-reviewed or licensed work. Every page carries "Education, not medical advice." Every citation on the released pages was checked on 13 October 2026; the record is in [`CITATIONS-Oct13.md`](CITATIONS-Oct13.md).

## What this repository is

This is the open edition of the project. It holds everything needed to rebuild the live site from scratch: the build, the tests, the governance page, and the 460 records that are released.

It does not hold the other 1,204 records. They are withheld on the live site pending source and rights review (five object types are withheld in full pending excerpt-rights review: quote cards, documents of the week, character profiles, passage spotlights and the geography series). A public repository would publish exactly what the site holds back, so those records stay in the private source repository. Here they appear only as counts by reason in `provenance/withheld.json`, with no id, title, excerpt or source. The site you build from this repository is byte-identical to the live one.

## How a record becomes public

`data/releases.json` is the only gate. A record is public when `hold` is `false` and `releasedAt` is today or earlier in Pacific/Honolulu. Any other record is left out of everything the build writes: the index, its item page (which returns 404), the sitemap, the public ledger and the search text.

| Field | Meaning |
|---|---|
| `id` | The shared id, `psychonaut-bookworm/<slug>`, used by [RN Collins Selected Work](https://rn-selected-work.vercel.app) for the same piece. |
| `recordId` | The provenance ledger id, `<corpus>/<id>`. The item page is `/item/<recordId>`. |
| `releasedAt` | Release date in Pacific/Honolulu, `YYYY-MM-DD`, or empty. |
| `hold` | `true` keeps the record hidden whatever its date. |
| `postUrls` | Links to posts about the piece. |
| `longFormUrl` | The editorial draft the piece belongs with. |
| `sourcePageUrl` | Its sources page on Selected Work. |

## Build and test

Standard library Python only, no dependencies.

```sh
python3 build/build.py                      # builds dist/ for today in Honolulu
python3 build/build.py --date 2026-11-01    # builds as if it were that day
python3 build/build.py --released-ids       # prints what is released today
python3 build/sync_releases.py --check      # fails when data/releases.json is out of date
python3 build/test_release_gate.py          # checks the gate, the links and that nothing withheld leaks
python3 -m http.server 8000 --directory dist
```

Locally, item pages and `/governance` need their `.html` extension; Vercel's `cleanUrls` removes it in production.

| Path | What it is |
|---|---|
| `data/library.json` | The content of the released objects. |
| `data/releases.json` | The release record for every public entry. |
| `data/citation-links.json` | Verified links for citations, keyed by the citation text. |
| `provenance/*.json` | The ledger records for released items, with their sources and rights basis. |
| `provenance/withheld.json` | Counts of withheld records by reason. Nothing else about them. |
| `build/build.py` | Writes `dist/`: the index, one page per released item, the public ledger, the sitemap and a 404 page. |
| `build/verify_citation_links.py` | Re-checks every entry of `data/citation-links.json` against Crossref, the DOI resolver, PubMed and the web. Needs the network. |
| `build/export_public.py` | Writes this open edition from the private source repository, then refuses to finish if any withheld id or text is in the output. |
| `governance.html` | The rule that decides what is public, and how to ask for a correction. |

## Citation links

`data/citation-links.json` maps a citation, written exactly as it appears in `data/library.json`, to the place it can be checked: a DOI, a PubMed record, or a web address. The build turns each citation that has an entry into a link, on the index and on every item page. A citation with no entry prints as plain text. Nothing is guessed, and a citation marked "Source not found; under review" is never linked. A source string that joins several citations with a semicolon is split there, and each part is looked up on its own.

Each entry records when it was verified (`verified`) and what was found (`matched`). A DOI is added only when Crossref and the DOI resolver both return the work and its first author, year and title match the citation. `python3 build/verify_citation_links.py` re-checks the whole file against those services (it needs the network, so it is not part of the test). `python3 build/test_release_gate.py` checks that every mapped citation occurs in the released data, that every DOI, PubMed and web address is well formed, that every link on a built page comes from the map, and that a build with an empty map differs only by the links.

Every item page links to its posts, its sources page, its long-form draft, its place in the gallery index, the previous and next items, and related items from the same book or course module. Links run both ways, and the build refuses to finish if a count in the page shell disagrees with the data.

## Corrections

Corrections are accepted through [`/governance`](https://psychonaut-bookworm.vercel.app/governance) on the live site. The two serverless functions behind its forms forward to a private service, so they stay in the source repository.

## Deployment

The live site is built and served by Vercel from the private source repository with `python3 build/build.py`, output in `dist/` (see `vercel.json`). This repository is a published copy: it is regenerated whenever a record is released, so its history is a series of release snapshots.

## License

Apache-2.0. See [LICENSE](LICENSE).
