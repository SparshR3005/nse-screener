# NSE Screener

Thirteen screeners over the liquid NIFTY 500, run seven times a session by
GitHub Actions. Every technical screen carries the edge it actually
demonstrated over 2015–2026, measured against what the average liquid stock
did **starting the same day**.

Three screens beat that bar. Five don't. Two are measurably worse than random.

| Screen | Edge over 6m | t | Verdict |
|---|--:|--:|---|
| Volume thrust / accumulation | **+1.89%** | +5.3 | EDGE |
| 52-week breakout on volume | **+1.29%** | +4.2 | EDGE |
| Momentum leader | **+0.95%** | +3.1 | EDGE |
| Pullback to 50-DMA in uptrend | −0.18% | −0.9 | no edge |
| Oversold bounce (RSI<32) | −0.27% | −0.4 | no edge |
| MACD bullish crossover | −0.36% | −1.7 | no edge |
| Volatility squeeze release | −0.54% | −1.7 | no edge |
| Golden crossover (50/200) | −0.73% | −1.4 | no edge |
| Recovery from lows | −1.52% | −2.8 | **negative** |
| Trend reversal (reclaim 200-DMA) | −2.19% | −4.9 | **negative** |

Alerts fire on EDGE screens only by default. The rest still run and appear on
the dashboard, labelled.

## The number that matters most

Any liquid NIFTY 500 stock, bought on any random day since 2015, had a
**73.9% chance of touching +10% within six months**, median **23 sessions**.
The best screen here moves that to 77.7% and 21 sessions.

Worse, that baseline swings from **59.6% (2015) to 89.9% (2023)** on start year
alone. The screen contributes two to four points; the year contributes thirty.
Treat any fixed "target and timeframe" accordingly.

## Setup

1. Push this repo to GitHub (private is fine — Actions minutes are consumed on
   private repos; public repos are free but disable schedules after 60 days of
   inactivity).
2. **Settings → Actions → General → Workflow permissions** → *Read and write*.
   The workflow commits results back.
3. Optional, for phone alerts: **Settings → Secrets and variables → Actions**
   - `TELEGRAM_TOKEN` — from [@BotFather](https://t.me/botfather)
   - `TELEGRAM_CHAT_ID` — your chat id
4. Optional, for a comment thread: open an issue, then set repository variable
   `ALERT_ISSUE_NUMBER` to its number.
5. Optional dashboard: **Settings → Pages** → deploy from `main` / `/docs`.

Nothing above is required to run — with zero configuration, results land in the
Actions step summary and in `data/latest.json`.

## Schedule

`intraday.yml` runs at 04:15–09:15 UTC hourly plus 10:05 UTC, Mon–Fri:

| UTC | IST | |
|---|---|---|
| 04:15 | 09:45 | provisional |
| 05:15 | 10:45 | provisional |
| 06:15 | 11:45 | provisional |
| 07:15 | 12:45 | provisional |
| 08:15 | 13:45 | provisional |
| 09:15 | 14:45 | provisional |
| 10:05 | 15:35 | **confirmed** |

`maintenance.yml` refreshes the universe and fundamentals on Saturdays, and can
re-run the full calibration on demand.

### Provisional vs confirmed

The screens are calibrated on **completed daily bars**. Mid-session, today's bar
is partial — and the three screens that work are all volume-based, so a raw
`volume / 20-day average` reads low all morning and they'd quietly fail to fire.

`market.py` corrects this by projecting the day's volume to a full-session
estimate using the typical U-shaped NSE volume curve. It's an estimate: a
signal that fires at 10:45 can un-fire by close. Only the 15:35 IST run matches
how the base rates were measured — earlier runs are early warning.

A symbol/screen pair alerts **once per day**, so seven runs don't send seven
copies of the same hit.

## Known limitations

- **GitHub's scheduler is best-effort.** Runs are commonly 5–15 minutes late,
  occasionally much worse. Times above are targets, not guarantees.
- **Yahoo Finance throttles cloud IPs.** `fetch_prices` retries with backoff,
  and the run aborts rather than emitting alerts off a partial pull.
- **NSE may refuse the runner's IP.** The universe fetch falls back to the
  committed `data/universe.json`.
- **Fundamental screens are uncalibrated.** Point-in-time fundamentals aren't
  available, only today's snapshot, so they carry survivorship and restatement
  bias and have no measured edge.
- **Calibrated across one long bull market**, positive in 9 of 12 years.
- **Edges this size are fragile** — +1.89% over six months is real at t=5.3 but
  sits close to ~0.35% delivery friction plus spread.

## Layout

```
screener/
  screens.py     screen definitions (firing-edge semantics)
  market.py      session state + intraday volume projection
  data.py        universe, prices, fundamentals (retry/fallback)
  run.py         live run, dedup, latest.json
  notify.py      step summary / issue comment / Telegram
  dashboard.py   renders docs/index.html
  calibrate.py   re-measures base rates (slow)
data/
  universe.json      committed fallback constituent list
  calibration.json   measured base rates + method note
  latest.json        most recent run
  state.json         per-day dedup
```

Research tooling. Not investment advice.
