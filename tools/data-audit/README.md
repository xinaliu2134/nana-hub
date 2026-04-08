# Venue Data Audit Toolkit

Reusable scripts for auditing venue coordinates in Kids Explorer HTML files
(Holland, and the 11 other country sites that share the same `STATIC_NL_VENUES`
data format).

## Why this exists

April 2026 audit revealed that **0 out of 86** indoor playground coordinates
in `holland-kids-explorer.html` were accurate — worst case was 27 km off
(Monkey Town Doetinchem). Similar accuracy issues spanned theme parks, zoos,
museums, nature reserves, and playgrounds.

This toolkit fixes these systemic issues and makes the same audit repeatable
for any country site.

## Workflow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  1. Extract  │ ──▶ │  2. Geocode  │ ──▶ │   3. Apply   │
│  by category │     │  (3 sources) │     │  patches     │
└──────────────┘     └──────────────┘     └──────────────┘
                            │
                            ├─ Nominatim (OSM, free, 1 req/s)
                            ├─ Photon (Komoot, lenient rate)
                            ├─ Wikipedia API (famous venues)
                            └─ Brand scrapers (chains)
```

## Scripts

### `audit.py` — main auditor

Extracts venues of given category markers, geocodes each via Nominatim +
Photon fallback, compares with existing coordinates, and produces a JSON
patch plan.

```bash
python3 tools/data-audit/audit.py holland-kids-explorer.html \
  --categories indoor_playground theme_park zoo museum \
  --out /tmp/audit.json
```

### `apply_patches.py` — patch applier

Takes a patch plan and applies lat/lon updates in place, keyed by venue ID.

```bash
python3 tools/data-audit/apply_patches.py holland-kids-explorer.html /tmp/audit.json
```

### `wiki_geocode.py` — Wikipedia coordinate fetcher

For famous venues (museums, national parks, well-known attractions) that
have Wikipedia articles with geo coordinates. Queries the Wikipedia API for
`action=query&prop=coordinates`, tries English first then Dutch.

```bash
python3 tools/data-audit/wiki_geocode.py \
  --ids 30,34,42,43 \
  --titles "NEMO Science Museum" "Naturalis Biodiversity Center" \
           "Tropenmuseum" "Kunstmuseum Den Haag" \
  --file holland-kids-explorer.html
```

### `scrape_monkeytown.py` / `scrape_ballorig.py` — chain scrapers

Fetches the canonical list of store locations from brand websites, extracts
street/postcode/city via structured data (JSON-LD for Ballorig, Google Maps
`daddr=` URL param for Monkey Town), then geocodes via Nominatim.

Use these as templates when adding support for new chains (You Jump,
Bounce Valley, Klimbos Fun Forest, Race Planet, GlowGolf — all still TODO).

## Data sources precedence

1. **Brand official website** (highest — for chains) — see scrapers
2. **Wikipedia API** (famous venues) — `wiki_geocode.py`
3. **Nominatim** (street-address queries) — `audit.py`
4. **Photon** (fuzzy brand/name queries, non-chain) — `audit.py`
5. **Manual curation** (fallback when all else fails)

## Rate limits (respect these)

- **Nominatim**: 1 req/sec, identify with User-Agent. Violating triggers
  temporary 403 (30+ min cooldown).
- **Photon**: More lenient, 0.4-0.5 s between requests is fine.
- **Wikipedia API**: 0.4 s between requests.
- **Brand websites**: 1 s between requests.

## Accuracy targets

- **Chain venues** (Monkey Town, Ballorig, etc.): **<50m** — scrape the brand site
- **Famous venues** (museums, national parks): **<100m** — Wikipedia
- **Street-addressed venues**: **<200m** — Nominatim with full address
- **Name-only venues**: **<2 km** — Photon fuzzy match
- **Reject** any Photon/Nominatim result that shifts a venue more than 50 km
  (likely wrong match — investigate manually)

## Auditing a new country site

1. Copy the country's HTML to a work directory
2. Run `audit.py` across all categories (~10 min for 600 venues)
3. Review the distance distribution (usually 0% <100m if data was eyeballed)
4. Apply patches, commit as `fix(data): audit <country> coordinates`
5. Run chain scrapers for each brand present in that country
6. Run `wiki_geocode.py` for the 10-20 most famous venues
7. Verify the JS array still parses: `node -e "eval(...)"`
8. Push and visually spot-check a few venues on the live map

## Known gotchas

- **Apostrophes in names**: Dutch place names like "'s-Hertogenbosch" use
  leading apostrophes. Source HTML uses double-quoted strings for these
  entries: `name:"Ballorig 's-Hertogenbosch"`. Extract regex must handle
  both quote styles.
- **Closed venues**: Some DB entries are no longer on the brand's site.
  Verify via the brand's current `vestigingen` page before adding new
  entries — then delete the stale ones. Don't match ambiguously.
- **Renamed venues**: Tropenmuseum → Wereldmuseum Amsterdam (2023),
  Gemeentemuseum → Kunstmuseum Den Haag (2019). Wikipedia redirects handle
  these, but DB name still needs manual update.
- **Wrong city in DB**: Ontdekhoek was listed as Amsterdam but actually in
  Rotterdam. Sea Life "Amsterdam" is actually in Scheveningen. Cross-check
  suspicious matches against the official venue website.

## History

- 2026-04-07: Level A Nominatim audit for 86 indoor playgrounds
- 2026-04-08: Level B brand scrapes (Monkey Town 51, Ballorig 36)
- 2026-04-08: Tier 1 audit (theme parks, zoos, aquariums, museums)
- 2026-04-08: Tier 2/3/4 audit (outdoor, activities, playgrounds)
- 2026-04-08: Wikipedia fallback for 18 famous venues
- 2026-04-08: Toolkit codified at `tools/data-audit/`
