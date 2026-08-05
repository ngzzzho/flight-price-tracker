"""All tunables live here. Edit this file each autumn to add next season's trips."""

ORIGIN = "HKG"
CURRENCY = "HKD"
LANGUAGE = "en-US"
TIMEZONE = "Asia/Hong_Kong"

# Every segment of an itinerary must be operated by one of these, or the offer
# is discarded. Also sent to Google as a server-side airline filter, which
# constrains BOTH legs of the round trip (including the hidden return leg
# baked into the quoted total price).
AIRLINE_WHITELIST = [
    "CX", "UO", "HB", "HX",   # HK: Cathay, HK Express, Greater Bay, Hong Kong Airlines
    "NH", "JL",               # JP: ANA, JAL
    "CI", "BR", "JX",         # TW: China Airlines, EVA, Starlux
    "KE",                     # KR: Korean Air
]

# (dest_code, google_query_code, label, nonstop_only, min_offers)
#   nonstop_only : only run the max_stops=0 query for this destination
#   min_offers   : health threshold — fewer priced offers than this (across the
#                  dest's queries) marks the day SUSPECT and fails the workflow.
#                  0 = zero offers is normal for this thin route (recorded as
#                  NO_RESULT but the workflow stays green).
# "TYO" city code covers NRT + HND in a single query (verified working).
DESTINATIONS = [
    ("TYO", "TYO", "Tokyo",     True,  3),
    ("SDJ", "SDJ", "Sendai",    True,  1),
    ("CTS", "CTS", "Sapporo",   False, 1),
    ("AKJ", "AKJ", "Asahikawa", False, 0),
    ("HKD", "HKD", "Hakodate",  False, 0),
]

# (trip_name, depart_date, return_date) — trips whose departure date has
# passed are skipped automatically. Add next season's rows each autumn.
# 2027 CNY 年初一 = 2027-02-06.
TRIPS = [
    ("XMAS-2026",       "2026-12-20", "2027-01-03"),
    ("CNY-2027-before", "2027-01-30", "2027-02-07"),
    ("CNY-2027-after",  "2027-02-06", "2027-02-14"),
]

# Politeness between Google queries, seconds (min, max). ~8 queries x 3 trips.
SLEEP_BETWEEN_QUERIES = (5.0, 12.0)

RETRIES_PER_QUERY = 3
RETRY_BACKOFF = (10.0, 25.0)   # seconds (min, max) between retries

DATA_DIR = "data"
PRICELOG = "pricelog.csv"
DAILYSUMMARY = "dailysummary.csv"
