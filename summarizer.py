"""
Game Summary Aggregator — groups whale alerts by game and bet type.
Categories per game:
  ML      — Moneyline (team A vs team B)
  SPREAD  — Spread bets
  TOTAL   — Over/Under
"""

import re
import pickle
import logging
import requests
from collections import defaultdict
from datetime import datetime, timezone

log = logging.getLogger(__name__)

NHL_TEAMS = [
    "avalanche", "bruins", "sabres", "flames", "hurricanes", "blackhawks",
    "blue jackets", "stars", "red wings", "oilers", "panthers", "wild",
    "canadiens", "predators", "devils", "islanders", "rangers", "senators",
    "flyers", "penguins", "sharks", "kraken", "blues", "lightning",
    "maple leafs", "canucks", "golden knights", "capitals", "jets",
    "coyotes", "ducks", "nhl", "stanley cup"
]

NBA_TEAMS = [
    "hawks", "celtics", "nets", "hornets", "bulls", "cavaliers", "cavs",
    "mavericks", "mavs", "nuggets", "pistons", "warriors", "rockets",
    "pacers", "clippers", "lakers", "grizzlies", "heat", "bucks",
    "timberwolves", "wolves", "pelicans", "knicks", "thunder", "magic",
    "76ers", "sixers", "suns", "trail blazers", "blazers", "kings",
    "spurs", "raptors", "jazz", "wizards"
]


def _is_nba(title: str) -> bool:
    t = title.lower()
    if any(kw in t for kw in NHL_TEAMS):
        return False
    return any(kw in t for kw in NBA_TEAMS)


def _bet_type(title: str) -> str:
    """Classify market title as ML, SPREAD, or TOTAL."""
    t = title.lower()
    if any(x in t for x in ["o/u", "over", "under", "total points", "total"]):
        return "TOTAL"
    if any(x in t for x in ["spread", "-0.5", "-1.5", "-2.5", "-3.5",
                              "-4.5", "-5.5", "-6.5", "-7.5", "-8.5",
                              "-9.5", "-10.5", "-11.5", "-12.5", "-13.5",
                              "-14.5", "-15.5"]):
        return "SPREAD"
    return "ML"


def _extract_game_key(title: str) -> str | None:
    """Extract normalized 'Team A vs Team B' from any market title."""
    if not _is_nba(title):
        return None

    t = title.lower()

    # Strip known prefixes
    for prefix in ["spread: ", "nba playoffs: who will win series? - ",
                   "will the ", "game \\d+: "]:
        t = re.sub(prefix, "", t)

    # Strip suffixes
    for suffix in [r":\s*o/u.*", r":\s*spread.*", r":\s*1h.*",
                   r":\s*moneyline.*", r"\s+o/u.*", r"\s+spread.*",
                   r"\s+winner\?.*", r"\s+series.*", r"\s+finals.*",
                   r"\s+win the.*", r"\?.*"]:
        t = re.sub(suffix, "", t)

    t = t.strip()

    # Try "X vs Y" or "X at Y"
    vs_match = re.search(r'([\w\s]+?)\s+(?:vs\.?|at)\s+([\w\s]+?)$', t)
    if vs_match:
        team1 = vs_match.group(1).strip()
        team2 = vs_match.group(2).strip()
        # Validate at least one is an NBA team
        if any(kw in team1 for kw in NBA_TEAMS) or any(kw in team2 for kw in NBA_TEAMS):
            teams = sorted([team1.title(), team2.title()])
            return f"{teams[0]} vs {teams[1]}"

    # Fallback — find any NBA team mentioned
    for team in NBA_TEAMS:
        if team in t:
            return f"{team.title()} (futures)"

    return None


# ── Alert store ──────────────────────────────────────────────────────────────

