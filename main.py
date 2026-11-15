#!/usr/bin/env python3
"""Lean EWMA forecaster (shrunk centre, 18h window) -- polymarket-faa-attribution-01, wallet w2.

Stdlib only. Reads one case (makefun/polymarket-case/v1) and writes
{"forecasts": [{"id": <market id>, "q": [[q05,q25,q50,q75,q95] x 240]}]}.

Model, per market (all prices are the 1-minute Yes grid ending at checkpoint):
  * Window: last 1080 minutes (18h) of prices only; older history is ignored.
  * Centre: last price x shrunk 6% toward the mean of the last 180 minutes:
        centre0 = 0.94 * x + 0.06 * mean180
    plus a damped empirical drift, linear in horizon h:
        drift = 0.35 * (x - mean180) / 180, clamped to +/-0.0005 per minute
        centre(h) = centre0 + drift * h
    The centre is evaluated at anchor horizons 1/5/15/30/60/120/240 and
    linearly interpolated between anchors (piecewise-linear in h).
    Drift is clamped to +/-0.0005 per minute. NO regime scaling: the same
    drift/sigma rules apply in quiet and jumpy stretches alike.
  * Spread: EWMA volatility of 1-minute price changes over the 1080-min
    window, halflife 300 min (alpha = 1 - 0.5**(1/300)), floored at 0.001
    and capped at 0.004 price units per sqrt-minute:
        q_tau(h) = clamp(centre(h) + z_tau * sigma * sqrt(h), 0, 1)
    with z = (-1.644854, -0.67449, 0, 0.67449, 1.644854).
  * Outputs are rounded to 6 decimals and forced non-decreasing per row.

Usage:
  python3 main.py <case.json> [output.json]     # single case; no 2nd arg -> stdout
  python3 main.py                                # dir mode: $MAKEFUN_INPUT_DIR
                                                 # (else /input) -> $MAKEFUN_OUTPUT_DIR
                                                 # (else /output), one .out per .in
Deterministic: no randomness, no wall-clock, no dict-order dependence.
"""

import json
import math
import os
import sys
from pathlib import Path

Z = (-1.644854, -0.67449, 0.0, 0.67449, 1.644854)
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)

# --- w2 parameter set (lean EWMA) ---
WINDOW = 1080          # minutes of history used
MEAN180 = 180          # minutes for the shrink target mean
SHRINK = 0.06          # weight of mean180 in centre0
EMP = 0.35             # empirical drift dampening factor
DRIFT_CLAMP = 0.0005   # per-minute drift clamp
ANCHORS = (1, 5, 15, 30, 60, 120, 240)
SIGMA_HALFLIFE = 300   # minutes, EWMA halflife for squared 1-min moves
SIGMA_FLOOR = 0.001
SIGMA_CAP = 0.004


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _round6(x):
    v = round(_clamp01(x) * 1e6) / 1e6
    return 0.0 if v == 0 else v  # never -0.0


def _ewma_sigma(prices):
    """EWMA std of 1-minute moves over the window, halflife 300 min."""
    if len(prices) < 2:
        return SIGMA_FLOOR
    alpha = 1.0 - 0.5 ** (1.0 / SIGMA_HALFLIFE)
    diffs = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
    # Seed with the whole window's mean squared move (rev 1): seeding from
    # only the first 10 (oldest) moves let a stale jump dominate the EWMA.
    var = sum(d * d for d in diffs) / len(diffs)
    for d in diffs:
        var = (1.0 - alpha) * var + alpha * d * d
    sigma = math.sqrt(var) if var > 0.0 else 0.0
    return min(SIGMA_CAP, max(SIGMA_FLOOR, sigma))


def _centre_anchors(prices):
    """Centre at each anchor horizon; linear interpolation fills the rest."""
    x = prices[-1]
    tail180 = prices[-MEAN180:] if len(prices) >= MEAN180 else prices
    centre0 = (1.0 - SHRINK) * x + SHRINK * _mean(tail180)
    drift = 0.0
    if len(prices) >= 2:
        # Rev 2: empirical slope anchored at the checkpoint -- how far the
        # last price sits from its own 180-min mean, spread over 180 min --
        # instead of the old two-window gap (mean30 vs minutes 180..210
        # ago), which compared windows whose centres were 165 min apart
        # but whose levels were noisy step-prices. Still damped by EMP.
        drift = EMP * (x - _mean(tail180)) / 180.0
        drift = max(-DRIFT_CLAMP, min(DRIFT_CLAMP, drift))
    return [(a, centre0 + drift * a) for a in ANCHORS]


def _centre_at(anchors, h):
    if h <= anchors[0][0]:
        return anchors[0][1]
    for (a0, c0), (a1, c1) in zip(anchors, anchors[1:]):
        if h <= a1:
            t = (h - a0) / (a1 - a0)
            return c0 + t * (c1 - c0)
    return anchors[-1][1]


def forecast_market(market, horizon):
    prices = [float(p) for p in market["prices"]]
    if not prices:
        raise ValueError("market %s has no prices" % market["id"])
    prices = prices[-WINDOW:]
    sigma = _ewma_sigma(prices)
    anchors = _centre_anchors(prices)
    rows = []
    for h in range(1, horizon + 1):
        centre = _centre_at(anchors, h)
        spread = sigma * math.sqrt(h)
        row = [_round6(centre + z * spread) for z in Z]
        # Enforce monotonicity after rounding (can only differ by 1e-6).
        for j in range(1, 5):
            if row[j] < row[j - 1]:
                row[j] = row[j - 1]
        rows.append(row)
    return rows


def forecast_case(case):
    horizon = int(case["horizon_minutes"])
    if list(case.get("quantiles", [])) != list(QUANTILES):
        raise ValueError("unexpected quantiles %r" % (case.get("quantiles"),))
    forecasts = [
        {"id": m["id"], "q": forecast_market(m, horizon)}
        for m in case["markets"]
    ]
    return {"forecasts": forecasts}


def run_file(in_path, out_path):
    with open(in_path, "r", encoding="utf-8") as f:
        case = json.load(f)
    out = forecast_case(case)
    text = json.dumps(out, separators=(",", ":"), sort_keys=False) + "\n"
    if out_path is None:
        sys.stdout.write(text)
    else:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)


def main(argv):
    if len(argv) >= 2:
        run_file(argv[1], argv[2] if len(argv) >= 3 else None)
        return 0
    in_dir = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    out_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = sorted(p for p in in_dir.iterdir() if p.name.endswith(".in"))
    if not inputs:
        raise SystemExit("no .in files in %s" % in_dir)
    for p in inputs:
        run_file(p, out_dir / (p.stem + ".out"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
