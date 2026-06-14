"""
run_council.py — Orchestrates the LLM council and generates bet recommendations.

Usage:
    python scripts/run_council.py                    # today's matches
    python scripts/run_council.py --date 2026-06-15  # specific date
    python scripts/run_council.py --all-pending      # all unplayed group matches
    python scripts/run_council.py --only-bets        # only matches with a bet
    python scripts/run_council.py --all              # every group match
    python scripts/run_council.py --bankroll 18.50   # override bankroll
"""

import argparse
import json
import os
import sys
from datetime import date

# Allow `from src.X import ...` when running from the repo root or scripts/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.council import aggregate_all_matches, load_weights_from_leaderboard, load_all_predictions
from src.betting import recommend_bet
from src.utils import BASE_DIR, load_leaderboard, now_iso

# ── Risk parameters ─────────────────────────────────────────────────────────
BANKROLL = 20.0
KELLY_DIVISOR = 4
MAX_BET_PCT = 0.05
MIN_EDGE = 0.05
MIN_AGREEMENT = 0.55
MIN_CONFIDENCE = 0.45

# ── Paths ────────────────────────────────────────────────────────────────────
ODDS_PATH = os.path.join(BASE_DIR, "data", "odds", "odds.json")
RESULTS_DIR = os.path.join(BASE_DIR, "data", "results")
COUNCIL_DIR = os.path.join(BASE_DIR, "data", "council")
RECOMMENDATIONS_PATH = os.path.join(COUNCIL_DIR, "recommendations.json")
LEADERBOARD_PATH = os.path.join(BASE_DIR, "data", "leaderboard.json")


# ── Data loaders ─────────────────────────────────────────────────────────────

