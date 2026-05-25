from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import threading
import time
import tty
from pathlib import Path
from typing import Iterable

import pmxt

from .discovery import DISCOVERY_VENUES, discover_outcome_groups
from .models import LivePriceRow, Quote, VenueOutcomeRef, VenuePrice
from .render import render_price_table
from .streams import LiveOrderBookWatcher


DEFAULT_DEPTH = 20
DEFAULT_LIMIT = 10
DEFAULT_CLUSTER_LIMIT = 50
DEFAULT_REFRESH_SECONDS = 1.0


class QuoteStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._quotes: dict[tuple[object, str, str], Quote] = {}
        self.errors: dict[tuple[object, str, str], str] = {}

    def seed(self, quote: Quote) -> None:
        with self._lock:
            self._quotes.setdefault(quote.ref.key, quote)

    def set(self, quote: Quote) -> None:
        with self._lock:
            self._quotes[quote.ref.key] = quote
            self.errors.pop(quote.ref.key, None)

    def set_error(self, ref: VenueOutcomeRef, error: Exception) -> None:
        with self._lock:
            self.errors[ref.key] = str(error)

    def get(self, ref: VenueOutcomeRef) -> Quote | None:
        with self._lock:
            return self._quotes.get(ref.key)


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_venues(value: str) -> tuple[str, ...]:
    venues = tuple(part.strip().lower() for part in value.split(",") if part.strip())
    supported = set(DISCOVERY_VENUES)
    unsupported = [venue for venue in venues if venue not in supported]
    if unsupported:
        raise argparse.ArgumentTypeError(
            f"unsupported venue(s): {', '.join(unsupported)}; use {', '.join(DISCOVERY_VENUES)}"
        )
    return venues or DISCOVERY_VENUES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pmxt-arb-scan",
        description="Live PMXT matched-market price comparison.",
    )
    parser.add_argument("--venues", type=parse_venues, default=DISCOVERY_VENUES)
    parser.add_argument("--query", help="Text search filter for matched clusters.")
    parser.add_argument("--category", help="PMXT category filter.")
    parser.add_argument("--min-confidence", type=float)
    parser.add_argument("--min-spread", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--clusters", type=int, default=DEFAULT_CLUSTER_LIMIT)
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--refresh", type=float, default=DEFAULT_REFRESH_SECONDS)
    return parser


class TerminalInput:
    def __init__(self) -> None:
        self.enabled = False
        self.fd = sys.stdin.fileno()
        self.old_settings: list[object] | None = None

    def __enter__(self) -> "TerminalInput":
        if sys.stdin.isatty():
            self.old_settings = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            self.enabled = True
        return self

    def __exit__(self, *_: object) -> None:
        self.disable()

    def disable(self) -> None:
        if self.enabled and self.old_settings is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)
        self.enabled = False

    def enable(self) -> None:
        if sys.stdin.isatty() and not self.enabled:
            self.old_settings = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            self.enabled = True

    def read_key(self) -> str | None:
        if not self.enabled:
            return None
        if not select.select([sys.stdin], [], [], 0)[0]:
            return None

        char = sys.stdin.read(1)
        if char != "\x1b":
            return char

        sequence = char
        deadline = time.monotonic() + 0.03
        while time.monotonic() < deadline and select.select([sys.stdin], [], [], 0)[0]:
            sequence += sys.stdin.read(1)
            if len(sequence) >= 3:
                break

        if sequence == "\x1b[A":
            return "up"
        if sequence == "\x1b[B":
            return "down"
        if sequence == "\x1b[5":
            return "page_up"
        if sequence == "\x1b[6":
            return "page_down"
        return "escape"

    def prompt(self, message: str) -> str:
        self.disable()
        try:
            return input(message)
        finally:
            self.enable()


def quote_from_book(ref: VenueOutcomeRef, book: object) -> Quote:
    bids = list(getattr(book, "bids", []) or [])
    asks = list(getattr(book, "asks", []) or [])
    best_bid = bids[0] if bids else None
    best_ask = asks[0] if asks else None
    return Quote(
        ref=ref,
        bid=_level_value(best_bid, "price"),
        ask=_level_value(best_ask, "price"),
        bid_size=_level_value(best_bid, "size"),
        ask_size=_level_value(best_ask, "size"),
        observed_at=time.time(),
    )


def _level_value(level: object | None, name: str) -> float | None:
    if level is None:
        return None
    if isinstance(level, dict):
        value = level.get(name)
    elif isinstance(level, (list, tuple)):
        value = level[0] if name == "price" and len(level) > 0 else level[1] if len(level) > 1 else None
    else:
        value = getattr(level, name, None)
    return float(value) if value is not None else None


def start_watcher(
    ref: VenueOutcomeRef,
    *,
    store: QuoteStore,
    stop: threading.Event,
    pmxt_api_key: str,
    depth: int,
) -> threading.Thread:
    def run() -> None:
        watcher = LiveOrderBookWatcher(
            ref.venue.value,
            ref.outcome_id,
            pmxt_api_key=pmxt_api_key,
            limit=depth,
        )
        try:
            book = watcher.exchange.fetch_order_book(ref.outcome_id, limit=depth)
            store.set(quote_from_book(ref, book))
        except Exception as exc:
            store.set_error(ref, exc)

        while not stop.is_set():
            try:
                book = watcher.watch_once()
                store.set(quote_from_book(ref, book))
            except Exception as exc:
                store.set_error(ref, exc)
                stop.wait(2)

    thread = threading.Thread(
        target=run,
        name=f"{ref.venue.value}:{ref.outcome_id[:12]}",
        daemon=True,
    )
    thread.start()
    return thread


