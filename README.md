# PMXT Live Arbitrage Scan

Dead-simple live price comparison showcase for PMXT. It finds matched markets across Polymarket, Kalshi, Limitless, and Opinion, then watches live order books and keeps a ranked table of cross-venue price spreads on screen.

## Quickstart

Requires Python 3.10+.

1. Clone the repo:

```bash
git clone https://github.com/realfishsam/prediction-markets-arbitrage-scan.git
cd prediction-markets-arbitrage-scan
```

2. Create a PMXT API key:

Go to [pmxt.dev/dashboard](https://www.pmxt.dev/dashboard), open **API Keys**, create a key, and copy it.

3. Add the key:

```bash
cp .env.example .env
```

Then edit `.env` so it looks like this:

```bash
PMXT_API_KEY=pmxt_your_api_key_here
```

4. Install:

```bash
python3 -m pip install -e .
```

5. Run:

```bash
pmxt-arb-scan
```

You should see a live, colored table of matched markets and price spreads.

## Filters

```bash
pmxt-arb-scan --venues polymarket,kalshi
pmxt-arb-scan --category Sports
pmxt-arb-scan --query "World Cup"
pmxt-arb-scan --min-spread 0.01 --limit 20
```

While running:

- `Up` / `Down`: scroll
- `PageUp` / `PageDown`: jump
- `/`: search
- `r`: refresh
- `q`: quit

## What It Does

- Fetches PMXT matched market clusters with live order-book quotes.
- Starts `watch_order_book` streams for each matched outcome.
- Shows the live positive/Yes-side price by venue.
- Renders a simple live spread: highest venue price minus lowest venue price.
- Colors venue prices and larger spreads for easier scanning.
- Makes venue price cells clickable in terminals that support OSC 8 hyperlinks.

This is a PMXT capabilities demo, not an execution bot. Fees, latency, venue limits, and order placement are intentionally out of scope.
