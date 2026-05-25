from pmxt_arb_scan.pricing import price_cross


def test_price_cross_matches_profitable_depth() -> None:
    result = price_cross(
        buy_asks=[{"price": 0.40, "size": 10}, {"price": 0.42, "size": 10}],
        sell_bids=[{"price": 0.45, "size": 5}, {"price": 0.43, "size": 10}],
    )

    assert round(result.spread or 0, 6) == 0.05
    assert result.size == 15
    assert round(result.gross_edge, 6) == 0.45
