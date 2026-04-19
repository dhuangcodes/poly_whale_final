import re
import logging
import requests
from datetime import datetime, timezone, timedelta
from config import (WEBHOOK_NBA, WEBHOOK_MLB, WEBHOOK_TENNIS,
                    WEBHOOK_VIDEOGAMES, WEBHOOK_OTHER)
from scorer import Score

log = logging.getLogger(__name__)

COLORS = {
    "STRONG SIGNAL": 0xFF4500,
    "DECENT SIGNAL": 0xFFD700,
    "MILD SIGNAL":   0x00BFFF,
    "INFORMATIONAL": 0x888888,
}

# Keywords to route alerts to the right channel
NBA_TEAMS = [
    "hawks", "celtics", "nets", "hornets", "bulls", "cavaliers", "mavericks",
    "nuggets", "pistons", "warriors", "rockets", "pacers", "clippers", "lakers",
    "grizzlies", "heat", "bucks", "timberwolves", "pelicans", "knicks", "thunder",
    "magic", "76ers", "suns", "trail blazers", "blazers", "kings", "spurs",
    "raptors", "jazz", "wizards", "nba", "o/u", "over/under"
]
MLB_TEAMS = [
    "yankees", "red sox", "dodgers", "giants", "cubs", "white sox", "reds",
    "indians", "guardians", "rockies", "tigers", "astros", "royals", "angels",
    "marlins", "brewers", "twins", "mets", "phillies", "pirates", "padres",
    "cardinals", "rays", "rangers", "blue jays", "nationals", "orioles",
    "athletics", "mariners", "braves", "mlb"
]
TENNIS_KEYWORDS = [
    "atp", "wta", "vs", "open", "wimbledon", "roland garros", "us open",
    "australian open", "grand slam", "challenger", "wuning", "tennis"
]
VIDEOGAME_KEYWORDS = [
    "cs2", "csgo", "valorant", "league of legends", "lol", "dota", "fortnite",
    "overwatch", "call of duty", "cod", "navi", "natus vincere", "faze", "vitality",
    "astralis", "g2", "fnatic", "team liquid", "esport", "gaming", "major",
    "blast", "pgl", "iem", "esl", "map", "rounds"
]


def _get_webhook(market_title: str) -> str:
    """Route alert to correct channel based on market title keywords."""
    title_lower = market_title.lower()

    # Check NBA first
    for team in NBA_TEAMS:
        if team in title_lower:
            return WEBHOOK_NBA

    # Check MLB
    for team in MLB_TEAMS:
        if team in title_lower:
            return WEBHOOK_MLB

    # Check esports/video games
    for kw in VIDEOGAME_KEYWORDS:
        if kw in title_lower:
            return WEBHOOK_VIDEOGAMES

    # Check tennis — "X vs Y" pattern with no team sports context
    for kw in TENNIS_KEYWORDS:
        if kw in title_lower:
            return WEBHOOK_TENNIS

    # Fallback
    return WEBHOOK_OTHER


def _bar(n: int) -> str:
    return "█" * round(n / 10) + "░" * (10 - round(n / 10))

def _pnl(v: float) -> str:
    return f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"

def _short(addr: str) -> str:
    return f"{addr[:6]}...{addr[-4:]}" if len(addr) > 10 else addr

def _format_est(ts: int) -> str:
    if not ts:
        return "unknown"
    est = timezone(timedelta(hours=-5))
    dt = datetime.fromtimestamp(ts, tz=est)
    return dt.strftime("%b %d %I:%M %p EST")