def start_streams(
    groups: list[object],
    *,
    pmxt_api_key: str,
    depth: int,
) -> tuple[QuoteStore, threading.Event, list[threading.Thread]]:
    store = QuoteStore()
    stop = threading.Event()
    refs = unique_refs(groups)
    threads = [
        start_watcher(ref, store=store, stop=stop, pmxt_api_key=pmxt_api_key, depth=depth)
        for ref in refs
    ]
    return store, stop, threads


def discover_groups(args: argparse.Namespace, router: object, query: str | None) -> list[object]:
    groups = discover_outcome_groups(
        router,
        limit=args.clusters,
        venues=args.venues,
        query=query,
        category=args.category,
        min_confidence=args.min_confidence,
    )
    return groups


def unique_refs(groups: Iterable[object]) -> list[VenueOutcomeRef]:
    refs: dict[tuple[object, str, str], VenueOutcomeRef] = {}
    for group in groups:
        for ref in getattr(group, "refs", ()):
            refs[ref.key] = ref
    return list(refs.values())


def display_price(quote: Quote) -> float | None:
    if quote.bid is not None and quote.ask is not None:
        return (quote.bid + quote.ask) / 2
    return quote.ask if quote.ask is not None else quote.bid


def live_price_rows(
    groups: Iterable[object],
    store: QuoteStore,
    *,
    min_spread: float,
) -> list[LivePriceRow]:
    rows: list[LivePriceRow] = []
    for group in groups:
        prices: list[VenuePrice] = []
        for ref in getattr(group, "refs", ()):
            quote = store.get(ref)
            if quote is None or quote.observed_at is None:
                continue
            price = display_price(quote)
            if price is None:
                continue
            prices.append(VenuePrice(venue=ref.venue, price=price, url=ref.market_url))
        row = LivePriceRow(
            title=getattr(group, "title"),
            outcome_label=getattr(group, "outcome_label"),
            prices=tuple(prices),
        )
        if row.spread is None or row.spread < min_spread:
            continue
        rows.append(row)
    return rows


def ranked_rows(rows: Iterable[LivePriceRow]) -> list[LivePriceRow]:
    return sorted(
        rows,
        key=lambda row: row.spread if row.spread is not None else float("-inf"),
        reverse=True,
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    pmxt_api_key = os.environ.get("PMXT_API_KEY")
    if not pmxt_api_key:
        print("Set PMXT_API_KEY in .env or the environment.", file=sys.stderr)
        return 2

    router = pmxt.Router(pmxt_api_key=pmxt_api_key)
    active_query = args.query
    print("Discovering matched PMXT markets...")
    groups = discover_groups(args, router, active_query)
    watch_groups = groups
    if not watch_groups:
        print("No matched outcome groups found for the selected filters.")
        return 0

    store, stop, threads = start_streams(
        watch_groups,
        pmxt_api_key=pmxt_api_key,
        depth=args.depth,
    )
    offset = 0

    with TerminalInput() as terminal:
        print(f"Watching {len(threads)} live order books. Press Ctrl-C to stop.")
        try:
            while True:
                key = terminal.read_key()
                if key in {"q", "Q"}:
                    stop.set()
                    print("\nStopped.")
                    return 0
                if key == "up":
                    offset = max(0, offset - 1)
                elif key == "down":
                    offset += 1
                elif key == "page_up":
                    offset = max(0, offset - args.limit)
                elif key == "page_down":
                    offset += args.limit
                elif key in {"r", "R"}:
                    stop.set()
                    print("\nRefreshing PMXT discovery...")
                    groups = discover_groups(args, router, active_query)
                    watch_groups = groups
                    store, stop, threads = start_streams(
                        watch_groups,
                        pmxt_api_key=pmxt_api_key,
                        depth=args.depth,
                    )
                    offset = 0
                elif key == "/":
                    next_query = terminal.prompt("\nSearch query (blank clears): ").strip()
                    active_query = next_query or None
                    stop.set()
                    print("Discovering matched PMXT markets...")
                    groups = discover_groups(args, router, active_query)
                    watch_groups = groups
                    store, stop, threads = start_streams(
                        watch_groups,
                        pmxt_api_key=pmxt_api_key,
                        depth=args.depth,
                    )
                    offset = 0

                rows = ranked_rows(
                    live_price_rows(
                        watch_groups,
                        store,
                        min_spread=args.min_spread,
                    )
                )
                if rows:
                    max_offset = max(0, len(rows) - args.limit)
                    offset = min(offset, max_offset)
                else:
                    offset = 0
                visible_rows = rows[offset : offset + args.limit]

                render_price_table(
                    visible_rows,
                    venues=args.venues,
                    limit=None,
                    clear=True,
                )
                showing_to = offset + len(visible_rows)
                print(
                    f"\nquery={active_query or '-'} "
                    f"venues={','.join(args.venues)} "
                    f"showing={offset + 1 if visible_rows else 0}-{showing_to}/{len(rows)} "
                    f"matched_groups={len(watch_groups)} "
                    f"streams={len(threads)}"
                )
                print("keys: ↑/↓ scroll  PgUp/PgDn jump  / search  r refresh  q quit")
                time.sleep(args.refresh)
        except KeyboardInterrupt:
            stop.set()
            print("\nStopped.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
