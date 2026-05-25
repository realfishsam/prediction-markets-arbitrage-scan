from __future__ import annotations

import json
from dataclasses import dataclass, fields, is_dataclass
from inspect import Parameter, signature
from math import isfinite
from typing import Any, Iterable, Sequence


__all__ = [
    "DEFAULT_LIMIT",
    "DISCOVERY_VENUES",
    "clusters_to_candidate_pairs",
    "clusters_to_outcome_groups",
    "discover_candidate_pairs",
    "discover_outcome_groups",
    "fetch_identity_market_clusters",
]

DISCOVERY_VENUES: tuple[str, ...] = (
    "polymarket",
    "kalshi",
    "limitless",
    "opinion",
)
DEFAULT_LIMIT = 50


@dataclass(frozen=True)
class _FallbackVenueOutcomeRef:
    venue: str
    market_id: str
    outcome_id: str | None
    outcome_label: str
    market_title: str | None = None
    market_url: str | None = None


@dataclass(frozen=True)
class _FallbackCandidateLeg:
    side: str
    ref: Any
    price: float
    size: float | None = None
    quote: Any | None = None


@dataclass(frozen=True)
class _FallbackOpportunity:
    buy: Any
    sell: Any
    cluster_id: str | None = None
    title: str | None = None

    @property
    def outcome_label(self) -> str:
        return self.buy.ref.outcome_label

    @property
    def spread(self) -> float:
        return self.sell.price - self.buy.price


try:
    from .models import CandidateLeg, MatchedOutcomeGroup, Opportunity, VenueOutcomeRef
except Exception:  # pragma: no cover - lets this module work before models.py lands.
    CandidateLeg = _FallbackCandidateLeg
    MatchedOutcomeGroup = None
    Opportunity = _FallbackOpportunity
    VenueOutcomeRef = _FallbackVenueOutcomeRef


def fetch_identity_market_clusters(
    router: Any,
    *,
    limit: int = DEFAULT_LIMIT,
    venues: Sequence[str] = DISCOVERY_VENUES,
    query: str | None = None,
    category: str | None = None,
    min_confidence: float | None = None,
) -> list[Any]:
    """Fetch identity-matched PMXT Router clusters for supported venues."""
    venue_values = [_normalize_venue(venue) for venue in venues]
    params: dict[str, Any] = {
        "relations": "identity",
        "min_venues": 2,
        "with_orderbook": True,
        "include_raw_matches": False,
        "sort": "volume",
        "limit": limit,
        "venues": ",".join(venue_values),
    }
    if query:
        params["query"] = query
    if category:
        params["category"] = category
    if min_confidence is not None:
        params["min_confidence"] = min_confidence

    if hasattr(router, "fetch_matched_market_clusters"):
        return router.fetch_matched_market_clusters(**params)
    return _fetch_matched_market_clusters_via_hosted_path(router, params)


def clusters_to_candidate_pairs(
    clusters: Iterable[Any],
    *,
    venues: Sequence[str] = DISCOVERY_VENUES,
) -> list[Any]:
    """Convert matched clusters into directional cross-venue outcome pairs."""
    venue_set = {_normalize_venue(venue) for venue in venues}
    candidates: list[Any] = []

    for cluster in clusters:
        entries = [
            entry
            for market in _value(cluster, "markets", default=[]) or []
            for entry in _market_outcome_entries(market)
            if entry["venue"] in venue_set
        ]

        for buy_entry in entries:
            for sell_entry in entries:
                if buy_entry is sell_entry:
                    continue
                if buy_entry["venue"] == sell_entry["venue"]:
                    continue
                if buy_entry["label_key"] != sell_entry["label_key"]:
                    continue
                if _spread(buy_entry["best_ask"], sell_entry["best_bid"]) <= 0:
                    continue

                candidates.append(_build_opportunity(cluster, buy_entry, sell_entry))

    return candidates


def discover_candidate_pairs(
    router: Any,
    *,
    limit: int = DEFAULT_LIMIT,
    venues: Sequence[str] = DISCOVERY_VENUES,
    query: str | None = None,
    category: str | None = None,
    min_confidence: float | None = None,
) -> list[Any]:
    """Fetch PMXT clusters and return candidate buy/sell outcome pairs."""
    clusters = fetch_identity_market_clusters(
        router,
        limit=limit,
        venues=venues,
        query=query,
        category=category,
        min_confidence=min_confidence,
    )
    return clusters_to_candidate_pairs(clusters, venues=venues)