def load_odds(path: str = ODDS_PATH) -> dict:
    """Load bookmaker odds indexed by match_id (string)."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {str(m["match_id"]): m for m in data.get("matches", [])}


def load_all_results(results_dir: str = RESULTS_DIR) -> dict:
    """Load all result files and index by match_id (string)."""
    results: dict = {}
    if not os.path.isdir(results_dir):
        return results
    for fname in os.listdir(results_dir):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(results_dir, fname)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for match in data.get("matches", []):
            mid = str(match.get("match_id", ""))
            if mid:
                results[mid] = match
    return results


# ── Enrichment ───────────────────────────────────────────────────────────────

def enrich_with_result(rec: dict, results: dict) -> dict:
    """Attach actual result and compute profit/loss if the match has been played."""
    result = results.get(rec["match_id"])

    if result is None:
        rec.update(result_known=False, actual_result=None,
                   actual_score=None, bet_won=None, profit_eur=None)
        return rec

    outcome = result.get("outcome")
    rec.update(
        result_known=True,
        actual_result=outcome,
        actual_score=result.get("score"),
    )

    if rec.get("should_bet") and outcome is not None:
        won = outcome == rec.get("bet_outcome")
        rec["bet_won"] = won
        rec["profit_eur"] = (
            round(rec["bet_size_eur"] * (rec["bet_odds"] - 1), 2)
            if won else round(-rec["bet_size_eur"], 2)
        )
    else:
        rec.update(bet_won=None, profit_eur=None)

    return rec


# ── Filtering ─────────────────────────────────────────────────────────────────

def filter_matches(matches: list, args) -> list:
    today = args.date or str(date.today())

    if args.all:
        return matches
    if getattr(args, "all_pending", False):
        return [m for m in matches
                if not m.get("result_known") and m.get("date", "") >= today]
    if getattr(args, "only_bets", False):
        return [m for m in matches
                if m.get("should_bet") and not m.get("result_known")
                and m.get("date", "") >= today]

    # Default: matches scheduled for the target date.
    return [m for m in matches if m.get("date") == today]


# ── Console output ────────────────────────────────────────────────────────────

OUTCOME_LABEL = {"home": "LOCAL", "draw": "EMPATE", "away": "VISITANTE"}
WIDTH = 78
SEP_THICK = "=" * WIDTH
SEP_THIN = "-" * WIDTH


def _print_header(weights: dict, bankroll: float, date_label: str):
    top = sorted(weights.items(), key=lambda x: -x[1])[:5]
    w_str = " | ".join(f"{n} ({v*100:.1f}%)" for n, v in top)
    print(f"\n{SEP_THICK}")
    print(f" WORLDCUPBENCH -- CONSEJO LLM | Jornada {date_label} | Bank: EUR{bankroll:.2f}")
    print(f" Pesos: {w_str}")
    print(f"{SEP_THICK}\n")


def _print_match(m: dict):
    mid = m["match_id"]
    outcome_lbl = OUTCOME_LABEL.get(m["recommended_outcome"], m["recommended_outcome"].upper())
    pct = round(m["confidence"] * 100, 1)
    agreement_n = round(m["agreement_rate"] * 11)

    print(f" #{mid}  {m['home_team']} vs {m['away_team']}  [Grupo {m['group']}]  {m['date']}")
    print(f"     Consejo:   {outcome_lbl}  ({pct}% | {agreement_n}/11 modelos de acuerdo)")
    print(f"     Marcador:  {m['predicted_score']}")

    if m.get("odds"):
        o = m["odds"]
        print(f"     Cuotas:    Local {o.get('home', '-')} · "
              f"Empate {o.get('draw', '-')} · Visitante {o.get('away', '-')}")

    rec = m.get("recommended_outcome")
    if m.get("edge") and rec and m["edge"].get(rec) is not None:
        ev = m["edge"][rec]
        sign = "+" if ev >= 0 else ""
        mark = "OK" if ev >= MIN_EDGE else "NO"
        print(f"     Edge:      {sign}{ev * 100:.1f}% [{mark}]")

    if m.get("should_bet"):
        print(f"     >> APOSTAR: {outcome_lbl} @ {m['bet_odds']} -> "
              f"EUR{m['bet_size_eur']:.2f} ({m['bet_size_pct']}% del bank)")
    else:
        reason_map = {
            "edge_negativo":    "edge negativo",
            "edge_insuficiente":"edge insuficiente (<5%)",
            "consenso_bajo":    "consenso bajo (<55%)",
            "sin_cuotas":       "sin cuotas",
        }
        reason = reason_map.get(m.get("no_bet_reason"), m.get("no_bet_reason") or "")
        print(f"     -- NO APOSTAR ({reason})")

    print(f"\n{SEP_THIN}\n")


def _print_footer(matches: list, bankroll: float):
    bets = [m for m in matches if m.get("should_bet")]
    exposure = sum(m.get("bet_size_eur", 0) for m in bets)
    pct = exposure / bankroll * 100 if bankroll else 0
    print(f"{SEP_THICK}")
    print(f" RESUMEN: {len(bets)} apuesta(s) recomendada(s) | "
          f"Exposicion total: EUR{exposure:.2f} ({pct:.1f}% del bank)")
    lb = load_leaderboard(LEADERBOARD_PATH)
    if lb.get("models"):
        top3 = lb["models"][:3]
        rank = " > ".join(
            f"{m['model']} (Brier: {m.get('brier_total', '?')})" for m in top3
        )
        print(f" Modelos rankeados: {rank}")
    print(f"{SEP_THICK}\n")


def print_table(matches: list, weights: dict, bankroll: float, date_label: str):
    _print_header(weights, bankroll, date_label)
    if not matches:
        print("  No hay partidos para mostrar con los filtros aplicados.\n")
    else:
        for m in matches:
            _print_match(m)
    _print_footer(matches, bankroll)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="WorldCupBench LLM Council — betting recommendations"
    )
    parser.add_argument("--date", help="Mostrar partidos de una fecha (YYYY-MM-DD)")
    parser.add_argument("--all-pending", dest="all_pending", action="store_true",
                        help="Mostrar todos los partidos pendientes sin resultado")
    parser.add_argument("--only-bets", dest="only_bets", action="store_true",
                        help="Mostrar solo partidos con apuesta recomendada")
    parser.add_argument("--all", action="store_true",
                        help="Mostrar todos los partidos de grupo")
    parser.add_argument("--bankroll", type=float, default=BANKROLL,
                        help="Bankroll actual en EUR (default: 20)")
    args = parser.parse_args()

    bankroll = args.bankroll
    date_label = args.date or str(date.today())

    # 1. Compute model weights.
    weights = load_weights_from_leaderboard()
    if not weights:
        preds = load_all_predictions()
        n = len(preds) or 1
        weights = {p.get("model", f"model_{i}"): 1.0 / n for i, p in enumerate(preds)}

    # 2-3. Aggregate all 72 group matches.
    council_matches = aggregate_all_matches(weights=weights)

    # 4. Load bookmaker odds.
    odds_by_id = load_odds()

    # 5. Load known results.
    results = load_all_results()

    # 6. Generate bet recommendations.
    recommendations = []
    for cm in council_matches:
        rec = recommend_bet(
            cm,
            odds_by_id.get(cm["match_id"]),
            bankroll,
            kelly_divisor=KELLY_DIVISOR,
            max_bet_pct=MAX_BET_PCT,
            min_edge=MIN_EDGE,
            min_agreement=MIN_AGREEMENT,
            min_confidence=MIN_CONFIDENCE,
        )
        rec = enrich_with_result(rec, results)
        recommendations.append(rec)

    # 7. Write data/council/recommendations.json.
    os.makedirs(COUNCIL_DIR, exist_ok=True)
    bets = [r for r in recommendations if r.get("should_bet")]
    output = {
        "generated_at": now_iso(),
        "bankroll": bankroll,
        "model_weights": weights,
        "matches_analyzed": len(recommendations),
        "bets_recommended": len(bets),
        "total_exposure_eur": round(sum(r.get("bet_size_eur", 0) for r in bets), 2),
        "matches": recommendations,
    }
    with open(RECOMMENDATIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 8. Filter and print.
    display = filter_matches(recommendations, args)
    print_table(display, weights, bankroll, date_label)


if __name__ == "__main__":
    main()
