# flight-price-tracker

**Dashboard: https://ngzzzho.github.io/flight-price-tracker/**

Multi-year study: for fixed HKG→Japan peak-season round trips, how many days
before departure is the cheapest time to buy? A GitHub Action queries Google
Flights daily (via [fast-flights](https://github.com/AWeirdDev/flights) query
builder + our own payload parser), appends every matching offer to CSV, and
fails loudly if results look broken — because a silent gap can never be
backfilled.

## How it works

- One round-trip query per (trip × destination × query_type), HKD, 1 adult.
- `query_type=nonstop` (`max_stops=0`, both legs nonstop) for every
  destination; plus `query_type=any` for destinations that allow connections.
- The airline whitelist is applied **server-side** (Google's airline filter,
  constrains both legs including the priced-in return) **and re-checked
  client-side** per segment.
- "TYO" is queried as the Google city code — one query covers NRT + HND.
- Results merge Google's "best" + main lists, deduped by flight numbers.

## Data files

`data/pricelog.csv` — one row per offer per day. Columns:

| column | meaning |
|---|---|
| `log_date` | HKT date of the run |
| `trip_name`, `dest` | e.g. `XMAS-2026`, `CTS` |
| `days_to_depart` | depart_date − log_date |
| `price_hkd` | **round-trip total** for this outbound + cheapest whitelisted return |
| `airlines` | segment carriers, e.g. `CX` or `KE` or `CX+NH` |
| `flight_numbers` | outbound chain, e.g. `CX580` or `CI924>CI104` |
| `out_stops`, `via` | outbound stops and connection airport(s) |
| `dest_airport` | actual arrival airport (`NRT`/`HND` for TYO) |
| `out_dep`, `out_arr`, `out_duration_min` | outbound schedule |
| `query_type` | `nonstop` or `any` |
| `in_best` | 1 if Google ranked it in "best flights" |

`data/dailysummary.csv` — one row per (day × trip × dest): `status`,
offer counts, `min_price_any`, `min_price_nonstop` (+ which flights), notes.

**Known limitation:** Google's round-trip list prices outbound options with the
cheapest matching return baked in — per-offer **return flight details are not
exposed** (capturing them would need ~20× more queries). Outbound details are
complete, and the whitelist still constrains the return leg server-side.

## Health & alerts

Per (trip × dest) status in `dailysummary.csv`:

- `OK` — enough offers.
- `SUSPECT` — fewer priced offers than `min_offers` in config → **run fails**.
- `NO_RESULT` — zero offers. Fails the run only if `min_offers > 0`; for thin
  routes (AKJ, HKD have `min_offers = 0`) zero is normal at long range —
  recorded, but no alarm.
- `ERROR` — query/parse failed after 3 retries → **run fails**.

A failed run still commits whatever it collected (status rows included), then
marks the workflow failed so GitHub emails the repo owner. Check
github.com → Settings → Notifications → System → Actions: email for
failed workflows enabled (default on).

The CSVs are the second alarm: gaps in `log_date` = missed runs.

> GitHub disables cron workflows after 60 days without repo activity; the
> daily data commits count as activity, so this stays alive on its own.

## Google Sheets

In a blank sheet (File → Import won't auto-refresh; `IMPORTDATA` re-fetches
roughly hourly):

```
=IMPORTDATA("https://raw.githubusercontent.com/ngzzzho/flight-price-tracker/main/data/dailysummary.csv")
```

and on another tab, the same for `pricelog.csv`.

**Days-to-departure curve** (the study's money chart), per trip × dest:
1. On the summary tab, Insert → Pivot table. Rows: `days_to_depart`
   (sort descending). Columns: `dest`. Values: `min_price_any` → MIN.
   Filter: `trip_name` = one trip; `status` = OK.
2. Insert → Chart → Line. X-axis `days_to_depart` descending = time flowing
   toward departure; the minimum of the curve answers "when to buy".

## Adding next season (each autumn)

Edit `tracker/config.py` → `TRIPS`: add rows, keep old ones (past trips are
skipped automatically). Adjust `DESTINATIONS` thresholds if route reality
changed. Commit. Done — no other steps.

## Run locally

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
FAST_SLEEP=1 .venv/bin/python -m tracker.fetch
```

## Accepted caveats

- Runner IP is US-based; currency is pinned to HKD but fares may differ
  slightly from HK-based results. The study measures **relative trends**.
- Google shows mild price jitter between back-to-back identical queries;
  daily cadence + same query shape keeps the series comparable.
- LCC fares exclude bags, CX includes — adjust at analysis time.
- Offers Google lists as "price unavailable" are counted (`unpriced`) but not
  logged as rows.
- Carrier codes are marketing carriers as shown by Google (operating carrier
  for all whitelisted HK/JP/TW/KR airlines in practice).

## Future phases (not built)

- Phase 2: Travelpayouts Data API as redundant second pipeline.
- Phase 3: UO / HB official-site low-fare endpoints for promo fares.
- Archive old-season CSV rows if files get heavy.
