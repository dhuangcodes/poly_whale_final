"""
Kalshi NBA whale monitor.
Uses public endpoints only — no auth required.
Base: https://api.elections.kalshi.com/trade-api/v2

Scoring (0-100):
  1. Trade Size       — 50 pts (replaces wallet credibility)
  2. Consensus        — 30 pts (same side, same market, last hour)
  3. Price Conviction — 20 pts (only counts if trade >= $10k)
"""
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from collections import defaultdict
from config import WEBHOOK_NBA

log = logging.getLogger(__name__)

BASE = "https://api.elections.kalshi.com/trade-api/v2"
SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json"})

# Kalshi NBA series tickers — add more as playoffs progress
NBA_SERIES = [
    "KXNBA",        # generic NBA
    "NBACHAMPION",  # NBA champion futures
    "NBAFINALS",    # Finals markets
    "KXNBAFINALS",
    "KXNBACHAMP",
]

# Keywords to identify NBA markets from title
NBA_KEYWORDS = [
    "nba", "hawks", "celtics", "nets", "hornets", "bulls", "cavaliers",
    "mavericks", "nuggets", "pistons", "warriors", "rockets", "pacers",
    "clippers", "lakers", "grizzlies", "heat", "bucks", "timberwolves",
    "pelicans", "knicks", "thunder", "magic", "76ers", "suns",
    "blazers", "kings", "spurs", "raptors", "jazz", "wizards", "playoff",
    "trail blazers"
]

COLORS = {
    "STRONG SIGNAL": 0xFF4500,
    "DECENT SIGNAL": 0xFFD700,
    "MILD SIGNAL":   0x00BFFF,
    "INFORMATIONAL": 0x888888,
}

MIN_KALSHI_TRADE = 3000  # minimum USD to alert on


@dataclass
class KalshiScore:
    total: int
    size_pts: int
    consensus_pts: int
    conviction_pts: int
    label: str
    emoji: str
    reason: str


def _get(path: str, params: dict = {}, retries: int = 3):
    for i in range(retries):
        try:
            r = SESSION.get(f"{BASE}{path}", params=params, timeout=12)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            if e.response.status_code == 429:
                time.sleep(2 ** i)
            elif e.response.status_code in (400, 404):
                return None
            else:
                time.sleep(1)
        except Exception:
            time.sleep(1)
    return None


