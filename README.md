# Nansen Alert Backtester

A tiny tool for the **Nansen Meridian Buildathon**: did Nansen *smart money* agree with a price move — or with your trading alert?

Give it a token, a date and a time horizon. It pulls the token's price change over that window and the net flow of Nansen-labelled smart traders, whales and exchanges, then tells you whether smart money was on the right side of the move.

## Why

Price alerts, Telegram calls and your own gut feeling all say "this is going up". Nansen's smart-money labels let you check that after the fact:

- **Was smart money buying while price went up?** Then the move was *confirmed* by informed flow.
- **Was smart money selling into the pump?** That's a warning sign worth knowing about.
- **Did your alert agree with smart money?** Backtest your own alert history, one date at a time.

It works for any token and any date, so you can bring your own alert history or just poke at something you're curious about.

## Requirements

- Python 3.10+
- **Zero external dependencies** — standard library only, nothing to `pip install`.
- A Nansen API key in the `NANSEN_API_KEY` environment variable. Get one free at [app.nansen.ai/api](https://app.nansen.ai/api). The two endpoints used work on the free tier.

```bash
export NANSEN_API_KEY=your_key_here
```

## Command line

```bash
python backtest.py --chain ethereum --token 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
    --date 2026-09-18 --horizon-days 7 --predicted up
```

| Flag             | Required | Default    | Meaning                                         |
|------------------|----------|------------|-------------------------------------------------|
| `--token`        | yes¹     |            | Token contract address                          |
| `--date`         | yes¹     |            | Alert / snapshot date, `YYYY-MM-DD` (UTC)       |
| `--chain`        | no       | `ethereum` | Chain the token lives on — see [Supported chains](#supported-chains) |
| `--horizon-days` | no       | `1`        | How many days forward to check                  |
| `--predicted`    | no       |            | What your alert predicted: `up` or `down`       |
| `--batch`        | no       |            | CSV of alerts to backtest at once — see [Batch mode](#batch-mode) |

¹ Not needed with `--batch`.

Example output:

```
Token:            0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 (ethereum)
Window:            2026-09-18 -> 2026-09-25 (7d)
Price:             ... -> ...  (+x.xx%)
Smart money flow:  $... net -> buying
Whale flow:        $... net
Exchange flow:     $... net

Verdict:           CONFIRMED — smart money agreed with the price move
Your alert said:   up
Smart money says:  agrees with your alert

Nansen API calls:  2
```

If the price didn't move, smart money was flat, or either data source has nothing for the window, the verdict is `NO VERDICT — price or smart-money signal missing/flat` instead of a guess.

## Batch mode

Backtest a whole alert history in one go and get a hit-rate scorecard:

```bash
python backtest.py --batch examples_alerts.csv
```

The CSV needs a header row. `date` and `token` are required; the rest are optional per row and fall back to `--chain` / `--horizon-days` / no prediction:

```csv
date,token,chain,horizon_days,predicted
2026-08-01,0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2,ethereum,7,up
2026-08-15,0x514910771AF9Ca656af840dff83E8264EcF986CA,ethereum,7,up
2026-09-01,0x514910771AF9Ca656af840dff83E8264EcF986CA,ethereum,7,down
```

A ready-to-run example is in [`examples_alerts.csv`](examples_alerts.csv).

Output is one line per alert, then a scorecard:

```
date        chain     token             price         smart$ verdict    alert  SM agrees
2026-08-01  ethereum  0xC02aaA39b2..    +x.x%        ...      CONFIRMED  up     yes
...

Smart money confirmed the move:  x/y (..%)
Your alerts were right:          x/y (..%)
  ...when smart money agreed:    x/y (..%)
  ...when smart money disagreed: x/y (..%)

Nansen API calls:  6
```

- **Smart money confirmed the move** — how often smart-money flow pointed the same way as the price.
- **Your alerts were right** — how often your `predicted` direction matched the actual price move.
- **...when smart money agreed / disagreed** — your hit rate split by whether smart money backed your alert. If the "agreed" rate is clearly higher, smart money is a useful filter for your alerts.

Rows with no verdict (missing or flat data) are left out of the rates. Each alert costs 2 API calls; the total is printed at the end.

## Supported chains

`ethereum`, `base`, `bnb`, `solana`.

These are the chains the two historical endpoints (`historical-token-ohlcv` and `historical-token-flow-summary`) cover. Any other `--chain` value is rejected up front rather than failing at the API. The web UI uses the same list.

## Web UI

The same check, in a browser. Also stdlib only (`http.server`), no JS/CSS libraries.

```bash
export NANSEN_API_KEY=your_key_here
python server.py            # open http://localhost:8000
python server.py --port 9000
```

Fill in chain, token address, date, horizon and (optionally) your predicted direction, and hit **Run check**.

## How it works

Two Nansen API calls (`POST`, `apikey` header):

- `/api/v1beta1/tgm/historical-token-ohlcv` — daily candles; price change = first open → last close.
- `/api/v1beta1/tgm/historical-token-flow-summary` — net USD flow of smart traders, whales and exchanges over the window.

Verdict: **confirmed** when smart money was net buying and price went up, or net selling and price went down; **not confirmed** when they point in opposite directions; **no verdict** when either side is missing or flat.

## License

MIT — see [LICENSE](LICENSE).
