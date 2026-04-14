"""
Whale trade confidence scorer (0-100).

5 factors:
  1. Wallet credibility (all-time PnL)        — 30 pts
  2. Bet size relative to market 24hr volume  — 25 pts
  3. Price conviction zone                     — 20 pts
  4. Price movement after trade                — 15 pts
  5. Whale consensus (same side, same market)  — 10 pts
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
    volume_24h: float,        # market 24hr volume in USD (0 if unknown)
    price_after_cents: float, # current market price for same side (0 if unknown)
    side: str,                # "YES" or "NO"
    same_side_whales: int,    # other top wallets same side same market last hour
) -> Score:

    # --- 1. Wallet Credibility (30 pts) ---
    if pnl >= 500_000:   cred = 30
    elif pnl >= 100_000: cred = 24
    elif pnl >= 50_000:  cred = 18
    elif pnl >= 10_000:  cred = 11
    elif pnl >= 0:       cred = 4
    else:                cred = 0

    # --- 2. Bet Size vs Market 24hr Volume (25 pts) ---
    if volume_24h > 0:
        pct = (usd / volume_24h) * 100
    else:
        pct = 0  # unknown, give neutral score

    if pct >= 10:    dom = 25
    elif pct >= 5:   dom = 20
    elif pct >= 2:   dom = 13
    elif pct >= 0.5: dom = 7
    elif pct > 0:    dom = 2
    else:            dom = 5  # volume unknown, neutral

    # --- 3. Price Conviction Zone (20 pts) ---
    p = price_cents
    if   p <= 10 or p >= 90: conv = 20
    elif p <= 20 or p >= 80: conv = 15
    elif p <= 35 or p >= 65: conv = 9
    else:                    conv = 2  # near 50/50

    # --- 4. Price Movement After Trade (15 pts) ---
    # Did the market move in the whale's favour after they traded?
    if price_after_cents > 0 and price_cents > 0:
        if side.upper() == "YES":
            movement = price_after_cents - price_cents
        else:
            movement = price_cents - price_after_cents

        if movement >= 3:    pm = 15  # strong confirmation
        elif movement >= 1:  pm = 9   # mild confirmation
        elif movement >= -1: pm = 3   # no movement
        else:                pm = 0   # market moved against whale
    else:
        pm = 3  # unknown, neutral

    # --- 5. Whale Consensus (10 pts) ---
    if same_side_whales >= 3:   cons = 10
    elif same_side_whales >= 2: cons = 6
    elif same_side_whales == 1: cons = 3
    else:                       cons = 0

    total = cred + dom + conv + pm + cons

    # --- Label ---
    if total >= 80:   label, emoji = "STRONG SIGNAL", "🔥"
    elif total >= 60: label, emoji = "DECENT SIGNAL", "⚡"
    elif total >= 40: label, emoji = "MILD SIGNAL",   "👀"
    else:             label, emoji = "INFORMATIONAL", "📊"

    # --- Reasoning ---
    parts = []

    if cred >= 24:   parts.append(f"elite wallet (+${pnl:,.0f})")
    elif cred >= 18: parts.append(f"strong wallet (+${pnl:,.0f})")
    elif cred >= 11: parts.append(f"profitable wallet (+${pnl:,.0f})")
    elif cred == 0 and pnl < 0: parts.append(f"losing wallet (${pnl:,.0f})")
    else:            parts.append("limited track record")

    if pct >= 5:     parts.append(f"dominates market volume ({pct:.1f}% of 24h)")
    elif pct >= 2:   parts.append(f"notable volume share ({pct:.1f}% of 24h)")

    if conv >= 15:   parts.append(f"extreme conviction ({price_cents:.0f}¢)")
    elif conv >= 9:  parts.append(f"high conviction ({price_cents:.0f}¢)")
    elif conv <= 2:  parts.append("near 50/50 (weak signal)")

    if pm == 15:     parts.append("market confirmed ✓✓")
    elif pm == 9:    parts.append("market moving with them ✓")
    elif pm == 0:    parts.append("market moved against ✗")

    if cons >= 6:    parts.append(f"{same_side_whales + 1} whales agree")
    elif cons == 3:  parts.append("1 other whale agrees")

    return Score(total, cred, dom, conv, pm, cons, label, emoji,
                 ", ".join(parts) or "no standout factors")