class GameSummaryStore:

    def __init__(self, ttl_hours: int = 20):
        # game_key -> bet_type -> side -> list of alert dicts
        self._data: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        self._ttl = ttl_hours * 3600

    def _now(self) -> int:
        return int(datetime.now(timezone.utc).timestamp())

    def _purge_old(self):
        cutoff = self._now() - self._ttl
        for game in list(self._data.keys()):
            for btype in list(self._data[game].keys()):
                for side in list(self._data[game][btype].keys()):
                    self._data[game][btype][side] = [
                        a for a in self._data[game][btype][side]
                        if a["ts"] > cutoff
                    ]
                    if not self._data[game][btype][side]:
                        del self._data[game][btype][side]
                if not self._data[game][btype]:
                    del self._data[game][btype]
            if not self._data[game]:
                del self._data[game]

    def add_alert(self, title: str, side: str, price_cents: float,
                  usd: float, wallet: str, pnl: float,
                  score_total: int, score_label: str, ts: int):
        game_key = _extract_game_key(title)
        if not game_key:
            return
        bet_type = _bet_type(title)
        self._purge_old()
        self._data[game_key][bet_type][side].append({
            "usd":         usd,
            "price_cents": price_cents,
            "wallet":      wallet,
            "pnl":         pnl,
            "score":       score_total,
            "ts":          ts,
        })

    def get_all_games(self) -> list[str]:
        self._purge_old()
        return sorted(self._data.keys())

    def get_summary(self, game_key: str) -> str | None:
        self._purge_old()
        game_data = self._data.get(game_key)
        if not game_data:
            return None

        lines = [f"{'='*45}",
                 f"📊  {game_key.upper()}",
                 f"{'='*45}"]

        bet_order = ["ML", "SPREAD", "TOTAL"]
        bet_labels = {"ML": "💰 MONEYLINE", "SPREAD": "📐 SPREAD", "TOTAL": "📈 OVER/UNDER"}

        for btype in bet_order:
            sides = game_data.get(btype)
            if not sides:
                continue

            lines.append(f"\n{bet_labels[btype]}")
            lines.append("-" * 35)

            # Sort sides by total USD desc
            for side, alerts in sorted(
                sides.items(),
                key=lambda x: sum(a["usd"] for a in x[1]),
                reverse=True
            ):
                total_usd  = sum(a["usd"] for a in alerts)
                n_wallets  = len({a["wallet"] for a in alerts})
                avg_price  = sum(a["price_cents"] for a in alerts) / len(alerts)
                best_score = max(a["score"] for a in alerts)
                best_pnl   = max(a["pnl"] for a in alerts)
                emoji      = "🟢" if side in ("YES", "OVER") or any(
                    t in side.lower() for t in NBA_TEAMS
                ) else "🔴"

                lines.append(
                    f"\n{emoji} {side}"
                    f"\n   Total bet:  ${total_usd:,.0f}"
                    f"\n   Wallets:    {n_wallets}"
                    f"\n   Avg price:  {avg_price:.1f}¢"
                    f"\n   Best score: {best_score}/100"
                    f"\n   Top PnL:    +${best_pnl:,.0f}"
                )

                # Top 3 by size
                top_size = sorted(alerts, key=lambda x: x["usd"], reverse=True)[:3]
                lines.append("   📌 Biggest bets:")
                for b in top_size:
                    lines.append(
                        f"      ${b['usd']:,.0f} @ {b['price_cents']:.1f}¢"
                        f"  [{b['wallet'][:10]}…  +${b['pnl']:,.0f}]"
                        f"  ({b['score']}/100)"
                    )

                # Top 3 elite wallets by PnL (unique wallets)
                seen = set()
                elite = []
                for b in sorted(alerts, key=lambda x: x["pnl"], reverse=True):
                    if b["wallet"] not in seen:
                        seen.add(b["wallet"])
                        elite.append(b)
                    if len(elite) == 3:
                        break

                if elite and elite[0]["pnl"] > 50_000:
                    lines.append("   🏆 Elite wallets:")
                    for b in elite:
                        wallet_total = sum(
                            a["usd"] for a in alerts if a["wallet"] == b["wallet"]
                        )
                        lines.append(
                            f"      +${b['pnl']:,.0f} PnL — "
                            f"${wallet_total:,.0f} on this side"
                        )

        # Overall lean per category
        lines.append(f"\n{'─'*35}")
        lines.append("📋 LEAN SUMMARY")
        for btype in bet_order:
            sides = game_data.get(btype)
            if not sides:
                continue
            totals = {s: sum(a["usd"] for a in alerts) for s, alerts in sides.items()}
            if totals:
                top = max(totals, key=totals.get)
                total_all = sum(totals.values())
                pct = totals[top] / total_all * 100 if total_all else 0
                lines.append(
                    f"  {bet_labels[btype]}: {top} "
                    f"(${totals[top]:,.0f} / {pct:.0f}% of money)"
                )

        return "\n".join(lines)

    def get_all_summaries_text(self) -> str:
        games = self.get_all_games()
        if not games:
            return "No active game data yet."
        return "\n\n".join(
            self.get_summary(g) for g in games if self.get_summary(g)
        )
