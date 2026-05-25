from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite


__all__ = [
    "Venue",
    "LegSide",
    "VenueOutcomeRef",
    "Quote",
    "CandidateLeg",
    "Opportunity",
    "MatchedOutcomeGroup",
    "VenuePrice",
    "LivePriceRow",
]


class Venue(str, Enum):
    """Supported PMXT source venues for the first scanner pass."""

    POLYMARKET = "polymarket"
    KALSHI = "kalshi"
    LIMITLESS = "limitless"
    OPINION = "opinion"

    @classmethod
    def parse(cls, value: Venue | str) -> Venue:
        if isinstance(value, cls):
            return value

        normalized = str(value).strip().lower()
        for venue in cls:
            if venue.value == normalized:
                return venue
        raise ValueError(f"Unsupported venue: {value!r}")


class LegSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @classmethod
    def parse(cls, value: LegSide | str) -> LegSide:
        if isinstance(value, cls):
            return value

        normalized = str(value).strip().lower()
        for side in cls:
            if side.value == normalized:
                return side
        raise ValueError(f"Unsupported leg side: {value!r}")


@dataclass(frozen=True, slots=True)
class VenueOutcomeRef:
    """Stable reference to one outcome on one venue market."""

    venue: Venue
    market_id: str
    outcome_id: str
    outcome_label: str
    market_title: str | None = None
    market_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", Venue.parse(self.venue))
        object.__setattr__(self, "market_id", _required_str(self.market_id, "market_id"))
        object.__setattr__(self, "outcome_id", _required_str(self.outcome_id, "outcome_id"))
        object.__setattr__(
            self,
            "outcome_label",
            _required_str(self.outcome_label, "outcome_label"),
        )
        if self.market_url is not None:
            object.__setattr__(self, "market_url", self.market_url.strip() or None)

    @property
    def key(self) -> tuple[Venue, str, str]:
        return (self.venue, self.market_id, self.outcome_id)


@dataclass(frozen=True, slots=True)
class Quote:
    """Top-of-book quote for a venue outcome."""

    ref: VenueOutcomeRef
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    observed_at: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bid", _price_or_none(self.bid, "bid"))
        object.__setattr__(self, "ask", _price_or_none(self.ask, "ask"))
        object.__setattr__(self, "bid_size", _size_or_none(self.bid_size, "bid_size"))
        object.__setattr__(self, "ask_size", _size_or_none(self.ask_size, "ask_size"))

    @property
    def has_bid(self) -> bool:
        return self.bid is not None

    @property
    def has_ask(self) -> bool:
        return self.ask is not None

    def buy_leg(self) -> CandidateLeg | None:
        if self.ask is None:
            return None
        return CandidateLeg(
            side=LegSide.BUY,
            ref=self.ref,
            price=self.ask,
            size=self.ask_size,
            quote=self,
        )

    def sell_leg(self) -> CandidateLeg | None:
        if self.bid is None:
            return None
        return CandidateLeg(
            side=LegSide.SELL,
            ref=self.ref,
            price=self.bid,
            size=self.bid_size,
            quote=self,
        )


@dataclass(frozen=True, slots=True)
class CandidateLeg:
    """Executable buy or sell leg derived from a live quote."""

    side: LegSide
    ref: VenueOutcomeRef
    price: float
    size: float | None = None
    quote: Quote | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", LegSide.parse(self.side))
        object.__setattr__(self, "price", _required_price(self.price, "price"))
        object.__setattr__(self, "size", _size_or_none(self.size, "size"))

    @property
    def venue(self) -> Venue:
        return self.ref.venue

    @property
    def outcome_label(self) -> str:
        return self.ref.outcome_label


@dataclass(frozen=True, slots=True)
class Opportunity:
    """Positive buy-low/sell-high spread for the same outcome across venues."""

    buy: CandidateLeg
    sell: CandidateLeg
    cluster_id: str | None = None
    title: str | None = None

    def __post_init__(self) -> None:
        if self.buy.side is not LegSide.BUY:
            raise ValueError("Opportunity.buy must be a buy leg")
        if self.sell.side is not LegSide.SELL:
            raise ValueError("Opportunity.sell must be a sell leg")
        if _normalized_label(self.buy.outcome_label) != _normalized_label(self.sell.outcome_label):
            raise ValueError("Opportunity legs must refer to the same outcome label")
        if self.buy.venue is self.sell.venue:
            raise ValueError("Opportunity legs must be on different venues")
        if self.spread <= 0:
            raise ValueError("Opportunity spread must be positive")

    @classmethod
    def from_quotes(
        cls,
        buy_quote: Quote,
        sell_quote: Quote,
        *,
        cluster_id: str | None = None,
        title: str | None = None,
    ) -> Opportunity | None:
        buy = buy_quote.buy_leg()
        sell = sell_quote.sell_leg()
        if buy is None or sell is None:
            return None
        if buy.venue is sell.venue:
            return None
        if _normalized_label(buy.outcome_label) != _normalized_label(sell.outcome_label):
            return None
        if sell.price <= buy.price:
            return None
        return cls(buy=buy, sell=sell, cluster_id=cluster_id, title=title)

    @property
    def outcome_label(self) -> str:
        return self.buy.outcome_label

    @property
    def spread(self) -> float:
        return self.sell.price - self.buy.price

    @property
    def spread_bps(self) -> float:
        return self.spread * 10_000

    @property
    def max_size(self) -> float | None:
        if self.buy.size is None or self.sell.size is None:
            return None
        return min(self.buy.size, self.sell.size)

    @property
    def is_cross_venue(self) -> bool:
        return self.buy.venue is not self.sell.venue

    @property
    def is_positive(self) -> bool:
        return self.spread > 0


@dataclass(frozen=True, slots=True)
class MatchedOutcomeGroup:
    """Same matched market outcome across multiple venues."""

    cluster_id: str | None
    title: str
    outcome_label: str
    refs: tuple[VenueOutcomeRef, ...]


@dataclass(frozen=True, slots=True)
class VenuePrice:
    """Display price for one venue/outcome."""

    venue: Venue
    price: float
    url: str | None = None


@dataclass(frozen=True, slots=True)
class LivePriceRow:
    """One live comparison row for the terminal table."""

    title: str
    outcome_label: str
    prices: tuple[VenuePrice, ...]

    @property
    def spread(self) -> float | None:
        if len(self.prices) < 2:
            return None
        values = [price.price for price in self.prices]
        return max(values) - min(values)


def _required_str(value: object, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _price_or_none(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    return _required_price(value, field_name)


def _required_price(value: float | None, field_name: str) -> float:
    if value is None:
        raise ValueError(f"{field_name} is required")
    number = _finite_float(value, field_name)
    if not 0 <= number <= 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return number


def _size_or_none(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    number = _finite_float(value, field_name)
    if number < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return number


def _finite_float(value: float, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if not isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _normalized_label(value: str) -> str:
    return value.strip().lower()
