from __future__ import annotations

import os
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

import pmxt


ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def value(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def dataclass_field_names(obj: Any) -> list[str]:
    if not is_dataclass(obj):
        return []
    return [field.name for field in fields(obj)]


def summarize_market(market: Any) -> dict[str, Any]:
    outcomes = value(market, "outcomes") or []
    return {
        "venue": value(market, "source_exchange", "venue", "exchange"),
        "market_id": value(market, "market_id", "marketId", "id"),
        "title": value(market, "title", "question"),
        "best_bid": value(market, "best_bid", "bestBid"),
        "best_ask": value(market, "best_ask", "bestAsk"),
        "outcomes": [
            {
                "label": value(outcome, "label", "name", "outcome"),
                "price": value(outcome, "price"),
                "best_bid": value(outcome, "best_bid", "bestBid"),
                "best_ask": value(outcome, "best_ask", "bestAsk"),
            }
            for outcome in outcomes[:4]
        ],
    }


def summarize_event(event: Any) -> dict[str, Any]:
    markets = value(event, "markets") or []
    return {
        "venue": value(event, "source_exchange", "venue", "exchange"),
        "event_id": value(event, "id", "event_id", "eventId"),
        "title": value(event, "title"),
        "market_count": len(markets),
        "first_market": summarize_market(markets[0]) if markets else None,
    }


def print_market_clusters(clusters: list[Any]) -> None:
    print(f"market_clusters_count={len(clusters)}")
    if not clusters:
        return

    first = clusters[0]
    print(f"market_cluster_fields={dataclass_field_names(first)}")
    for index, cluster in enumerate(clusters, start=1):
        print(f"\nmarket_cluster[{index}]")
        print(f"  cluster_id={cluster.cluster_id}")
        print(f"  title={cluster.canonical_title}")
        print(f"  relations={cluster.relations}")
        print(f"  confidence={cluster.confidence}")
        print(f"  category={cluster.category}")
        print(f"  volume_24h={cluster.volume_24h}")
        print(f"  markets_count={len(cluster.markets)}")
        print(f"  raw_matches_count={len(cluster.raw_matches or [])}")
        print(f"  market_fields={dataclass_field_names(cluster.markets[0]) if cluster.markets else []}")
        for market in cluster.markets[:3]:
            print(f"  market={summarize_market(market)}")
        spreads = find_simple_cross_venue_spreads(cluster.markets)
        for spread in spreads[:3]:
            print(f"  candidate_spread={spread}")


def print_event_clusters(clusters: list[Any]) -> None:
    print(f"event_clusters_count={len(clusters)}")
    if not clusters:
        return

    first = clusters[0]
    print(f"event_cluster_fields={dataclass_field_names(first)}")
    for index, cluster in enumerate(clusters, start=1):
        print(f"\nevent_cluster[{index}]")
        print(f"  cluster_id={cluster.cluster_id}")
        print(f"  title={cluster.canonical_title}")
        print(f"  relations={cluster.relations}")
        print(f"  confidence={cluster.confidence}")
        print(f"  category={cluster.category}")
        print(f"  volume_24h={cluster.volume_24h}")
        print(f"  events_count={len(cluster.events)}")
        print(f"  raw_matches_count={len(cluster.raw_matches or [])}")
        print(f"  event_fields={dataclass_field_names(cluster.events[0]) if cluster.events else []}")
        for event in cluster.events[:3]:
            print(f"  event={summarize_event(event)}")


def normalized_label(label: Any) -> str:
    if label is None:
        return ""
    label = str(label).strip().lower()
    if label in {"yes", "y"}:
        return "yes"
    if label in {"no", "n"}:
        return "no"
    return label


def find_simple_cross_venue_spreads(markets: list[Any]) -> list[dict[str, Any]]:
    quotes: dict[str, list[dict[str, Any]]] = {}
    for market in markets:
        for outcome in value(market, "outcomes") or []:
            label = normalized_label(value(outcome, "label", "name", "outcome"))
            bid = value(outcome, "best_bid", "bestBid")
            ask = value(outcome, "best_ask", "bestAsk")
            if bid is None or ask is None:
                continue
            quotes.setdefault(label, []).append(
                {
                    "venue": value(market, "source_exchange", "venue", "exchange"),
                    "market_id": value(market, "market_id", "marketId", "id"),
                    "label": label,
                    "bid": float(bid),
                    "ask": float(ask),
                }
            )

    spreads: list[dict[str, Any]] = []
    for label, label_quotes in quotes.items():
        for buy in label_quotes:
            for sell in label_quotes:
                if buy["venue"] == sell["venue"] and buy["market_id"] == sell["market_id"]:
                    continue
                spread = sell["bid"] - buy["ask"]
                if spread > 0:
                    spreads.append(
                        {
                            "label": label,
                            "buy_venue": buy["venue"],
                            "buy_ask": buy["ask"],
                            "sell_venue": sell["venue"],
                            "sell_bid": sell["bid"],
                            "spread": round(spread, 6),
                        }
                    )

    return sorted(spreads, key=lambda item: item["spread"], reverse=True)


def main() -> None:
    load_dotenv()

    api_key = os.environ.get("PMXT_API_KEY")
    if not api_key:
        raise SystemExit("Set PMXT_API_KEY in .env")

    router = pmxt.Router(pmxt_api_key=api_key)

    market_clusters = router.fetch_matched_market_clusters(
        relations="identity",
        min_venues=2,
        with_orderbook=True,
        include_raw_matches=True,
        sort="volume",
        limit=3,
    )
    print_market_clusters(market_clusters)

    print("\n---\n")

    event_clusters = router.fetch_matched_event_clusters(
        relations="identity",
        min_venues=2,
        include_raw_matches=True,
        sort="volume",
        limit=3,
    )
    print_event_clusters(event_clusters)


if __name__ == "__main__":
    main()
