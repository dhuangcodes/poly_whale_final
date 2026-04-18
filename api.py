"""
All Polymarket API calls in one place.
Uses only public, no-auth endpoints:
  - data-api.polymarket.com  (profiles, leaderboard, activity)
  - gamma-api.polymarket.com (market titles/slugs/volume)
"""
import logging
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)
DATA  = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"

SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json"})


def _get(url: str, params: dict = {}, retries: int = 3):
    for i in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=12)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            code = e.response.status_code
            if code == 429:
                time.sleep(2 ** i)
            elif code in (400, 404):
                return None
            else:
                if i == retries - 1:
                    return None
                time.sleep(1)
        except Exception:
            if i == retries - 1:
                return None
            time.sleep(1)
    return None


def get_leaderboard(limit: int = 300) -> list[dict]:
    data = _get(f"{DATA}/v1/leaderboard", {"limit": limit})
    if data is None:
        log.error("Leaderboard returned None")
        return []
    if isinstance(data, list):
        log.info(f"Leaderboard: {len(data)} wallets loaded")
        return data
    if isinstance(data, dict):
        for key in ("leaderboard", "data", "results", "traders"):
            entries = data.get(key)
            if entries and isinstance(entries, list):
                log.info(f"Leaderboard: {len(entries)} wallets loaded")
                return entries
    log.error(f"Unexpected leaderboard response: {str(data)[:100]}")
    return []


def get_wallet_activity(address: str, limit: int = 20) -> list[dict]:
    data = _get(f"{DATA}/activity", {
        "user": address,
        "type": "TRADE",
        "limit": limit,
    })
    if isinstance(data, list):
        return data
    return []


def get_wallet_profile(address: str) -> dict:
    data = _get(f"{DATA}/profile", {"user": address})
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}


def get_market_by_slug(slug: str) -> dict:
    """Fetch market info by slug — most reliable method."""
    data = _get(f"{GAMMA}/markets", {"slug": slug})
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict) and data.get("markets"):
        return data["markets"][0]
    return {}


def get_market_by_condition(condition_id: str) -> dict:
    """Fetch market info by conditionId."""
    for param in [
        {"id": condition_id},
        {"condition_id": condition_id},
    ]:
        data = _get(f"{GAMMA}/markets", param)
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict) and data.get("markets"):
            return data["markets"][0]
    return {}


def get_market_by_event_slug(event_slug: str) -> dict:
    """
    Fetch event info by eventSlug and return the highest-volume market.
    This correctly gets ML volume instead of a sub-market volume.
    """
    data = _get(f"{GAMMA}/events", {"slug": event_slug})
    events = data if isinstance(data, list) else ([data] if isinstance(data, dict) and data else [])
    if not events:
        return {}

    event = events[0]
    markets = event.get("markets", [])

    # Use event-level volume as the authoritative number
    event_volume = float(event.get("volume24hr") or event.get("volume") or 0)

    if markets:
        # Pick the highest-volume sub-market (usually the moneyline)
        best = max(markets, key=lambda m: float(m.get("volume24hr") or m.get("volume") or 0))
        result = best.copy()
        # Use event-level volume if higher (more accurate for ML)
        result["volume24hr"] = max(
            event_volume,
            float(best.get("volume24hr") or 0)
        )
        result["question"] = event.get("title") or best.get("question", "")
        return result

    # No markets, return event info directly
    return {
        "question": event.get("title", ""),
        "volume24hr": event_volume,
        "outcomePrices": None,
    }


def batch_get_activity(wallets: list[str], limit: int = 10) -> dict[str, list]:
    results = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(get_wallet_activity, w, limit): w for w in wallets}
        for future in as_completed(futures):
            wallet = futures[future]
            try:
                results[wallet] = future.result() or []
            except Exception:
                results[wallet] = []
    return results
