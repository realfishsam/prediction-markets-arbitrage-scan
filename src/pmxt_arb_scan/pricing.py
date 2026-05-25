from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class Level:
    price: float
    size: float


@dataclass(frozen=True)
class ExecutableSpread:
    buy_price: float | None
    sell_price: float | None
    spread: float | None
    size: float
    gross_edge: float
    average_spread: float | None


def _value(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_level(level: Any) -> Level | None:
    """Return a simple price/size level from dicts, SDK objects, or tuples."""
    if isinstance(level, (list, tuple)):
        if len(level) < 2:
            return None
        price = _to_float(level[0])
        size = _to_float(level[1])
    else:
        price = _to_float(_value(level, "price", "px", "p"))
        size = _to_float(_value(level, "size", "quantity", "qty", "amount"))

    if price is None or size is None or size <= 0:
        return None
    return Level(price=price, size=size)


def normalize_levels(levels: Iterable[Any] | None, *, side: str | None = None) -> list[Level]:
    normalized = [level for raw in levels or () if (level := normalize_level(raw))]
    if side is None:
        return normalized

    side = side.lower()
    if side in {"bid", "bids", "sell"}:
        return sorted(normalized, key=lambda level: level.price, reverse=True)
    if side in {"ask", "asks", "buy"}:
        return sorted(normalized, key=lambda level: level.price)
    raise ValueError(f"Unknown order book side: {side}")


def best_bid(bids: Iterable[Any] | None) -> Level | None:
    levels = normalize_levels(bids, side="bid")
    return levels[0] if levels else None


def best_ask(asks: Iterable[Any] | None) -> Level | None:
    levels = normalize_levels(asks, side="ask")
    return levels[0] if levels else None


def size_at_price(levels: Iterable[Any] | None, target_price: float, side: str) -> float:
    side = side.lower()
    target = float(target_price)
    book = normalize_levels(levels, side=side)

    if side in {"ask", "asks", "buy"}:
        return sum(level.size for level in book if level.price <= target)
    if side in {"bid", "bids", "sell"}:
        return sum(level.size for level in book if level.price >= target)
    raise ValueError(f"Unknown order book side: {side}")


def price_cross(
    buy_asks: Iterable[Any] | None,
    sell_bids: Iterable[Any] | None,
    *,
    min_spread: float = 0.0,
) -> ExecutableSpread:
    """Price buying from asks and selling into bids, ignoring fees/slippage."""
    asks = normalize_levels(buy_asks, side="ask")
    bids = normalize_levels(sell_bids, side="bid")

    if not asks or not bids:
        return ExecutableSpread(
            buy_price=asks[0].price if asks else None,
            sell_price=bids[0].price if bids else None,
            spread=None,
            size=0.0,
            gross_edge=0.0,
            average_spread=None,
        )

    top_ask = asks[0]
    top_bid = bids[0]
    top_spread = top_bid.price - top_ask.price
    min_edge = float(min_spread)
    matched_size = 0.0
    gross_edge = 0.0
    ask_index = 0
    bid_index = 0
    ask_remaining = top_ask.size
    bid_remaining = top_bid.size

    while ask_index < len(asks) and bid_index < len(bids):
        ask = asks[ask_index]
        bid = bids[bid_index]
        spread = bid.price - ask.price
        if spread <= min_edge:
            break

        size = min(ask_remaining, bid_remaining)
        matched_size += size
        gross_edge += size * spread
        ask_remaining -= size
        bid_remaining -= size

        if ask_remaining <= 0:
            ask_index += 1
            if ask_index < len(asks):
                ask_remaining = asks[ask_index].size
        if bid_remaining <= 0:
            bid_index += 1
            if bid_index < len(bids):
                bid_remaining = bids[bid_index].size

    average_spread = gross_edge / matched_size if matched_size else None
    return ExecutableSpread(
        buy_price=top_ask.price,
        sell_price=top_bid.price,
        spread=top_spread,
        size=matched_size,
        gross_edge=gross_edge,
        average_spread=average_spread,
    )


def executable_spread(
    bids: Iterable[Any] | None,
    asks: Iterable[Any] | None,
) -> float | None:
    bid = best_bid(bids)
    ask = best_ask(asks)
    if bid is None or ask is None:
        return None
    return bid.price - ask.price


def executable_size(
    bids_or_levels: Iterable[Any] | None,
    asks_or_target: Iterable[Any] | float,
    side: str | None = None,
) -> float:
    if side is not None:
        return size_at_price(bids_or_levels, float(asks_or_target), side)
    return price_cross(asks_or_target, bids_or_levels).size  # type: ignore[arg-type]


def executable_from_l2(
    bids: Iterable[Any] | None,
    asks: Iterable[Any] | None,
    *,
    min_spread: float = 0.0,
) -> ExecutableSpread:
    return price_cross(asks, bids, min_spread=min_spread)


def quote_from_order_books(
    buy_book: Any,
    sell_book: Any,
    *,
    min_spread: float = 0.0,
) -> ExecutableSpread:
    buy_asks = _value(buy_book, "asks", "ask")
    sell_bids = _value(sell_book, "bids", "bid")
    return price_cross(buy_asks, sell_bids, min_spread=min_spread)

