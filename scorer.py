"""
Whale trade confidence scorer (0-100).

3 factors:
  1. Wallet credibility (all-time PnL)        — 40 pts
  2. Bet size relative to market 24hr volume  — 35 pts
  3. Price conviction zone                     — 25 pts

Score bands:
  80-100  🔥 STRONG SIGNAL
  60-79   ⚡ DECENT SIGNAL
  40-59   👀 MILD SIGNAL
  <40     📊 INFORMATIONAL
"""
from dataclasses import dataclass


@dataclass
class Score:
    total: int
    credibility: int
    dominance: int
    conviction: int
    price_move: int
    consensus: int
    label: str
    emoji: str
    reason: str


def score(
    usd: float,
    price_cents: float,
    pnl: float,
    volume_24h: float,
    price_after_cents: float,
    side: str,
    same_side_whales: int,
) -> Score:

    # --- 1. Wallet Credibility (40 pts) ---
    if pnl >= 500_000:   cred = 40
    elif pnl >= 200_000: cred = 34
    elif pnl >= 100_000: cred = 27
    elif pnl >= 50_000:  cred = 20
    elif pnl >= 10_000:  cred = 12
    elif pnl >= 0:       cred = 5
    else:                cred = 0

    # --- 2. Bet Size vs Market Volume (35 pts) ---
    if volume_24h > 0:
        pct = (usd / volume_24h) * 100
    else:
        pct = 0

    if pct >= 20:    dom = 35
    elif pct >= 10:  dom = 28
    elif pct >= 5:   dom = 20
    elif pct >= 2:   dom = 12
    elif pct >= 0.5: dom = 6
    elif pct > 0:    dom = 2
    else:            dom = 4  # volume unknown, neutral

    # --- 3. Price Conviction (25 pts) ---
    # For sports markets (40-60¢ range) we still reward extreme prices
    # but don't heavily punish normal NBA-range prices
    p = price_cents
    if   p <= 10 or p >= 90: conv = 25
    elif p <= 20 or p >= 80: conv = 20
    elif p <= 30 or p >= 70: conv = 14
    elif p <= 40 or p >= 60: conv = 8
    else:                    conv = 4  # near 50/50 — low but not zero

    # Bonus factors (don't change total max but boost signal quality)
    # Price movement confirmation
    pm = 0
    if price_after_cents > 0 and price_cents > 0:
        if side.upper() in ("YES",):
            movement = price_after_cents - price_cents
        else:
            movement = price_cents - price_after_cents
        if movement >= 3:    pm = 8
        elif movement >= 1:  pm = 4
        elif movement < -1:  pm = -4  # moved against

    # Whale consensus bonus
    cons = 0
    if same_side_whales >= 4:   cons = 10
    elif same_side_whales >= 3: cons = 7
    elif same_side_whales >= 2: cons = 4
    elif same_side_whales == 1: cons = 2

    # Cap total at 100
    total = min(100, cred + dom + conv + pm + cons)

    # Label
    if total >= 80:   label, emoji = "STRONG SIGNAL", "🔥"
    elif total >= 60: label, emoji = "DECENT SIGNAL", "⚡"
    elif total >= 40: label, emoji = "MILD SIGNAL",   "👀"
    else:             label, emoji = "INFORMATIONAL", "📊"

    # Reasoning
    parts = []
    if cred >= 34:   parts.append(f"elite wallet (+${pnl:,.0f})")
    elif cred >= 27: parts.append(f"strong wallet (+${pnl:,.0f})")
    elif cred >= 20: parts.append(f"profitable wallet (+${pnl:,.0f})")
    elif cred >= 12: parts.append(f"emerging wallet (+${pnl:,.0f})")
    elif cred == 0 and pnl < 0: parts.append(f"losing wallet (${pnl:,.0f})")
    else:            parts.append("limited track record")

    if pct >= 10:    parts.append(f"dominates volume ({pct:.1f}% of 24h)")
    elif pct >= 5:   parts.append(f"significant volume ({pct:.1f}% of 24h)")
    elif pct >= 2:   parts.append(f"notable volume ({pct:.1f}% of 24h)")

    if conv >= 20:   parts.append(f"extreme conviction ({price_cents:.0f}¢)")
    elif conv >= 14: parts.append(f"high conviction ({price_cents:.0f}¢)")
    elif conv <= 4:  parts.append(f"near 50/50 ({price_cents:.0f}¢)")

    if pm >= 8:      parts.append("market confirmed ✓✓")
    elif pm >= 4:    parts.append("market moving with them ✓")
    elif pm < 0:     parts.append("market moved against ✗")

    if cons >= 7:    parts.append(f"{same_side_whales + 1} whales agree")
    elif cons >= 4:  parts.append(f"{same_side_whales} other whale{'s' if same_side_whales > 1 else ''} agree")

    return Score(
        total, cred, dom, conv, pm, cons,
        label, emoji,
        ", ".join(parts) or "no standout factors"
    )
