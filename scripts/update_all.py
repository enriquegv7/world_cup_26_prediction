"""
update_all.py — WorldCupBench daily pipeline.

Runs the full update sequence in order:
  1. Fetch odds from Polymarket (data/odds/odds.json)
  2. Fetch today's match results (data/results/{date}.json)
  3. Score all models (data/leaderboard.json)
  4. Generate council recommendations (data/council/recommendations.json)

Usage:
    python scripts/update_all.py
    python scripts/update_all.py --date 2026-06-15
    python scripts/update_all.py --skip-odds
"""

import argparse
import os
import subprocess
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd: list[str], label: str) -> int:
    print(f"\n{'=' * 60}")
    print(f">> {label}")
    print("=" * 60)
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print(f"ERROR: '{' '.join(cmd)}' failed (exit {result.returncode})")
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="WorldCupBench daily update pipeline")
    parser.add_argument("--date", default=str(date.today()),
                        help="Date for results fetch and council (default: today)")
    parser.add_argument("--skip-odds", action="store_true",
                        help="Skip Polymarket odds fetch")
    parser.add_argument("--skip-results", action="store_true",
                        help="Skip results fetch")
    parser.add_argument("--bankroll", type=float, default=None,
                        help="Override bankroll for council (EUR)")
    args = parser.parse_args()

    py = sys.executable
    target_date = args.date
    errors: list[str] = []

    if not args.skip_odds:
        rc = run([py, "src/fetch_odds.py"], "Fetching Polymarket odds...")
        if rc != 0:
            errors.append("fetch_odds")

    if not args.skip_results:
        rc = run([py, "scripts/fetch_results.py", "--date", target_date],
                 f"Fetching results for {target_date}...")
        if rc != 0:
            errors.append("fetch_results")

    rc = run([py, "scripts/score.py"], "Scoring models...")
    if rc != 0:
        errors.append("score")

    council_cmd = [py, "scripts/run_council.py", "--date", target_date]
    if args.bankroll is not None:
        council_cmd += ["--bankroll", str(args.bankroll)]
    rc = run(council_cmd, f"Running council for {target_date}...")
    if rc != 0:
        errors.append("run_council")

    print(f"\n{'=' * 60}")
    if errors:
        print(f"Pipeline finished with errors in: {', '.join(errors)}")
        sys.exit(1)
    else:
        print(f"Pipeline complete for {target_date}.")
    print("=" * 60)


if __name__ == "__main__":
    main()
