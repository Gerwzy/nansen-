#!/usr/bin/env python3
"""
Nansen Alert Backtester — Meridian Buildathon entry.

Checks whether Nansen "smart money" wallets were net buying or selling a
token around a given point in time, and compares that against what actually
happened to the price afterwards. Works for ANY token/date — bring your own
alert history, or just try a token+date you're curious about.

Needs only a free Nansen API key (tested against the free tier — no paid
plan required for the two endpoints used here).

Usage:
    export NANSEN_API_KEY=your_key_here
    python backtest.py --chain ethereum --token 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
        --date 2026-09-18 --horizon-days 7 --predicted up

    # or backtest a whole alert history at once:
    python backtest.py --batch alerts.csv
"""
import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API_HOST = "https://api.nansen.ai"
OHLCV_PATH = "/api/v1beta1/tgm/historical-token-ohlcv"
FLOW_SUMMARY_PATH = "/api/v1beta1/tgm/historical-token-flow-summary"

SUPPORTED_CHAINS = ["ethereum", "base", "bnb", "solana"]

API_CALLS = 0


def _api_key() -> str:
    key = os.environ.get("NANSEN_API_KEY")
    if not key:
        sys.exit("Missing NANSEN_API_KEY environment variable. Set it and try again.")
    return key


def _post(path: str, body: dict) -> dict:
    global API_CALLS
    API_CALLS += 1
    req = urllib.request.Request(
        API_HOST + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "apikey": _api_key()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Nansen API error {e.code} on {path}: {e.read().decode()[:300]}")


def get_price_change(chain: str, token_address: str, start: datetime, end: datetime) -> dict:
    body = {
        "chain": chain,
        "token_address": token_address,
        "date_from": start.strftime("%Y-%m-%d"),
        "as_of_date": end.strftime("%Y-%m-%d"),
        "timeframe": "1d",
    }
    data = _post(OHLCV_PATH, body).get("data", [])
    if not data:
        return {"available": False}
    price_start = data[0]["open"]
    price_end = data[-1]["close"]
    change_pct = (price_end - price_start) / price_start * 100 if price_start else None
    return {"available": True, "price_start": price_start, "price_end": price_end, "change_pct": change_pct}


def get_smart_money_flow(chain: str, token_address: str, start: datetime, end: datetime) -> dict:
    body = {
        "chain": chain,
        "token_address": token_address,
        "date_range": {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")},
    }
    rows = _post(FLOW_SUMMARY_PATH, body).get("data", [])
    if not rows:
        return {"available": False}
    row = rows[0]
    return {
        "available": True,
        "smart_trader_net_flow_usd": row.get("smart_trader_net_flow_usd"),
        "whale_net_flow_usd": row.get("whale_net_flow_usd"),
        "exchange_net_flow_usd": row.get("exchange_net_flow_usd"),
    }


def direction_of(value) -> str:
    if value is None:
        return "unknown"
    if value > 0:
        return "buying"
    if value < 0:
        return "selling"
    return "neutral"


def fmt_usd(value) -> str:
    return "n/a (no data for this window)" if value is None else f"${value:,.0f}"


def evaluate(price: dict, flow: dict, predicted) -> dict:
    smart_dir = direction_of(flow.get("smart_trader_net_flow_usd")) if flow.get("available") else "unknown"
    price_dir = None
    if price.get("available") and price.get("change_pct") is not None:
        pct = price["change_pct"]
        price_dir = "up" if pct > 0 else "down" if pct < 0 else "flat"
    confirmed = None
    if price_dir in ("up", "down") and smart_dir in ("buying", "selling"):
        confirmed = (smart_dir == "buying" and price_dir == "up") or (smart_dir == "selling" and price_dir == "down")
    agrees = None
    if predicted and smart_dir in ("buying", "selling"):
        agrees = (predicted == "up" and smart_dir == "buying") or (predicted == "down" and smart_dir == "selling")
    alert_correct = None
    if predicted and price_dir in ("up", "down"):
        alert_correct = predicted == price_dir
    return {"smart_dir": smart_dir, "price_dir": price_dir, "confirmed": confirmed, "agrees": agrees, "alert_correct": alert_correct}


def run(chain, token_address, alert_time, horizon_days, predicted) -> None:
    end = alert_time + timedelta(days=horizon_days)
    price = get_price_change(chain, token_address, alert_time, end)
    flow = get_smart_money_flow(chain, token_address, alert_time, end)
    v = evaluate(price, flow, predicted)

    print(f"\nToken:             {token_address} ({chain})")
    print(f"Window:            {alert_time.date()} -> {end.date()} ({horizon_days}d)")
    if not price["available"]:
        print("Price data:        not available for this window")
    else:
        print(f"Price:             {price['price_start']:.6g} -> {price['price_end']:.6g}  ({price['change_pct']:+.2f}%)")
    if not flow["available"]:
        print("Smart money data:  not available for this window")
    else:
        print(f"Smart money flow:  {fmt_usd(flow['smart_trader_net_flow_usd'])} net -> {v['smart_dir']}")
        print(f"Whale flow:        {fmt_usd(flow['whale_net_flow_usd'])} net")
        print(f"Exchange flow:     {fmt_usd(flow['exchange_net_flow_usd'])} net")

    if v["confirmed"] is None:
        print("\nVerdict:           NO VERDICT — price or smart-money signal missing/flat")
    elif v["confirmed"]:
        print("\nVerdict:           CONFIRMED — smart money agreed with the price move")
    else:
        print("\nVerdict:           NOT confirmed — smart money went against the price move")
    if predicted:
        print(f"Your alert said:   {predicted}")
        if v["agrees"] is not None:
            print(f"Smart money says:  {'agrees' if v['agrees'] else 'disagrees'} with your alert")
    print(f"\nNansen API calls:  {API_CALLS}")


def run_batch(csv_path, default_chain, default_horizon) -> None:
    with open(csv_path, newline="") as f:
        alerts = list(csv.DictReader(f))
    results = []
    print(f"{'date':<11} {'chain':<9} {'token':<14} {'price':>8} {'smart$':>14} {'verdict':<10} {'alert':<6} SM agrees")
    for a in alerts:
        chain = (a.get("chain") or default_chain).strip()
        token = a["token"].strip()
        horizon = int(a.get("horizon_days") or default_horizon)
        predicted = (a.get("predicted") or "").strip() or None
        start = datetime.strptime(a["date"].strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = start + timedelta(days=horizon)
        price = get_price_change(chain, token, start, end)
        flow = get_smart_money_flow(chain, token, start, end)
        v = evaluate(price, flow, predicted)
        results.append(v)
        pct = f"{price['change_pct']:+.1f}%" if price.get("available") and price.get("change_pct") is not None else "n/a"
        sm = flow.get("smart_trader_net_flow_usd") if flow.get("available") else None
        sm_s = f"{sm:,.0f}" if sm is not None else "n/a"
        verdict = {True: "CONFIRMED", False: "AGAINST", None: "n/a"}[v["confirmed"]]
        agrees = {True: "yes", False: "no", None: "-"}[v["agrees"]]
        print(f"{start.date()!s:<11} {chain:<9} {token[:12]+'..':<14} {pct:>8} {sm_s:>14} {verdict:<10} {predicted or '-':<6} {agrees}")

    def rate(key, subset=None):
        vals = [r[key] for r in (subset or results) if r[key] is not None]
        return (sum(vals), len(vals))

    c, n = rate("confirmed")
    print(f"\nSmart money confirmed the move:  {c}/{n}" + (f" ({c/n:.0%})" if n else ""))
    ok, n2 = rate("alert_correct")
    if n2:
        print(f"Your alerts were right:          {ok}/{n2} ({ok/n2:.0%})")
        agreed = [r for r in results if r["agrees"] is True and r["alert_correct"] is not None]
        against = [r for r in results if r["agrees"] is False and r["alert_correct"] is not None]
        for label, grp in (("  ...when smart money agreed:   ", agreed), ("  ...when smart money disagreed:", against)):
            k, m = rate("alert_correct", grp) if grp else (0, 0)
            print(f"{label} {k}/{m}" + (f" ({k/m:.0%})" if m else ""))
    print(f"\nNansen API calls:  {API_CALLS}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a token's price move against Nansen smart-money flow.")
    parser.add_argument("--chain", default="ethereum")
    parser.add_argument("--token", help="Token contract address")
    parser.add_argument("--date", help="Alert/snapshot date, YYYY-MM-DD")
    parser.add_argument("--batch", metavar="CSV", help="Backtest many alerts: CSV with date,token[,chain,horizon_days,predicted]")
    parser.add_argument("--horizon-days", type=int, default=1)
    parser.add_argument("--predicted", choices=["up", "down"])
    args = parser.parse_args()

    if args.chain not in SUPPORTED_CHAINS:
        parser.error(f"--chain must be one of {SUPPORTED_CHAINS} (the historical endpoints only cover these)")
    if args.batch:
        run_batch(args.batch, args.chain, args.horizon_days)
        return
    if not (args.token and args.date):
        parser.error("--token and --date are required (or use --batch)")
    alert_time = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    run(args.chain, args.token, alert_time, args.horizon_days, args.predicted)


if __name__ == "__main__":
    main()