def _format_est(ts_str: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        est = dt.astimezone(timezone(timedelta(hours=-5)))
        return est.strftime("%b %d %I:%M %p EST")
    except Exception:
        return "unknown"


def _bar(n: int) -> str:
    return "█" * round(n / 10) + "░" * (10 - round(n / 10))


def get_nba_markets(limit: int = 100) -> list[dict]:
    """Fetch active NBA markets from Kalshi."""
    markets = []
    # Search by NBA keyword
    data = _get("/markets", {
        "status": "open",
        "limit": limit,
        "tags": "sports",
    })
    if data and data.get("markets"):
        for m in data["markets"]:
            title = (m.get("title") or m.get("subtitle") or "").lower()
            if any(kw in title for kw in NBA_KEYWORDS):
                markets.append(m)
    return markets


def get_recent_trades(ticker: str, limit: int = 50) -> list[dict]:
    """Get recent trades for a market ticker."""
    data = _get(f"/markets/{ticker}/trades", {"limit": limit})
    if data and data.get("trades"):
        return data["trades"]
    return []


def kalshi_score(usd: float, price_cents: float, same_side: int) -> KalshiScore:
    # 1. Trade Size (50 pts)
    if usd >= 100_000:   sz = 50
    elif usd >= 50_000:  sz = 40
    elif usd >= 25_000:  sz = 28
    elif usd >= 10_000:  sz = 16
    elif usd >= 5_000:   sz = 7
    else:                sz = 0

    # 2. Consensus (30 pts)
    if same_side >= 4:   cons = 30
    elif same_side >= 3: cons = 22
    elif same_side >= 2: cons = 14
    elif same_side == 1: cons = 7
    else:                cons = 0

    # 3. Price Conviction (20 pts) — only if trade >= $10k
    if usd >= 10_000:
        p = price_cents
        if   p <= 15 or p >= 85: conv = 20
        elif p <= 25 or p >= 75: conv = 16
        elif p <= 35 or p >= 65: conv = 11
        elif p <= 45 or p >= 55: conv = 6
        else:                    conv = 3
    else:
        conv = 0

    total = min(100, sz + cons + conv)

    if total >= 80:   label, emoji = "STRONG SIGNAL", "🔥"
    elif total >= 60: label, emoji = "DECENT SIGNAL", "⚡"
    elif total >= 40: label, emoji = "MILD SIGNAL",   "👀"
    else:             label, emoji = "INFORMATIONAL", "📊"

    parts = []
    if sz >= 40:   parts.append(f"massive trade (${usd:,.0f})")
    elif sz >= 28: parts.append(f"large trade (${usd:,.0f})")
    elif sz >= 16: parts.append(f"solid trade (${usd:,.0f})")
    else:          parts.append(f"trade (${usd:,.0f})")

    if cons >= 22: parts.append(f"{same_side + 1} trades same side 🐋")
    elif cons >= 7: parts.append(f"{same_side} other trade(s) same side")

    if conv >= 16: parts.append(f"high conviction ({price_cents:.0f}¢)")
    elif conv >= 6: parts.append(f"moderate conviction ({price_cents:.0f}¢)")

    return KalshiScore(total, sz, cons, conv, label, emoji,
                       ", ".join(parts) or "no standout factors")


def send_kalshi_alert(trade: dict, market: dict, s: KalshiScore, same_side: int):
    if not WEBHOOK_NBA:
        return

    title = market.get("title") or market.get("subtitle") or trade.get("ticker", "")
    side = "YES" if trade.get("taker_side") == "yes" else "NO"
    price = float(trade.get("yes_price_dollars") or 0) * 100
    if side == "NO":
        price = 100 - price
    usd = float(trade.get("count_fp") or trade.get("count", 0)) * float(trade.get("yes_price_dollars") or 0)
    ts = trade.get("created_time", "")

    side_e = "🟢" if side == "YES" else "🔴"
    cons_str = f"{same_side + 1} trades this side" if same_side > 0 else "first trade this side"

    embed = {
        "title": f"{s.emoji} {s.label} — Kalshi Whale",
        "color": COLORS.get(s.label, 0x888888),
        "fields": [
            {"name": "📌 Market",
             "value": title,
             "inline": False},
            {"name": f"{side_e} Side & Price",
             "value": f"**{side}** @ **{price:.1f}¢**",
             "inline": True},
            {"name": "💰 Size",
             "value": f"**${usd:,.0f}**",
             "inline": True},
            {"name": "📊 Confidence Score",
             "value": f"`{_bar(s.total)}` **{s.total}/100**\n{s.reason}",
             "inline": False},
            {"name": "🔬 Breakdown",
             "value": (f"Size: `{s.size_pts}/50` • "
                       f"Consensus: `{s.consensus_pts}/30` • "
                       f"Conviction: `{s.conviction_pts}/20`"),
             "inline": False},
            {"name": "📈 Context",
             "value": cons_str,
             "inline": False},
        ],
        "footer": {"text": f"Kalshi Whale Alert  •  Trade placed: {_format_est(ts)}"},
    }

    try:
        r = requests.post(WEBHOOK_NBA, json={"embeds": [embed]}, timeout=5)
        r.raise_for_status()
        log.info(f"✅ [KALSHI NBA] ${usd:,.0f} {side} @ {price:.1f}¢ [{s.total}/100] — {title[:50]}")
    except Exception as e:
        log.error(f"Kalshi Discord failed: {e}")


class KalshiMonitor:
    def __init__(self):
        self.seen: set = set()
        self.markets: list = []
        self.last_market_refresh = 0
        self.consensus_log: dict = defaultdict(list)  # ticker -> [(ts, side)]
        self.MARKET_REFRESH = 3600  # refresh market list every hour
        self.CONSENSUS_WINDOW = 3600

    def refresh_markets(self):
        now = time.time()
        if now - self.last_market_refresh > self.MARKET_REFRESH or not self.markets:
            log.info("Refreshing Kalshi NBA markets...")
            self.markets = get_nba_markets()
            self.last_market_refresh = now
            log.info(f"Found {len(self.markets)} Kalshi NBA markets")

    def poll(self):
        self.refresh_markets()
        now = int(time.time())

        for market in self.markets:
            ticker = market.get("ticker", "")
            if not ticker:
                continue

            trades = get_recent_trades(ticker, limit=20)
            for trade in trades:
                trade_id = trade.get("trade_id") or trade.get("id", "")
                if not trade_id or trade_id in self.seen:
                    continue

                # Calculate USD size
                try:
                    count = float(trade.get("count_fp") or trade.get("count", 0))
                    price_d = float(trade.get("yes_price_dollars") or 0)
                    taker = trade.get("taker_side", "yes")
                    usd = count * price_d if taker == "yes" else count * (1 - price_d)
                except Exception:
                    continue

                if usd < MIN_KALSHI_TRADE:
                    self.seen.add(trade_id)
                    continue

                self.seen.add(trade_id)

                # Price in cents
                price_cents = price_d * 100 if taker == "yes" else (1 - price_d) * 100
                side = "YES" if taker == "yes" else "NO"

                # Consensus
                cutoff = now - self.CONSENSUS_WINDOW
                self.consensus_log[ticker] = [
                    (t, s) for t, s in self.consensus_log[ticker]
                    if t > cutoff
                ]
                same_side = sum(1 for t, s in self.consensus_log[ticker] if s == side)
                self.consensus_log[ticker].append((now, side))

                s = kalshi_score(usd, price_cents, same_side)
                send_kalshi_alert(trade, market, s, same_side)

        # Cleanup
        if len(self.seen) > 10_000:
            self.seen = set(list(self.seen)[-2000:])
