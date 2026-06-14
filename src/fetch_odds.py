"""
fetch_odds.py — Fetch FIFA World Cup 2026 match odds from Polymarket.

Pulls 3-outcome (home/draw/away) prices for all group stage matches from the
Polymarket Gamma API (series: soccer-fifwc, event IDs 351715–351786).

Each match has 3 binary YES/NO markets:
  fifwc-{t1}-{t2}-{date}-draw  → draw probability
  fifwc-{t1}-{t2}-{date}-{t1}  → home team win probability
  fifwc-{t1}-{t2}-{date}-{t2}  → away team win probability

Decimal odd = round(1 / price, 2)

Usage:
    python src/fetch_odds.py
    python src/fetch_odds.py --output data/odds/odds.json
    python src/fetch_odds.py --dry-run
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    requests = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import utils

GAMMA_API = "https://gamma-api.polymarket.com"

# All 72 FIFA World Cup 2026 group stage event IDs on Polymarket (series: soccer-fifwc)
WC26_FIRST_EVENT_ID = 351715
WC26_LAST_EVENT_ID = 351786

ODDS_OUTPUT_PATH = os.path.join(utils.BASE_DIR, "data", "odds", "odds.json")
RESULTS_DIR = os.path.join(utils.BASE_DIR, "data", "results")

# Polymarket event title team names → FIFA 3-letter codes
TEAM_NAME_TO_FIFA: dict[str, str] = {
    "Mexico": "MEX",
    "South Africa": "RSA",
    "Korea Republic": "KOR",
    "Czechia": "CZE",
    "Canada": "CAN",
    "Bosnia-Herzegovina": "BIH",
    "Bosnia and Herzegovina": "BIH",
    "Qatar": "QAT",
    "Switzerland": "SUI",
    "Brazil": "BRA",
    "Morocco": "MAR",
    "Haiti": "HAI",
    "Scotland": "SCO",
    "United States": "USA",
    "Paraguay": "PAR",
    "Australia": "AUS",
    "Türkiye": "TUR",
    "Turkey": "TUR",
    "Germany": "GER",
    "Curaçao": "CUW",
    "Curacao": "CUW",
    "Netherlands": "NED",
    "Japan": "JPN",
    "Côte d'Ivoire": "CIV",
    "Cote d'Ivoire": "CIV",
    "Ivory Coast": "CIV",
    "Ecuador": "ECU",
    "Sweden": "SWE",
    "Tunisia": "TUN",
    "Belgium": "BEL",
    "Egypt": "EGY",
    "IR Iran": "IRN",
    "Iran": "IRN",
    "New Zealand": "NZL",
    "Saudi Arabia": "KSA",
    "Uruguay": "URU",
    "France": "FRA",
    "Senegal": "SEN",
    "Iraq": "IRQ",
    "Norway": "NOR",
    "Argentina": "ARG",
    "Algeria": "ALG",
    "Austria": "AUT",
    "Jordan": "JOR",
    "Portugal": "POR",
    "DR Congo": "COD",
    "Uzbekistan": "UZB",
    "Colombia": "COL",
    "England": "ENG",
    "Croatia": "CRO",
    "Ghana": "GHA",
    "Panama": "PAN",
    "Cabo Verde": "CPV",
    "Cape Verde": "CPV",
    "Spain": "ESP",
}


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def _load_known_results() -> set[str]:
    """Return a set of match_id strings that already have a known result."""
    known: set[str] = set()
    if not os.path.isdir(RESULTS_DIR):
        return known
    for fname in os.listdir(RESULTS_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(RESULTS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        for m in data.get("matches", []):
            mid = m.get("match_id")
            if mid is not None:
                known.add(str(mid))
    return known


def _load_tournament_index() -> dict:
    """Index tournament.json matches by (home_team, away_team) → match entry."""
    try:
        tournament = utils.load_tournament_data()
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    index: dict[tuple[str, str], dict] = {}
    for match in tournament.get("matches", []):
        key = (match.get("home_team", ""), match.get("away_team", ""))
        index[key] = match
    return index


def _fetch_event(event_id: int) -> dict | None:
    """Fetch a single Polymarket event by ID."""
    if requests is None:
        return None
    url = f"{GAMMA_API}/events/{event_id}"
    try:
        resp = requests.get(url, timeout=10,
                            headers={"User-Agent": "WorldCupBench/1.0"})
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        _log(f"  Warn: event {event_id} fetch failed: {exc}")
        return None


def _parse_outcome_price(prices_raw) -> float | None:
    """Extract the YES (first) price from outcomePrices JSON string or list."""
    try:
        if isinstance(prices_raw, str):
            prices_raw = json.loads(prices_raw)
        return float(prices_raw[0])
    except (TypeError, IndexError, ValueError, json.JSONDecodeError):
        return None


def _price_to_odd(price: float) -> float | None:
    """Convert a probability price (0–1) to a decimal bookmaker odd."""
    if price is None or price <= 0:
        return None
    return round(1.0 / price, 2)


def _parse_event_markets(event: dict) -> dict | None:
    """
    Extract home/draw/away prices from a Polymarket 3-market soccer event.

    Returns dict with keys 'home_price', 'draw_price', 'away_price' (float 0–1)
    and 'home_name', 'away_name' (str), or None if parsing fails.
    """
    title = event.get("title", "")
    event_slug = event.get("slug", "")
    markets = event.get("markets", [])

    if len(markets) != 3:
        return None

    # Parse home/away team names from title "Home vs. Away"
    if " vs. " in title:
        home_name, away_name = title.split(" vs. ", 1)
    elif " vs " in title:
        home_name, away_name = title.split(" vs ", 1)
    else:
        return None

    # Extract t1 and t2 codes from the event slug: fifwc-{t1}-{t2}-{date}
    # Slug format: fifwc-bel-egy-2026-06-15
    parts = event_slug.split("-")
    # parts[0]='fifwc', parts[1]=t1, parts[2]=t2, parts[3]=year, parts[4]=mo, parts[5]=day
    if len(parts) < 6 or parts[0] != "fifwc":
        return None
    t1 = parts[1]  # home team code in Polymarket
    t2 = parts[2]  # away team code in Polymarket

    home_price = draw_price = away_price = None

    for market in markets:
        mslug = market.get("slug", "")
        prices_raw = market.get("outcomePrices")
        price = _parse_outcome_price(prices_raw)
        if price is None:
            continue

        # Skip already-resolved markets (price is exactly 0 or 1)
        if price == 0.0 or price == 1.0:
            continue

        # Identify market role from slug suffix
        if mslug.endswith("-draw") or "draw" in market.get("question", "").lower():
            draw_price = price
        elif mslug.endswith(f"-{t1}"):
            home_price = price
        elif mslug.endswith(f"-{t2}"):
            away_price = price

    if home_price is None or draw_price is None or away_price is None:
        return None

    return {
        "home_name": home_name.strip(),
        "away_name": away_name.strip(),
        "home_price": home_price,
        "draw_price": draw_price,
        "away_price": away_price,
    }


def fetch_all_odds(known_results: set[str], tournament_index: dict) -> list[dict]:
    """Fetch odds for all 72 group stage matches and return list of odds dicts."""
    odds_list: list[dict] = []
    skipped_resolved = 0
    skipped_no_prices = 0
    skipped_no_match = 0

    for event_id in range(WC26_FIRST_EVENT_ID, WC26_LAST_EVENT_ID + 1):
        event = _fetch_event(event_id)
        if not event:
            skipped_no_prices += 1
            continue

        parsed = _parse_event_markets(event)
        if not parsed:
            skipped_no_prices += 1
            continue

        home_name = parsed["home_name"]
        away_name = parsed["away_name"]

        home_fifa = TEAM_NAME_TO_FIFA.get(home_name)
        away_fifa = TEAM_NAME_TO_FIFA.get(away_name)

        if not home_fifa or not away_fifa:
            _log(f"  Warn: unknown team name(s): '{home_name}' / '{away_name}'")
            skipped_no_match += 1
            continue

        # Look up match_id from tournament index
        match_entry = tournament_index.get((home_fifa, away_fifa))
        if not match_entry:
            _log(f"  Warn: no tournament match for {home_fifa} vs {away_fifa}")
            skipped_no_match += 1
            continue

        match_id = str(match_entry["match_id"])

        # Skip if result already known
        if match_id in known_results:
            skipped_resolved += 1
            continue

        home_odd = _price_to_odd(parsed["home_price"])
        draw_odd = _price_to_odd(parsed["draw_price"])
        away_odd = _price_to_odd(parsed["away_price"])

        odds_list.append({
            "match_id": match_id,
            "home_team": home_fifa,
            "away_team": away_fifa,
            "date": match_entry.get("date", ""),
            "source": "polymarket",
            "prices": {
                "home": round(parsed["home_price"] * 100, 2),
                "draw": round(parsed["draw_price"] * 100, 2),
                "away": round(parsed["away_price"] * 100, 2),
            },
            "odds": {
                "home": home_odd,
                "draw": draw_odd,
                "away": away_odd,
            },
        })

    _log(f"Fetched {len(odds_list)} matches | "
         f"skipped: {skipped_resolved} resolved, "
         f"{skipped_no_prices} no-prices, {skipped_no_match} no-match")
    return odds_list


def save_odds(odds_list: list[dict], output_path: str) -> None:
    """Write odds to JSON. Does NOT write if odds_list is empty."""
    if not odds_list:
        _log("No odds to save — file NOT updated.")
        return

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "source": "polymarket",
        "bookmaker": "Polymarket (soccer-fifwc)",
        "total_matches": len(odds_list),
        "matches": odds_list,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _log(f"Saved {len(odds_list)} matches to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch FIFA World Cup 2026 odds from Polymarket"
    )
    parser.add_argument("--output", default=ODDS_OUTPUT_PATH,
                        help="Output JSON path (default: data/odds/odds.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and print but do not write to disk")
    args = parser.parse_args()

    if requests is None:
        _log("ERROR: 'requests' package not installed. Run: pip install requests")
        sys.exit(1)

    _log("Loading known results and tournament index...")
    known_results = _load_known_results()
    tournament_index = _load_tournament_index()
    _log(f"  Known results: {len(known_results)} | Tournament matches: {len(tournament_index)}")

    _log(f"Fetching odds for event IDs {WC26_FIRST_EVENT_ID}–{WC26_LAST_EVENT_ID}...")
    odds_list = fetch_all_odds(known_results, tournament_index)

    if args.dry_run:
        _log("DRY RUN — not writing to disk.")
        for entry in odds_list[:5]:
            print(json.dumps(entry, indent=2, ensure_ascii=False))
        if len(odds_list) > 5:
            print(f"  ... and {len(odds_list) - 5} more")
        return

    # Only write if fetch succeeded (non-empty list)
    save_odds(odds_list, args.output)


if __name__ == "__main__":
    main()
