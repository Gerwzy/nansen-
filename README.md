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
| `--token`        | yes      |            | Token contract address                          |
| `--date`         | yes      |            | Alert / snapshot date, `YYYY-MM-DD` (UTC)       |
| `--chain`        | no       | `ethereum` | Chain the token lives on                        |
| `--horizon-days` | no       | `1`        | How many days forward to check                  |
| `--predicted`    | no       |            | What your alert predicted: `up` or `down`       |

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
```

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

Verdict: **confirmed** when smart money was net buying and price went up, or net selling and price went down. Otherwise **not confirmed**.

## License

MIT — see [LICENSE](LICENSE).
