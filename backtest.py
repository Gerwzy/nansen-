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
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API_HOST = "https://api.nansen.ai"
OHLCV_PATH = "/api/v1beta1/tgm/historical-token-ohlcv"
FLOW_SUMMARY_PATH = "/api/v1beta1/tgm/historical-token-flow-summary"


def _api_key() -> str:
    key = os.environ.get("NANSEN_API_KEY")
    if not key:
        sys.exit("Missing NANSEN_API_KEY environment variable. Set it and try again.")
    return key


def _post(path: str, body: dict) -> dict:
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
    return {
        "available": True,
        "price_start": price_start,
        "price_end": price_end,
        "change_pct": change_pct,
    }


def get_smart_money_flow(chain: str, token_address: str, start: datetime, end: datetime) -> dict:
    body = {
        "chain": chain,
        "token_address": token_address,
        "date_range": {
            "from": start.strftime("%Y-%m-%d"),
            "to": end.strftime("%Y-%m-%d"),
        },
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


def direction_of(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value > 0:
        return "buying"
    if value < 0:
        return "selling"
    return "neutral"


def run(chain: str, token_address: str, alert_time: datetime, horizon_days: int, predicted: str | None) -> None:
    end = alert_time + timedelta(days=horizon_days)

    price = get_price_change(chain, token_address, alert_time, end)
    flow = get_smart_money_flow(chain, token_address, alert_time, end)

    print(f"\nToken:            {token_address} ({chain})")
    print(f"Window:            {alert_time.date()} -> {end.date()} ({horizon_days}d)")

    if not price["available"]:
        print("Price data:        not available for this window")
    else:
        print(f"Price:             {price['price_start']:.6g} -> {price['price_end']:.6g}  ({price['change_pct']:+.2f}%)")

    if not flow["available"]:
        print("Smart money data:  not available for this window")
        smart_dir = "unknown"
    else:
        smart_dir = direction_of(flow["smart_trader_net_flow_usd"])
        print(f"Smart money flow:  ${flow['smart_trader_net_flow_usd']:,.0f} net -> {smart_dir}")
        print(f"Whale flow:        ${flow['whale_net_flow_usd']:,.0f} net")
        print(f"Exchange flow:     ${flow['exchange_net_flow_usd']:,.0f} net")

    if price["available"] and flow["available"]:
        price_dir = "up" if price["change_pct"] > 0 else "down" if price["change_pct"] < 0 else "flat"
        confirmed = (smart_dir == "buying" and price_dir == "up") or (smart_dir == "selling" and price_dir == "down")
        verdict = "CONFIRMED — smart money agreed with the price move" if confirmed else "NOT confirmed — smart money went against the price move"
        print(f"\nVerdict:           {verdict}")

        if predicted:
            alert_matched_smart_money = (predicted == "up" and smart_dir == "buying") or (predicted == "down" and smart_dir == "selling")
            print(f"Your alert said:   {predicted}")
            print(f"Smart money says:  {'agrees' if alert_matched_smart_money else 'disagrees'} with your alert")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a token's price move against Nansen smart-money flow.")
    parser.add_argument("--chain", default="ethereum")
    parser.add_argument("--token", required=True, help="Token contract address")
    parser.add_argument("--date", required=True, help="Alert/snapshot date, YYYY-MM-DD")
    parser.add_argument("--horizon-days", type=int, default=1, help="How many days forward to check")
    parser.add_argument("--predicted", choices=["up", "down"], help="What the alert predicted, if any")
    args = parser.parse_args()

    alert_time = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    run(args.chain, args.token, alert_time, args.horizon_days, args.predicted)


if __name__ == "__main__":
    main()