class Alerter:
    def __init__(self):
        pass  # no threads needed anymore

    def send(self, trade: dict, s: Score):
        webhook = _get_webhook(trade["market_title"])
        if not webhook:
            self._console(trade, s)
            return

        embed = self._build_embed(trade, s)
        try:
            r = requests.post(webhook, json={"embeds": [embed]}, timeout=5)
            r.raise_for_status()
            log.info(f"✅ [{_route_name(trade['market_title'])}] "
                     f"${trade['usd']:,.0f} {trade['outcome']} @ {trade['price_cents']:.1f}¢ "
                     f"[{s.total}/100] — {trade['market_title'][:50]}")
        except Exception as e:
            log.error(f"Discord failed: {e}")
            self._console(trade, s)

    def _build_embed(self, trade: dict, s: Score) -> dict:
        usd    = trade["usd"]
        side   = trade["outcome"]
        wallet = trade["wallet"]
        pnl    = trade["pnl"]
        side_e = "🟢" if side in ("YES", "OVER") or (len(side) > 2 and side not in ("NO", "UNDER")) else "🔴"

        pa = trade.get("price_after", 0)
        pc = trade["price_cents"]
        if pa > 0 and pc > 0:
            diff = (pa - pc) if side in ("YES",) else (pc - pa)
            move_str = f"{'▲' if diff > 0 else '▼'} {abs(diff):.1f}¢ after trade"
        else:
            move_str = "price data unavailable"

        sw = trade.get("same_side_whales", 0)
        cons_str = f"{sw + 1} whales on this side" if sw > 0 else "first whale on this side"

        return {
            "title": f"{s.emoji} {s.label} — Polymarket Whale",
            "color": COLORS.get(s.label, 0x888888),
            "fields": [
                {"name": "📌 Market",
                 "value": trade["market_title"],
                 "inline": False},
                {"name": f"{side_e} Side & Price",
                 "value": f"**{side}** @ **{trade['price_cents']:.1f}¢**",
                 "inline": True},
                {"name": "💰 Size",
                 "value": f"**${usd:,.0f}**",
                 "inline": True},
                {"name": "👛 Wallet",
                 "value": f"`{_short(wallet)}`  |  All-time PnL: **{_pnl(pnl)}**",
                 "inline": False},
                {"name": "📊 Confidence Score",
                 "value": f"`{_bar(s.total)}` **{s.total}/100**\n{s.reason}",
                 "inline": False},
                {"name": "🔬 Breakdown",
                 "value": (
                     f"Credibility: `{s.credibility}/50` • "
                     f"Consensus: `{s.consensus}/30` • "
                     f"Conviction: `{s.conviction}/20` • "
                     f"Mkt Move: `{s.price_move:+d}`"
                 ),
                 "inline": False},
                {"name": "📈 Context",
                 "value": f"{move_str}  |  {cons_str}",
                 "inline": False},
                {"name": "🔗 Links",
                 "value": (f"[Market]({trade['market_url']}) • "
                           f"[Wallet](https://polymarket.com/profile/{wallet})"),
                 "inline": False},
            ],
            "footer": {"text": f"Polymarket Whale Alert  •  Trade placed: {_format_est(trade.get('timestamp', 0))}"},
        }

    def _console(self, trade: dict, s: Score):
        print(f"\n{'='*60}")
        print(f"{s.emoji} {s.label} [{s.total}/100]")
        print(f"Market : {trade['market_title']}")
        print(f"Side   : {trade['outcome']} @ {trade['price_cents']:.1f}¢")
        print(f"Size   : ${trade['usd']:,.0f}")
        print(f"Wallet : {_short(trade['wallet'])} | {_pnl(trade['pnl'])}")
        print(f"Reason : {s.reason}")
        print(f"Link   : {trade['market_url']}")
        print(f"{'='*60}\n")


def _route_name(title: str) -> str:
    """Human readable channel name for logging."""
    t = title.lower()
    for team in NBA_TEAMS:
        if team in t: return "NBA"
    for team in MLB_TEAMS:
        if team in t: return "MLB"
    for kw in VIDEOGAME_KEYWORDS:
        if kw in t: return "GAMES"
    for kw in TENNIS_KEYWORDS:
        if kw in t: return "TENNIS"
    return "OTHER"