def clusters_to_outcome_groups(
    clusters: Iterable[Any],
    *,
    venues: Sequence[str] = DISCOVERY_VENUES,
) -> list[Any]:
    """Convert matched clusters into positive/Yes-side outcome groups."""
    venue_set = {_normalize_venue(venue) for venue in venues}
    groups: list[Any] = []

    for cluster in clusters:
        refs: list[Any] = []
        labels: list[str] = []
        for market in _value(cluster, "markets", default=[]) or []:
            entry = _positive_market_outcome_entry(market)
            if not entry or entry["venue"] not in venue_set:
                continue
            refs.append(_build_venue_outcome_ref(entry))
            if entry["outcome_label"].lower() not in {"yes", "y"}:
                labels.append(entry["outcome_label"])

        if len(refs) < 2:
            continue

        title = _value(cluster, "canonical_title", "canonicalTitle", "title")
        label = labels[0] if labels else "Yes"
        if MatchedOutcomeGroup is None:
            groups.append(
                {
                    "cluster_id": _optional_str(_value(cluster, "cluster_id", "clusterId")),
                    "title": str(title or label),
                    "outcome_label": label,
                    "refs": tuple(refs),
                }
            )
        else:
            groups.append(
                MatchedOutcomeGroup(
                    cluster_id=_optional_str(_value(cluster, "cluster_id", "clusterId")),
                    title=str(title or label),
                    outcome_label=label,
                    refs=tuple(refs),
                )
            )

    return groups


def discover_outcome_groups(
    router: Any,
    *,
    limit: int = DEFAULT_LIMIT,
    venues: Sequence[str] = DISCOVERY_VENUES,
    query: str | None = None,
    category: str | None = None,
    min_confidence: float | None = None,
) -> list[Any]:
    """Fetch PMXT clusters and return live-price comparison groups."""
    clusters = fetch_identity_market_clusters(
        router,
        limit=limit,
        venues=venues,
        query=query,
        category=category,
        min_confidence=min_confidence,
    )
    return clusters_to_outcome_groups(clusters, venues=venues)


def _market_outcome_entries(market: Any) -> list[dict[str, Any]]:
    venue = _value(market, "source_exchange", "sourceExchange", "venue", "exchange")
    market_id = _value(market, "market_id", "marketId", "id")
    market_title = _value(market, "title", "question")
    market_url = _value(market, "url")
    venue_text = _normalize_venue(venue)
    market_id_text = str(market_id).strip() if market_id is not None else ""
    if not venue_text or not market_id_text:
        return []

    entries: list[dict[str, Any]] = []
    for outcome in _value(market, "outcomes", default=[]) or []:
        label = _value(outcome, "label", "name", "outcome")
        label_key = _normalize_label(label)
        if not label_key:
            continue
        outcome_id = _optional_str(_value(outcome, "outcome_id", "outcomeId", "id"))
        if not outcome_id:
            continue

        entries.append(
            {
                "venue": venue_text,
                "market_id": market_id_text,
                "market_title": str(market_title) if market_title is not None else None,
                "market_url": _optional_str(market_url),
                "outcome_id": outcome_id,
                "outcome_label": label_key,
                "label_key": label_key,
                "best_bid": _float_or_none(_value(outcome, "best_bid", "bestBid")),
                "best_ask": _float_or_none(_value(outcome, "best_ask", "bestAsk")),
            }
        )

    return entries


def _positive_market_outcome_entry(market: Any) -> dict[str, Any] | None:
    entries = _market_outcome_entries(market)
    if not entries:
        return None
    for entry in entries:
        if entry["label_key"] in {"yes", "y"}:
            return entry
    for entry in entries:
        if entry["label_key"] in {"no", "n"} or entry["label_key"].startswith("not "):
            continue
        return entry
    return entries[0]


