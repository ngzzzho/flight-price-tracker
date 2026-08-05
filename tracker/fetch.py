"""Daily price fetch.

Queries Google Flights (via fast-flights' query builder + fetcher, with our own
payload parser), appends one row per offer to data/pricelog.csv and one row per
(trip x destination) to data/dailysummary.csv, then exits non-zero if any
destination looks broken so GitHub Actions emails the owner.

Run from the repo root:  python -m tracker.fetch
Env:
  FAST_SLEEP=1   short sleeps/backoff (local testing only)
"""

import csv
import json
import os
import random
import sys
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from selectolax.lexbor import LexborHTMLParser
from fast_flights import FlightQuery, Passengers, create_query, fetch_flights_html

from . import config


class ParseShapeError(Exception):
    """Google's embedded payload no longer matches the expected shape."""


def _hm(t):
    # midnight hours/minutes arrive as null: [null, 45] means 00:45, [7] means 07:00
    h = t[0] if len(t) > 0 and t[0] is not None else 0
    m = t[1] if len(t) > 1 and t[1] is not None else 0
    return h, m


def _iso(d, t):
    h, m = _hm(t)
    return f"{d[0]:04d}-{d[1]:02d}-{d[2]:02d} {h:02d}:{m:02d}"


def parse_offers(html):
    """Extract offers from the Google Flights page.

    Returns (offers, unpriced_count, parse_skipped_count). Each offer is a dict.
    Merges the "best flights" group (payload[2]) and the main list (payload[3]),
    deduped by flight-number chain (best-group entry wins).
    """
    doc = LexborHTMLParser(html)
    script = doc.css_first(r"script.ds\:1")
    if script is None:
        raise ParseShapeError("script.ds:1 not found in page")
    data = script.text().split("data:", 1)[1].rsplit(",", 1)[0]
    if data.endswith("errorHasStatus: true"):
        raise ParseShapeError("Google returned an error page")
    payload = json.loads(data)

    offers, unpriced, skipped = [], 0, 0
    seen = set()
    for slot, in_best in ((2, True), (3, False)):
        group = payload[slot] if len(payload) > slot else None
        if not (isinstance(group, list) and group and isinstance(group[0], list)):
            continue
        for k in group[0]:
            try:
                fl = k[0]
                segs = fl[2]
                numbers = ">".join(f"{s[22][0]}{s[22][1]}" for s in segs)
                try:
                    price = k[1][0][1]
                except (IndexError, TypeError):
                    unpriced += 1
                    continue
                if not isinstance(price, (int, float)) or price <= 0:
                    unpriced += 1
                    continue
                if numbers in seen:
                    continue
                seen.add(numbers)
                codes = []
                for s in segs:
                    if s[22][0] not in codes:
                        codes.append(s[22][0])
                duration = fl[9] if isinstance(fl[9], int) else sum(s[11] for s in segs)
                offers.append({
                    "price": int(price),
                    "airlines": "+".join(codes),
                    "codes": codes,
                    "numbers": numbers,
                    "out_dep": _iso(segs[0][20], segs[0][8]),
                    "out_arr": _iso(segs[-1][21], segs[-1][10]),
                    "duration": duration,
                    "stops": len(segs) - 1,
                    "via": "-".join(s[6] for s in segs[:-1]),
                    "dest_airport": segs[-1][6],
                    "in_best": in_best,
                })
            except (IndexError, TypeError, KeyError):
                skipped += 1
    if skipped and not offers:
        raise ParseShapeError(f"all {skipped} offers failed to parse — payload shape changed?")
    return offers, unpriced, skipped


def run_query(query_code, depart, ret, max_stops):
    """One Google query with retries. Returns dict with offers or error."""
    fast = os.environ.get("FAST_SLEEP") == "1"
    retries = config.RETRIES_PER_QUERY
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            q = create_query(
                flights=[
                    FlightQuery(date=depart, from_airport=config.ORIGIN,
                                to_airport=query_code, max_stops=max_stops,
                                airlines=list(config.AIRLINE_WHITELIST)),
                    FlightQuery(date=ret, from_airport=query_code,
                                to_airport=config.ORIGIN, max_stops=max_stops,
                                airlines=list(config.AIRLINE_WHITELIST)),
                ],
                trip="round-trip",
                seat="economy",
                passengers=Passengers(adults=1, children=0,
                                      infants_in_seat=0, infants_on_lap=0),
                currency=config.CURRENCY,
                language=config.LANGUAGE,
            )
            html = fetch_flights_html(q)
            offers, unpriced, skipped = parse_offers(html)
            kept = [o for o in offers
                    if all(c in config.AIRLINE_WHITELIST for c in o["codes"])]
            return {"offers": kept, "unpriced": unpriced, "skipped": skipped,
                    "dropped": len(offers) - len(kept), "error": None}
        except Exception as e:  # noqa: BLE001 — any failure means retry, then report
            last_err = f"{type(e).__name__}: {e}"
            print(f"    attempt {attempt}/{retries} failed: {last_err}", flush=True)
            if attempt < retries:
                lo, hi = (1.0, 2.0) if fast else config.RETRY_BACKOFF
                time.sleep(random.uniform(lo, hi))
    return {"offers": [], "unpriced": 0, "skipped": 0, "dropped": 0, "error": last_err}


