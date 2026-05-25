from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Mapping

import pmxt


VENUE_EXCHANGE_CLASSES: Mapping[str, type[Any]] = {
    "polymarket": pmxt.Polymarket,
    "kalshi": pmxt.Kalshi,
    "limitless": pmxt.Limitless,
    "opinion": pmxt.Opinion,
}


@dataclass(frozen=True)
class OrderBookSummary:
    best_bid: float | None
    best_ask: float | None
    bid_depth: float
    ask_depth: float
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    timestamp: int | None = None
    datetime: str | None = None


class LiveOrderBookWatcher:
    def __init__(
        self,
        venue: str,
        outcome_id: Any,
        *,
        pmxt_api_key: str | None = None,
        limit: int | None = None,
        params: dict[str, Any] | None = None,
        exchange: Any | None = None,
        **exchange_kwargs: Any,
    ) -> None:
        self.venue = normalize_venue(venue)
        self.outcome_id = outcome_id
        self.limit = limit
        self.params = params
        self.exchange = exchange or exchange_for_venue(
            self.venue,
            pmxt_api_key=pmxt_api_key,
            **exchange_kwargs,
        )
        self.latest_book: Any | None = None

    def watch_once(self) -> Any:
        self.latest_book = self.exchange.watch_order_book(
            self.outcome_id,
            limit=self.limit,
            params=self.params,
        )
        return self.latest_book

    def watch(self) -> Iterator[Any]:
        while True:
            yield self.watch_once()

    def summaries(self, *, depth: int | None = None) -> Iterator[OrderBookSummary]:
        for book in self.watch():
            yield summarize_order_book(book, depth=depth)

    def latest_summary(self, *, depth: int | None = None) -> OrderBookSummary | None:
        if self.latest_book is None:
            return None
        return summarize_order_book(self.latest_book, depth=depth)


def normalize_venue(venue: str) -> str:
    return venue.strip().lower()


def exchange_for_venue(
    venue: str,
    *,
    pmxt_api_key: str | None = None,
    **exchange_kwargs: Any,
) -> Any:
    normalized = normalize_venue(venue)
    exchange_class = VENUE_EXCHANGE_CLASSES.get(normalized)
    if exchange_class is None:
        supported = ", ".join(sorted(VENUE_EXCHANGE_CLASSES))
        raise ValueError(f"Unsupported venue {venue!r}; expected one of: {supported}")
    return exchange_class(pmxt_api_key=pmxt_api_key, **exchange_kwargs)


def watch_order_book(
    venue: str,
    outcome_id: Any,
    *,
    pmxt_api_key: str | None = None,
    limit: int | None = None,
    params: dict[str, Any] | None = None,
    **exchange_kwargs: Any,
) -> Iterator[Any]:
    watcher = LiveOrderBookWatcher(
        venue,
        outcome_id,
        pmxt_api_key=pmxt_api_key,
        limit=limit,
        params=params,
        **exchange_kwargs,
    )
    return watcher.watch()


def summarize_order_book(book: Any, *, depth: int | None = None) -> OrderBookSummary:
    bids = _levels(getattr(book, "bids", []), depth)
    asks = _levels(getattr(book, "asks", []), depth)
    return OrderBookSummary(
        best_bid=bids[0][0] if bids else None,
        best_ask=asks[0][0] if asks else None,
        bid_depth=sum(size for _, size in bids),
        ask_depth=sum(size for _, size in asks),
        bids=bids,
        asks=asks,
        timestamp=getattr(book, "timestamp", None),
        datetime=getattr(book, "datetime", None),
    )


def _levels(levels: list[Any], depth: int | None) -> tuple[tuple[float, float], ...]:
    visible_levels = levels if depth is None else levels[:depth]
    return tuple(_price_size(level) for level in visible_levels)


def _price_size(level: Any) -> tuple[float, float]:
    if isinstance(level, dict):
        return float(level["price"]), float(level["size"])
    if isinstance(level, (list, tuple)):
        return float(level[0]), float(level[1])
    return float(level.price), float(level.size)