def _build_opportunity(
    cluster: Any,
    buy_entry: dict[str, Any],
    sell_entry: dict[str, Any],
) -> Any:
    buy_leg = _build_candidate_leg(
        buy_entry,
        side="buy",
        price=buy_entry["best_ask"],
    )
    sell_leg = _build_candidate_leg(
        sell_entry,
        side="sell",
        price=sell_entry["best_bid"],
    )
    spread = _spread(buy_entry["best_ask"], sell_entry["best_bid"])

    return _construct(
        Opportunity,
        _FallbackOpportunity,
        {
            "cluster_id": _optional_str(_value(cluster, "cluster_id", "clusterId")),
            "title": _value(cluster, "canonical_title", "canonicalTitle", "title"),
            "canonical_title": _value(cluster, "canonical_title", "canonicalTitle", "title"),
            "outcome_label": buy_entry["outcome_label"],
            "label": buy_entry["outcome_label"],
            "buy_leg": buy_leg,
            "buy": buy_leg,
            "sell_leg": sell_leg,
            "sell": sell_leg,
            "spread": spread,
        },
    )


def _build_candidate_leg(
    entry: dict[str, Any],
    *,
    side: str,
    price: float | None,
) -> Any:
    ref = _build_venue_outcome_ref(entry)
    return _construct(
        CandidateLeg,
        _FallbackCandidateLeg,
        {
            "outcome_ref": ref,
            "venue_outcome": ref,
            "ref": ref,
            "outcome": ref,
            "side": side,
            "price": price,
            "size": None,
            "quote": None,
            "best_bid": entry["best_bid"],
            "best_ask": entry["best_ask"],
        },
    )


def _build_venue_outcome_ref(entry: dict[str, Any]) -> Any:
    return _construct(
        VenueOutcomeRef,
        _FallbackVenueOutcomeRef,
        {
            "venue": entry["venue"],
            "market_id": entry["market_id"],
            "outcome_id": entry["outcome_id"],
            "outcome_label": entry["outcome_label"],
            "label": entry["outcome_label"],
            "market_title": entry["market_title"],
            "title": entry["market_title"],
            "market_url": entry["market_url"],
            "url": entry["market_url"],
        },
    )


def _construct(model_cls: Any, fallback_cls: type[Any], values: dict[str, Any]) -> Any:
    try:
        return model_cls(**_accepted_kwargs(model_cls, values))
    except TypeError:
        return fallback_cls(**_accepted_kwargs(fallback_cls, values))


def _accepted_kwargs(model_cls: Any, values: dict[str, Any]) -> dict[str, Any]:
    try:
        if is_dataclass(model_cls):
            names = {field.name for field in fields(model_cls) if field.init}
            return {key: value for key, value in values.items() if key in names}

        params = signature(model_cls).parameters.values()
        if any(param.kind == Parameter.VAR_KEYWORD for param in params):
            return values
        names = {
            param.name
            for param in params
            if param.kind
            in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)
        }
        return {key: value for key, value in values.items() if key in names}
    except (TypeError, ValueError):
        return values


def _value(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _fetch_matched_market_clusters_via_hosted_path(
    router: Any,
    params: dict[str, Any],
) -> list[Any]:
    """Compatibility path for SDK builds before Router exposed this helper."""
    hosted_params = {
        "relations": params.get("relations"),
        "minVenues": params.get("min_venues"),
        "withOrderbook": params.get("with_orderbook"),
        "includeRawMatches": params.get("include_raw_matches"),
        "sort": params.get("sort"),
        "limit": params.get("limit"),
        "venues": params.get("venues"),
        "query": params.get("query"),
        "category": params.get("category"),
        "minConfidence": params.get("min_confidence"),
    }
    query = router._build_sidecar_query_string(hosted_params)
    url = f"{router._resolve_sidecar_host()}/v0/matched-market-clusters"
    if query:
        url = f"{url}?{query}"

    headers = {"Accept": "application/json"}
    headers.update(router._get_auth_headers())
    response = router._fetch_with_retry(
        lambda: router._api_client.call_api(
            method="GET",
            url=url,
            header_params=headers,
        )
    )
    response.read()
    raw = json.loads(response.data)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        return raw["data"]
    return []


def _normalize_label(label: Any) -> str:
    if label is None:
        return ""

    value = str(label).strip().lower()
    if value in {"yes", "y"}:
        return "yes"
    if value in {"no", "n"}:
        return "no"
    return value


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number) or not 0 <= number <= 1:
        return None
    return number


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_venue(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value)).strip().lower()


def _spread(ask: float | None, bid: float | None) -> float:
    if ask is None or bid is None:
        return 0
    return bid - ask
