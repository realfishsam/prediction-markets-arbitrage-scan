from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pmxt


ROOT = Path(__file__).resolve().parents[1]

EXCHANGE_CLASSES = {
    "polymarket": pmxt.Polymarket,
    "kalshi": pmxt.Kalshi,
    "kalshi-demo": pmxt.KalshiDemo,
    "limitless": pmxt.Limitless,
    "probable": pmxt.Probable,
    "baozi": pmxt.Baozi,
    "myriad": pmxt.Myriad,
    "opinion": pmxt.Opinion,
    "metaculus": pmxt.Metaculus,
    "smarkets": pmxt.Smarkets,
    "polymarket_us": pmxt.PolymarketUS,
    "gemini-titan": pmxt.GeminiTitan,
    "hyperliquid": pmxt.Hyperliquid,
}


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def side_label(label: str) -> str:
    label = label.strip().lower()
    if label in {"yes", "y"}:
        return "yes"
    if label in {"no", "n"}:
        return "no"
    return label


def top_levels(levels: list[Any], count: int = 3) -> list[dict[str, float]]:
    return [
        {"price": float(level.price), "size": float(level.size)}
        for level in levels[:count]
    ]


def executable_size(levels: list[Any], target_price: float, side: str) -> float:
    if side == "buy":
        return sum(float(level.size) for level in levels if float(level.price) <= target_price)
    if side == "sell":
        return sum(float(level.size) for level in levels if float(level.price) >= target_price)
    raise ValueError(f"Unknown side: {side}")


def exchange_for(venue: str, api_key: str) -> Any:
    exchange_class = EXCHANGE_CLASSES.get(venue)
    if not exchange_class:
        raise ValueError(f"No SDK class mapped for venue: {venue}")
    return exchange_class(pmxt_api_key=api_key)


def find_candidate(markets: list[Any]) -> dict[str, Any] | None:
    quotes: dict[str, list[dict[str, Any]]] = {}
    for market in markets:
        venue = market.source_exchange
        for outcome in market.outcomes:
            bid = outcome.best_bid
            ask = outcome.best_ask
            if bid is None or ask is None:
                continue
            label = side_label(outcome.label)
            quotes.setdefault(label, []).append(
                {
                    "venue": venue,
                    "market": market,
                    "outcome": outcome,
                    "label": label,
                    "bid": float(bid),
                    "ask": float(ask),
                }
            )

    candidates: list[dict[str, Any]] = []
    for label_quotes in quotes.values():
        for buy in label_quotes:
            for sell in label_quotes:
                if buy["venue"] == sell["venue"] and buy["market"].market_id == sell["market"].market_id:
                    continue
                spread = sell["bid"] - buy["ask"]
                if spread > 0:
                    candidates.append({"buy": buy, "sell": sell, "spread": spread})

    return max(candidates, key=lambda candidate: candidate["spread"], default=None)


def main() -> None:
    load_dotenv()

    api_key = os.environ.get("PMXT_API_KEY")
    if not api_key:
        raise SystemExit("Set PMXT_API_KEY in .env")

    router = pmxt.Router(pmxt_api_key=api_key)
    clusters = router.fetch_matched_market_clusters(
        relations="identity",
        min_venues=2,
        with_orderbook=True,
        sort="volume",
        limit=20,
    )

    for cluster in clusters:
        candidate = find_candidate(cluster.markets)
        if not candidate:
            continue

        buy = candidate["buy"]
        sell = candidate["sell"]
        buy_exchange = exchange_for(buy["venue"], api_key)
        sell_exchange = exchange_for(sell["venue"], api_key)

        buy_book = buy_exchange.fetch_order_book(buy["outcome"], limit=20)
        sell_book = sell_exchange.fetch_order_book(sell["outcome"], limit=20)

        if not buy_book.asks or not sell_book.bids:
            continue

        live_buy_ask = float(buy_book.asks[0].price)
        live_sell_bid = float(sell_book.bids[0].price)
        live_spread = live_sell_bid - live_buy_ask
        buy_size = executable_size(buy_book.asks, live_sell_bid, "buy")
        sell_size = executable_size(sell_book.bids, live_buy_ask, "sell")

        print(f"cluster={cluster.canonical_title}")
        print(f"label={buy['label']}")
        print(f"cluster_spread={candidate['spread']:.6f}")
        print(f"live_orderbook_spread={live_spread:.6f}")
        print(
            "buy="
            f"{buy['venue']} market={buy['market'].market_id} "
            f"outcome={buy['outcome'].outcome_id} ask={buy['ask']}"
        )
        print(f"buy_book_asks={top_levels(buy_book.asks)}")
        print(f"buy_size_profitable_against_live_bid={buy_size}")
        print(
            "sell="
            f"{sell['venue']} market={sell['market'].market_id} "
            f"outcome={sell['outcome'].outcome_id} bid={sell['bid']}"
        )
        print(f"sell_book_bids={top_levels(sell_book.bids)}")
        print(f"sell_size_profitable_against_live_ask={sell_size}")
        print(f"max_matched_size={min(buy_size, sell_size)}")
        return

    print("No positive top-of-book candidate found in scanned clusters.")


if __name__ == "__main__":
    main()
