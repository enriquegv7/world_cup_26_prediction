"""
betting.py — Kelly Criterion bet sizing for WorldCupBench council recommendations.

Given aggregated council probabilities and bookmaker decimal odds, decides
whether a bet has positive expected value and how much to stake.
"""

from typing import Optional


def calculate_edge(council_prob: float, odd: float) -> float:
    """
    Expected edge for a single outcome.

    edge = (prob × odd) − 1
    Positive → value bet; negative → bookmaker has the edge.
    """
    return (council_prob * odd) - 1.0


def kelly_fraction(council_prob: float, odd: float) -> float:
    """
    Full Kelly stake fraction.

    f = (p × b − q) / b, where b = odd − 1, q = 1 − p
    Equivalent to: f = edge / (odd − 1)
    Returns 0.0 if odd ≤ 1 (degenerate case).
    """
    b = odd - 1.0
    if b <= 0:
        return 0.0
    return (council_prob * b - (1.0 - council_prob)) / b


def recommend_bet(
    council_match: dict,
    odds_match: Optional[dict],
    bankroll: float,
    kelly_divisor: int = 4,
    max_bet_pct: float = 0.05,
    min_edge: float = 0.05,
    min_agreement: float = 0.55,
    min_confidence: float = 0.45,
) -> dict:
    """
    Produce a bet recommendation for one match.

    council_match : output dict from council.aggregate_match()
    odds_match    : entry from odds.json for this match_id, or None
    bankroll      : current bankroll in EUR
    kelly_divisor : divide raw Kelly by this factor (4 = fractional 1/4 Kelly)
    max_bet_pct   : hard cap on bet size as fraction of bankroll (default 5%)
    min_edge      : minimum edge to trigger a bet (default 5%)
    min_agreement : minimum model agreement rate to trigger a bet (default 55%)
    min_confidence: minimum council confidence to trigger a bet (default 45%)
    """
    base = {
        "match_id": council_match["match_id"],
        "home_team": council_match["home_team"],
        "away_team": council_match["away_team"],
        "group": council_match["group"],
        "date": council_match["date"],
        "recommended_outcome": council_match["recommended_outcome"],
        "predicted_score": council_match["predicted_score"],
        "confidence": council_match["confidence"],
        "agreement_rate": council_match["agreement_rate"],
        "council_probs": council_match["council_probs"],
    }

    no_bet_fields = {
        "should_bet": False,
        "bet_outcome": None,
        "bet_odds": None,
        "kelly_raw": None,
        "kelly_fraction": 0.0,
        "bet_size_eur": 0.0,
        "bet_size_pct": 0.0,
    }

    # No odds available for this match.
    if not odds_match or not odds_match.get("odds"):
        return {**base, "odds": None, "edge": None,
                "no_bet_reason": "sin_cuotas", **no_bet_fields}

    odds = odds_match["odds"]
    probs = council_match["council_probs"]

    # Calculate edge for all three outcomes.
    edge: dict = {}
    for outcome in ("home", "draw", "away"):
        o = odds.get(outcome)
        edge[outcome] = round(calculate_edge(probs[outcome], o), 4) if o else None

    result_base = {**base, "odds": odds, "edge": edge}

    # Filter: low consensus.
    if council_match["agreement_rate"] < min_agreement:
        return {**result_base, "no_bet_reason": "consenso_bajo", **no_bet_fields}

    # Filter: low confidence.
    if council_match["confidence"] < min_confidence:
        return {**result_base, "no_bet_reason": "consenso_bajo", **no_bet_fields}

    recommended = council_match["recommended_outcome"]
    rec_prob = probs[recommended]
    rec_odd = odds.get(recommended)
    rec_edge = edge.get(recommended)

    # Filter: negative edge.
    if rec_edge is None or rec_edge <= 0:
        return {**result_base, "no_bet_reason": "edge_negativo", **no_bet_fields}

    # Filter: edge below minimum threshold.
    if rec_edge < min_edge:
        return {**result_base, "no_bet_reason": "edge_insuficiente", **no_bet_fields}

    # Calculate stake.
    kelly_raw = kelly_fraction(rec_prob, rec_odd)
    kelly_safe = kelly_raw / kelly_divisor
    bet_size = min(bankroll * kelly_safe, bankroll * max_bet_pct)
    bet_size = round(bet_size, 2)
    bet_pct = round(bet_size / bankroll * 100, 1)

    return {
        **result_base,
        "should_bet": True,
        "no_bet_reason": None,
        "bet_outcome": recommended,
        "bet_odds": rec_odd,
        "kelly_raw": round(kelly_raw, 4),
        "kelly_fraction": round(kelly_safe, 4),
        "bet_size_eur": bet_size,
        "bet_size_pct": bet_pct,
    }