def append_csv(path, header, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(header)
        w.writerows(rows)


PRICELOG_HEADER = [
    "log_date", "trip_name", "dest", "days_to_depart", "price_hkd", "airlines",
    "flight_numbers", "out_stops", "dest_airport", "out_dep", "out_arr",
    "out_duration_min", "via", "query_type", "in_best",
    "depart_date", "return_date", "log_ts_utc",
]
SUMMARY_HEADER = [
    "log_date", "trip_name", "dest", "days_to_depart", "status",
    "offers_any", "offers_nonstop", "min_price_any", "min_flights_any",
    "min_price_nonstop", "min_flights_nonstop", "unpriced", "note", "log_ts_utc",
]


def main():
    fast = os.environ.get("FAST_SLEEP") == "1"
    sleep_lo, sleep_hi = (0.5, 1.5) if fast else config.SLEEP_BETWEEN_QUERIES
    hkt = ZoneInfo(config.TIMEZONE)
    log_date = datetime.now(hkt).date()
    log_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    active = [(n, d, r) for (n, d, r) in config.TRIPS
              if date.fromisoformat(d) >= log_date]
    skipped_trips = [n for (n, d, r) in config.TRIPS
                     if date.fromisoformat(d) < log_date]
    if skipped_trips:
        print(f"skipping past trips: {', '.join(skipped_trips)}")
    if not active:
        print("no active trips — nothing to do (add next season's dates in tracker/config.py)")
        return 0

    price_rows, summary_rows = [], []
    hard_fail = False
    first_query = True

    for trip_name, depart, ret in active:
        days = (date.fromisoformat(depart) - log_date).days
        print(f"\n== {trip_name}  {depart} -> {ret}  (T-{days}d) ==", flush=True)
        for dest_code, query_code, label, nonstop_only, min_offers in config.DESTINATIONS:
            plan = [("nonstop", 0)] if nonstop_only else [("nonstop", 0), ("any", None)]
            outcomes = {}
            for query_type, max_stops in plan:
                if not first_query:
                    time.sleep(random.uniform(sleep_lo, sleep_hi))
                first_query = False
                outcomes[query_type] = run_query(query_code, depart, ret, max_stops)

            # pricelog rows
            for query_type, out in outcomes.items():
                for o in sorted(out["offers"], key=lambda x: x["price"]):
                    price_rows.append([
                        log_date.isoformat(), trip_name, dest_code, days,
                        o["price"], o["airlines"], o["numbers"], o["stops"],
                        o["dest_airport"], o["out_dep"], o["out_arr"],
                        o["duration"], o["via"], query_type,
                        int(o["in_best"]), depart, ret, log_ts,
                    ])

            # summary row
            ns = outcomes.get("nonstop", {"offers": [], "error": None})
            any_ = outcomes.get("any", ns)  # nonstop-only dests mirror nonstop
            errors = [o["error"] for o in outcomes.values() if o["error"]]
            unpriced = sum(o["unpriced"] for o in outcomes.values())
            skipped = sum(o["skipped"] for o in outcomes.values())
            dropped = sum(o["dropped"] for o in outcomes.values())
            n_ns, n_any = len(ns["offers"]), len(any_["offers"])
            best = max(n_ns, n_any)

            def cheapest(offers):
                if not offers:
                    return "", ""
                m = min(offers, key=lambda x: x["price"])
                return m["price"], m["numbers"]

            min_any, min_any_f = cheapest(any_["offers"])
            min_ns, min_ns_f = cheapest(ns["offers"])

            notes = []
            if errors:
                status = "ERROR"
                notes += errors
                hard_fail = True
            elif best == 0:
                status = "NO_RESULT"
                if min_offers > 0:
                    hard_fail = True
                    notes.append(f"0 offers, expected >= {min_offers}")
            elif best < min_offers:
                status = "SUSPECT"
                hard_fail = True
                notes.append(f"only {best} offers, expected >= {min_offers}")
            else:
                status = "OK"
            if skipped:
                notes.append(f"{skipped} offers unparseable")
            if dropped:
                notes.append(f"{dropped} offers dropped by whitelist")

            summary_rows.append([
                log_date.isoformat(), trip_name, dest_code, days, status,
                n_any, n_ns, min_any, min_any_f, min_ns, min_ns_f,
                unpriced, "; ".join(notes), log_ts,
            ])
            print(f"  {dest_code:<4} {status:<9} nonstop={n_ns} any={n_any}"
                  f" min={min_any or min_ns or '-'} {('; '.join(notes))[:80]}", flush=True)

    append_csv(os.path.join(config.DATA_DIR, config.PRICELOG),
               PRICELOG_HEADER, price_rows)
    append_csv(os.path.join(config.DATA_DIR, config.DAILYSUMMARY),
               SUMMARY_HEADER, summary_rows)
    print(f"\nwrote {len(price_rows)} pricelog rows, {len(summary_rows)} summary rows")
    if hard_fail:
        print("HEALTH CHECK FAILED — see statuses above", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
