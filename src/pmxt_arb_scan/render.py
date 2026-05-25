from __future__ import annotations

import shutil
import sys
from typing import Any, Iterable, TextIO


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
GRAY = "\033[90m"

VENUE_COLORS = {
    "polymarket": CYAN,
    "kalshi": GREEN,
    "limitless": MAGENTA,
    "opinion": BLUE,
}


def _value(obj: Any, *names: str) -> Any:
    for name in names:
        if obj is None:
            continue
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def _pick(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if hasattr(value, "value"):
            value = value.value
        text = str(value).strip()
        if text:
            return text
    return "-"


def _fmt_decimal(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _fmt_size(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def _clip(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _cell(text: str, width: int, *, right: bool = False) -> str:
    text = _clip(text, width)
    return text.rjust(width) if right else text.ljust(width)


def _color(text: str, code: str) -> str:
    return f"{code}{text}{RESET}"


def _leg_value(opportunity: Any, leg_name: str, *names: str) -> Any:
    leg = _pick(
        _value(opportunity, leg_name),
        _value(
            opportunity,
            f"{leg_name}_leg",
            f"{leg_name}Leg",
        ),
    )
    direct_names = tuple(f"{leg_name}_{name}" for name in names)
    camel_names = tuple(
        f"{leg_name}{name[:1].upper()}{name[1:]}" for name in names if name
    )
    ref = _value(leg, "ref", "outcome_ref", "venue_outcome", "outcome")
    return _pick(
        _value(opportunity, *direct_names, *camel_names),
        _value(leg, *names),
        _value(ref, *names),
    )


def _format_leg(venue: Any, price: float | None) -> str:
    if hasattr(venue, "value"):
        venue = venue.value
    venue_text = str(venue).strip() if venue is not None else ""
    price_text = _fmt_decimal(price)
    if venue_text and price is not None:
        return f"{venue_text} @{price_text}"
    if venue_text:
        return venue_text
    if price is not None:
        return f"@{price_text}"
    return "-"


def _hyperlink(text: str, url: Any) -> str:
    if not url:
        return text
    url_text = str(url).strip()
    if not url_text:
        return text
    return f"\033]8;;{url_text}\033\\{text}\033]8;;\033\\"


def summarize_opportunity(opportunity: Any) -> dict[str, Any]:
    buy_price = _to_float(
        _pick(
            _leg_value(opportunity, "buy", "price", "ask", "best_ask", "bestAsk"),
            _value(opportunity, "buy_price", "buy_ask", "buyPrice", "buyAsk"),
        )
    )
    sell_price = _to_float(
        _pick(
            _leg_value(opportunity, "sell", "price", "bid", "best_bid", "bestBid"),
            _value(opportunity, "sell_price", "sell_bid", "sellPrice", "sellBid"),
        )
    )
    spread = _to_float(
        _value(opportunity, "spread", "live_spread", "executable_spread", "edge")
    )
    if spread is None and buy_price is not None and sell_price is not None:
        spread = sell_price - buy_price

    average_spread = _to_float(
        _value(opportunity, "average_spread", "avg_spread", "averageSpread")
    )
    size = _to_float(
        _value(
            opportunity,
            "size",
            "executable_size",
            "matched_size",
            "max_size",
            "quantity",
        )
    )
    gross_edge = _to_float(
        _value(opportunity, "gross_edge", "grossEdge", "profit", "expected_profit")
    )
    if gross_edge is None and spread is not None and size is not None:
        gross_edge = spread * size

    market = _value(opportunity, "market", "cluster", "event")
    label = _first_text(_value(opportunity, "label", "outcome", "outcome_label"), "")
    title = _first_text(
        _value(opportunity, "title", "canonical_title", "market_title", "question"),
        _value(market, "title", "canonical_title", "question"),
    )
    if title == "-" and label != "-":
        title = label
    elif label != "-" and label.lower() not in title.lower():
        title = f"{title} [{label}]"

    return {
        "spread": spread,
        "average_spread": average_spread,
        "size": size,
        "gross_edge": gross_edge,
        "buy": _format_leg(
            _pick(
                _leg_value(opportunity, "buy", "venue", "source_exchange", "exchange"),
                _value(opportunity, "buy_venue", "buyVenue"),
            ),
            buy_price,
        ),
        "buy_url": _pick(
            _leg_value(opportunity, "buy", "market_url", "url"),
            _value(opportunity, "buy_url", "buyUrl"),
        ),
        "sell": _format_leg(
            _pick(
                _leg_value(opportunity, "sell", "venue", "source_exchange", "exchange"),
                _value(opportunity, "sell_venue", "sellVenue"),
            ),
            sell_price,
        ),
        "sell_url": _pick(
            _leg_value(opportunity, "sell", "market_url", "url"),
            _value(opportunity, "sell_url", "sellUrl"),
        ),
        "market": title,
    }


def _rank_value(row: dict[str, Any], sort_by: str) -> tuple[float, float, float]:
    primary = _to_float(row.get(sort_by))
    if primary is None and sort_by == "profit":
        primary = _to_float(row.get("gross_edge"))
    spread = _to_float(row.get("spread"))
    size = _to_float(row.get("size"))
    return (
        primary if primary is not None else float("-inf"),
        spread if spread is not None else float("-inf"),
        size if size is not None else 0.0,
    )


def rank_opportunities(
    opportunities: Iterable[Any],
    *,
    limit: int | None = None,
    sort_by: str = "spread",
) -> list[Any]:
    ranked = sorted(
        list(opportunities),
        key=lambda opportunity: _rank_value(summarize_opportunity(opportunity), sort_by),
        reverse=True,
    )
    return ranked[:limit] if limit is not None else ranked


def _columns(width: int) -> list[tuple[str, str, int, bool]]:
    if width < 96:
        fixed = [
            ("rank", "#", 3, True),
            ("spread", "spread", 8, True),
            ("size", "size", 9, True),
            ("buy", "buy", 14, False),
            ("sell", "sell", 14, False),
        ]
    else:
        fixed = [
            ("rank", "#", 3, True),
            ("spread", "spread", 8, True),
            ("size", "size", 9, True),
            ("gross_edge", "edge", 9, True),
            ("buy", "buy", 18, False),
            ("sell", "sell", 18, False),
        ]

    separators = 3 * len(fixed)
    market_width = max(12, width - sum(column[2] for column in fixed) - separators - 6)
    return [*fixed, ("market", "market", market_width, False)]


def format_live_table(
    opportunities: Iterable[Any],
    *,
    limit: int | None = 20,
    sort_by: str = "spread",
    width: int | None = None,
) -> str:
    rows = [
        summarize_opportunity(item)
        for item in rank_opportunities(opportunities, limit=limit, sort_by=sort_by)
    ]
    if not rows:
        return "No opportunities."

    table_width = width or shutil.get_terminal_size((120, 24)).columns
    columns = _columns(table_width)
    lines = [
        " | ".join(_cell(label, col_width, right=right) for _, label, col_width, right in columns),
        "-+-".join("-" * col_width for _, _, col_width, _ in columns),
    ]

    for index, row in enumerate(rows, start=1):
        row = {**row, "rank": str(index)}
        cells = []
        for key, _, col_width, right in columns:
            value = row.get(key)
            if key in {"spread", "average_spread"}:
                text = _fmt_decimal(_to_float(value))
            elif key in {"size", "gross_edge"}:
                text = _fmt_size(_to_float(value))
            else:
                text = str(value)
            cell = _cell(text, col_width, right=right)
            if key in {"buy", "sell"}:
                cell = _hyperlink(cell, row.get(f"{key}_url"))
            cells.append(cell)
        lines.append(" | ".join(cells))

    return "\n".join(lines)


def render_live_table(
    opportunities: Iterable[Any],
    *,
    limit: int | None = 20,
    sort_by: str = "spread",
    width: int | None = None,
    stream: TextIO | None = None,
    clear: bool = False,
) -> None:
    stream = stream or sys.stdout
    if clear:
        stream.write("\033[2J\033[H")
    stream.write(
        format_live_table(opportunities, limit=limit, sort_by=sort_by, width=width)
    )
    stream.write("\n")
    stream.flush()


def render_table(
    opportunities: Iterable[Any],
    *,
    limit: int | None = 20,
    sort_by: str = "spread",
    width: int | None = None,
) -> str:
    return format_live_table(opportunities, limit=limit, sort_by=sort_by, width=width)


def _price_row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _price_row_prices(row: Any) -> dict[str, tuple[float, str | None]]:
    prices: dict[str, tuple[float, str | None]] = {}
    for item in _price_row_value(row, "prices", ()) or ():
        venue = _value(item, "venue")
        if hasattr(venue, "value"):
            venue = venue.value
        price = _to_float(_value(item, "price"))
        if not venue or price is None:
            continue
        prices[str(venue).lower()] = (price, _value(item, "url"))
    return prices


def format_price_table(
    rows: Iterable[Any],
    *,
    venues: Iterable[str],
    limit: int | None = 20,
    width: int | None = None,
) -> str:
    items = list(rows)
    items.sort(
        key=lambda row: _to_float(_price_row_value(row, "spread")) or float("-inf"),
        reverse=True,
    )
    if limit is not None:
        items = items[:limit]
    if not items:
        return "No matched live prices yet."

    venue_list = [venue.lower() for venue in venues]
    table_width = width or shutil.get_terminal_size((120, 24)).columns
    venue_width = 13
    fixed_width = 3 + 8 + (venue_width + 3) * len(venue_list)
    market_width = max(18, table_width - fixed_width - 12)
    columns = [
        ("rank", "#", 3, True),
        ("spread", "spread", 8, True),
        *[(venue, venue[:venue_width], venue_width, True) for venue in venue_list],
        ("market", "market", market_width, False),
    ]

    lines = [
        _color(
            " | ".join(
                _cell(label, col_width, right=right)
                for _, label, col_width, right in columns
            ),
            BOLD,
        ),
        _color("-+-".join("-" * col_width for _, _, col_width, _ in columns), GRAY),
    ]

    for index, row in enumerate(items, start=1):
        prices = _price_row_prices(row)
        cells = []
        for key, _, col_width, right in columns:
            if key == "rank":
                text = str(index)
                cell = _color(_cell(text, col_width, right=right), GRAY)
            elif key == "spread":
                spread = _to_float(_price_row_value(row, "spread"))
                spread_color = GREEN if spread is not None and spread >= 0.01 else YELLOW
                cell = _color(_cell(_fmt_decimal(spread), col_width, right=True), spread_color)
            elif key == "market":
                title = _first_text(_price_row_value(row, "title"))
                label = _first_text(_price_row_value(row, "outcome_label"), "")
                if label != "-" and label.lower() not in title.lower():
                    title = f"{title} [{label}]"
                cell = _cell(title, col_width)
            else:
                price = prices.get(key)
                if price is None:
                    cell = _color(_cell("-", col_width, right=True), DIM)
                else:
                    value, url = price
                    venue_color = VENUE_COLORS.get(key, BOLD)
                    text = _cell(_fmt_decimal(value), col_width, right=True)
                    cell = _hyperlink(_color(text, venue_color), url)
            cells.append(cell)
        lines.append(" | ".join(cells))

    return "\n".join(lines)


def render_price_table(
    rows: Iterable[Any],
    *,
    venues: Iterable[str],
    limit: int | None = 20,
    width: int | None = None,
    stream: TextIO | None = None,
    clear: bool = False,
) -> None:
    stream = stream or sys.stdout
    if clear:
        stream.write("\033[2J\033[H")
    stream.write(format_price_table(rows, venues=venues, limit=limit, width=width))
    stream.write("\n")
    stream.flush()
