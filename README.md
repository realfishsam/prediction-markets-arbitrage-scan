# PMXT Live Arbitrage Scan

Dead-simple live price comparison showcase for PMXT. It finds matched markets across Polymarket, Kalshi, Limitless, and Opinion, then watches live order books and keeps a ranked table of cross-venue price spreads on screen.

## Run

```bash
cp .env.example .env
# set PMXT_API_KEY
pip install -e .
pmxt-arb-scan
```

Optional filters:

```bash
pmxt-arb-scan --venues polymarket,kalshi
pmxt-arb-scan --category Sports
pmxt-arb-scan --query "World Cup"
pmxt-arb-scan --min-spread 0.01 --limit 20
```

While running: use `Up`/`Down` to scroll, `PageUp`/`PageDown` to jump, `/` to search, `r` to refresh discovery, and `q` to quit.

## What It Does

- Fetches PMXT matched market clusters with live order-book quotes.
- Starts `watch_order_book` streams for each matched outcome.
- Shows the live positive/Yes-side price by venue.
- Renders a simple live spread: highest venue price minus lowest venue price.
- Colors venue prices and larger spreads for easier scanning.
- Makes venue price cells clickable in terminals that support OSC 8 hyperlinks.

This is a PMXT capabilities demo, not an execution bot. Fees, latency, venue limits, and order placement are intentionally out of scope.
