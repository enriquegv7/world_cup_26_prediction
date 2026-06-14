"""
council.py — Weighted aggregator of LLM model predictions for WorldCupBench.

Reads pre-tournament prediction files, applies inverse-Brier weights from
the leaderboard, and returns an aggregated "council" probability vector for
each of the 72 group-stage matches.
"""

import json
import os

try:
    from src.utils import BASE_DIR, load_tournament_data, load_leaderboard
except ImportError:
    from utils import BASE_DIR, load_tournament_data, load_leaderboard


PREDICTIONS_DIR = os.path.join(BASE_DIR, "predictions", "pre-tournament")


def load_weights_from_leaderboard(leaderboard_path: str = None) -> dict:
    """
    Compute per-model weights from data/leaderboard.json.

    Weight is inversely proportional to brier_group; models without scored
    matches receive the average weight of models that do have history.
    If no model has history, returns equal weights.
    """
    if leaderboard_path is None:
        leaderboard_path = os.path.join(BASE_DIR, "data", "leaderboard.json")

    leaderboard = load_leaderboard(leaderboard_path)
    if not leaderboard or not leaderboard.get("models"):
        return {}

    models = leaderboard["models"]
    scored = [m for m in models if m.get("n_matches_scored", 0) > 0
              and m.get("brier_group") is not None]
    unscored = [m for m in models if m not in scored]

    raw_weights: dict = {}

    if scored:
        for m in scored:
            raw_weights[m["model"]] = 1.0 / (m["brier_group"] + 0.01)
        avg_weight = sum(raw_weights.values()) / len(raw_weights)
        for m in unscored:
            raw_weights[m["model"]] = avg_weight
    else:
        for m in models:
            raw_weights[m["model"]] = 1.0

    total = sum(raw_weights.values())
    return {name: w / total for name, w in raw_weights.items()}


def load_all_predictions(predictions_dir: str = None) -> list:
    """Load every *_prediction.json from predictions/pre-tournament/."""
    if predictions_dir is None:
        predictions_dir = PREDICTIONS_DIR

    predictions = []
    for fname in sorted(os.listdir(predictions_dir)):
        if fname.endswith("_prediction.json"):
            path = os.path.join(predictions_dir, fname)
            with open(path, "r", encoding="utf-8") as f:
                predictions.append(json.load(f))
    return predictions


def _get_match_from_prediction(prediction: dict, match_id: str) -> dict | None:
    """Return the group_matches entry whose match_id equals match_id (string)."""
    for m in prediction.get("group_matches", []):
        if str(m.get("match_id")) == match_id:
            return m
    return None


def _normalize_orientation(pred_match: dict) -> tuple:
    """
    Return (probs, score_home, score_away, predicted_result) in tournament frame.

    If orientation_flipped is True the model predicted the match with home/away
    teams reversed; flip probs, score, and result to match the official fixture.
    """
    if pred_match.get("orientation_flipped"):
        probs = {
            "home": pred_match["probs"]["away"],
            "draw": pred_match["probs"]["draw"],
            "away": pred_match["probs"]["home"],
        }
        score_home = pred_match["predicted_score"]["away"]
        score_away = pred_match["predicted_score"]["home"]
        raw = pred_match.get("predicted_result", "draw")
        predicted_result = "away" if raw == "home" else ("home" if raw == "away" else "draw")
    else:
        probs = dict(pred_match["probs"])
        score_home = pred_match["predicted_score"]["home"]
        score_away = pred_match["predicted_score"]["away"]
        predicted_result = pred_match.get("predicted_result", "draw")

    return probs, score_home, score_away, predicted_result


def aggregate_match(
    match_id: str,
    predictions: list,
    weights: dict,
    tournament_match: dict,
) -> dict | None:
    """
    Aggregate all model predictions for one group-stage match.

    Returns a dict with council_probs, recommended_outcome, confidence,
    agreement_rate, predicted_score, and the weights actually used.
    Returns None if no model had a prediction for this match.
    """
    model_data = []

    for pred in predictions:
        model_name = pred.get("model", "")
        pred_match = _get_match_from_prediction(pred, match_id)
        if pred_match is None:
            continue

        n = len(predictions) or 1
        weight = weights.get(model_name, 1.0 / n)
        probs, score_home, score_away, predicted_result = _normalize_orientation(pred_match)

        model_data.append({
            "model": model_name,
            "weight": weight,
            "probs": probs,
            "score_home": score_home,
            "score_away": score_away,
            "predicted_result": predicted_result,
        })

    if not model_data:
        return None

    # Re-normalise weights to account for any missing models.
    total_weight = sum(d["weight"] for d in model_data)

    council_probs = {"home": 0.0, "draw": 0.0, "away": 0.0}
    council_score_home = 0.0
    council_score_away = 0.0

    for d in model_data:
        w = d["weight"] / total_weight
        for outcome in ("home", "draw", "away"):
            council_probs[outcome] += w * d["probs"][outcome]
        council_score_home += w * d["score_home"]
        council_score_away += w * d["score_away"]

    council_probs = {k: round(v, 3) for k, v in council_probs.items()}

    recommended_outcome = max(council_probs, key=council_probs.get)
    confidence = council_probs[recommended_outcome]

    agreement = sum(1 for d in model_data if d["predicted_result"] == recommended_outcome)
    agreement_rate = round(agreement / len(model_data), 3)

    predicted_score = f"{round(council_score_home)}-{round(council_score_away)}"

    model_weights_used = {
        d["model"]: round(d["weight"] / total_weight, 3) for d in model_data
    }

    return {
        "match_id": match_id,
        "home_team": tournament_match.get("home_team"),
        "away_team": tournament_match.get("away_team"),
        "group": tournament_match.get("group"),
        "date": tournament_match.get("date"),
        "council_probs": council_probs,
        "recommended_outcome": recommended_outcome,
        "confidence": confidence,
        "agreement_rate": agreement_rate,
        "predicted_score": predicted_score,
        "model_weights_used": model_weights_used,
    }


def aggregate_all_matches(
    tournament_path: str = None,
    predictions_dir: str = None,
    weights: dict = None,
) -> list:
    """
    Aggregate predictions for all 72 group-stage matches.

    Loads tournament fixture, all prediction files, and (optionally) weights.
    Returns a list of aggregated match dicts in fixture order.
    """
    if tournament_path is None:
        tournament_path = os.path.join(BASE_DIR, "data", "tournament.json")
    if predictions_dir is None:
        predictions_dir = PREDICTIONS_DIR

    tournament = load_tournament_data(tournament_path)
    predictions = load_all_predictions(predictions_dir)

    if not weights:
        weights = load_weights_from_leaderboard()
        if not weights:
            n = len(predictions) or 1
            weights = {p.get("model", f"model_{i}"): 1.0 / n
                       for i, p in enumerate(predictions)}

    results = []
    for match in tournament.get("matches", []):
        match_id = str(match["match_id"])
        aggregated = aggregate_match(match_id, predictions, weights, match)
        if aggregated is not None:
            results.append(aggregated)

    return results
