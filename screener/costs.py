"""
Indian equity transaction costs (discount broker, delivery/CNC).

Stated explicitly so they can be challenged:
  brokerage  min(0.03% x turnover, Rs 20) per order  -- CONSERVATIVE. Several
             brokers charge Rs 0 on equity delivery; if so, results here are
             understated by ~Rs 40 per round trip.
  STT        0.1% on BOTH buy and sell turnover
  exchange   0.00297% both sides
  SEBI       0.0001%, IPFT 0.0001%
  stamp      0.015% on BUY only
  GST        18% on (brokerage + exchange + SEBI + IPFT)
  DP charge  Rs 15.34 per scrip per SELL day - flat, so it punishes small
             positions disproportionately

Slippage is applied by the backtest, not here.
"""
GST = 0.18
EXCH, SEBI, IPFT = 0.0000297, 0.000001, 0.000001
DP_CHARGE = 15.34


def _brokerage(turnover, free=False):
    return 0.0 if free else min(0.0003 * turnover, 20.0)


def delivery_cost(buy_value, sell_value, free_brokerage=False):
    """Total round-trip charges in rupees."""
    turnover = buy_value + sell_value
    brok = _brokerage(buy_value, free_brokerage) + _brokerage(sell_value, free_brokerage)
    stt = 0.001 * buy_value + 0.001 * sell_value
    exch = EXCH * turnover
    sebi = SEBI * turnover
    ipft = IPFT * turnover
    stamp = 0.00015 * buy_value
    gst = GST * (brok + exch + sebi + ipft)
    return brok + stt + exch + sebi + ipft + stamp + gst + DP_CHARGE


def round_trip_pct(position_value, free_brokerage=False):
    """Round-trip cost as a fraction of position value - the bar a trade
    must clear before it makes anything."""
    c = delivery_cost(position_value, position_value, free_brokerage)
    return c / position_value


if __name__ == "__main__":
    for v in (10_000, 25_000, 50_000, 1_00_000, 2_00_000):
        print(f"Rs {v:>8,}  round trip Rs {delivery_cost(v, v):7.2f}  "
              f"= {100*round_trip_pct(v):.3f}% of position")
