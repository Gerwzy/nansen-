#!/usr/bin/env python3
"""
Local web UI for the Nansen Alert Backtester.

Stdlib only. Reuses the API functions from backtest.py and reads
NANSEN_API_KEY from the environment, exactly like the CLI.

Usage:
    export NANSEN_API_KEY=your_key_here
    python server.py            # then open http://localhost:8000
    python server.py --port 9000
"""
import argparse
import html
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from backtest import SUPPORTED_CHAINS, evaluate, get_price_change, get_smart_money_flow

STYLE = """
:root { --bg:#f6f7f9; --card:#fff; --text:#1a1d21; --muted:#6b7280; --border:#e5e7eb;
        --accent:#2563eb; --good:#15803d; --good-bg:#dcfce7; --bad:#b91c1c; --bad-bg:#fee2e2; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0f1115; --card:#181b21; --text:#e5e7eb; --muted:#9ca3af; --border:#2a2f38;
          --accent:#60a5fa; --good:#4ade80; --good-bg:#12301f; --bad:#f87171; --bad-bg:#3a1515; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
main { max-width:640px; margin:40px auto; padding:0 16px; }
h1 { font-size:22px; margin:0 0 4px; }
p.sub { color:var(--muted); margin:0 0 24px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:20px; margin-bottom:16px; }
label { display:block; font-weight:600; font-size:13px; margin:12px 0 4px; }
label:first-child { margin-top:0; }
input, select { width:100%; padding:9px 10px; font:inherit; color:var(--text); background:var(--bg);
                border:1px solid var(--border); border-radius:6px; }
.row { display:flex; gap:12px; } .row > div { flex:1; }
button, a.btn { display:inline-block; margin-top:18px; padding:10px 18px; font:inherit; font-weight:600;
                color:#fff; background:var(--accent); border:0; border-radius:6px; cursor:pointer; text-decoration:none; }
table { width:100%; border-collapse:collapse; }
td { padding:8px 0; border-bottom:1px solid var(--border); vertical-align:top; }
tr:last-child td { border-bottom:0; }
td:first-child { color:var(--muted); width:40%; }
td.num { font-variant-numeric:tabular-nums; }
.mono { font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:13px; word-break:break-all; }
.pos { color:var(--good); } .neg { color:var(--bad); }
.verdict { padding:14px 16px; border-radius:8px; font-weight:600; }
.verdict.ok { background:var(--good-bg); color:var(--good); }
.verdict.no { background:var(--bad-bg); color:var(--bad); }
.verdict.na { background:var(--bg); color:var(--muted); }
.error { background:var(--bad-bg); color:var(--bad); padding:14px 16px; border-radius:8px; }
"""


def page(body: str) -> bytes:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nansen Alert Backtester</title><style>{STYLE}</style></head>
<body><main>
<h1>Nansen Alert Backtester</h1>
<p class="sub">Did smart money agree with the price move?</p>
{body}
</main></body></html>""".encode()


def form_html(values: dict | None = None) -> str:
    v = values or {}
    esc = lambda k, d="": html.escape(v.get(k, d), quote=True)
    predicted = v.get("predicted", "")
    chain_opts = "".join(f'<option value="{c}">' for c in SUPPORTED_CHAINS)
    pred_opts = "".join(
        f'<option value="{val}"{" selected" if val == predicted else ""}>{label}</option>'
        for val, label in [("", "— none —"), ("up", "up"), ("down", "down")]
    )
    default_date = (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d")
    return f"""<form class="card" method="get" action="/check">
<label for="chain">Chain</label>
<input id="chain" name="chain" list="chains" required value="{esc('chain', 'ethereum')}">
<datalist id="chains">{chain_opts}</datalist>
<label for="token">Token address</label>
<input id="token" name="token" required placeholder="0x…" value="{esc('token')}" class="mono">
<div class="row">
  <div><label for="date">Date</label>
  <input id="date" name="date" type="date" required value="{esc('date', default_date)}"></div>
  <div><label for="horizon">Horizon (days)</label>
  <input id="horizon" name="horizon" type="number" min="1" max="365" value="{esc('horizon', '7')}"></div>
</div>
<label for="predicted">Your alert predicted (optional)</label>
<select id="predicted" name="predicted">{pred_opts}</select>
<button type="submit">Run check</button>
</form>"""


def fmt_usd(value) -> str:
    if value is None:
        return "n/a (no data for this window)"
    cls = "pos" if value > 0 else "neg" if value < 0 else ""
    return f'<span class="{cls}">${value:,.0f}</span>'


def result_html(params: dict) -> str:
    chain = params.get("chain", "ethereum").strip() or "ethereum"
    token = params.get("token", "").strip()
    predicted = params.get("predicted") or None
    if not token:
        raise ValueError("Token address is required.")
    try:
        alert_time = datetime.strptime(params.get("date", ""), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError("Date must be in YYYY-MM-DD format.")
    try:
        horizon_days = int(params.get("horizon", "7"))
    except ValueError:
        raise ValueError("Horizon must be a whole number of days.")
    if horizon_days < 1:
        raise ValueError("Horizon must be at least 1 day.")
    if predicted not in (None, "up", "down"):
        raise ValueError("Predicted direction must be up or down.")
    if chain not in SUPPORTED_CHAINS:
        raise ValueError(f"Chain must be one of {', '.join(SUPPORTED_CHAINS)} (the historical endpoints only cover these).")

    end = alert_time + timedelta(days=horizon_days)
    price = get_price_change(chain, token, alert_time, end)
    flow = get_smart_money_flow(chain, token, alert_time, end)
    v = evaluate(price, flow, predicted)

    rows = [
        ("Token", f'<span class="mono">{html.escape(token)}</span> ({html.escape(chain)})'),
        ("Window", f"{alert_time.date()} → {end.date()} ({horizon_days}d)"),
    ]

    if price["available"] and price["change_pct"] is not None:
        pct = price["change_pct"]
        cls = "pos" if pct > 0 else "neg" if pct < 0 else ""
        rows.append(("Price change", f'{price["price_start"]:.6g} → {price["price_end"]:.6g} '
                                     f'<strong class="{cls}">({pct:+.2f}%)</strong>'))
    else:
        rows.append(("Price change", "not available for this window"))

    if flow["available"]:
        rows.append(("Smart money flow", f'{fmt_usd(flow["smart_trader_net_flow_usd"])} net → {v["smart_dir"]}'))
        rows.append(("Whale flow", f'{fmt_usd(flow["whale_net_flow_usd"])} net'))
        rows.append(("Exchange flow", f'{fmt_usd(flow["exchange_net_flow_usd"])} net'))
    else:
        rows.append(("Smart money flow", "not available for this window"))

    table = "".join(f"<tr><td>{k}</td><td class='num'>{v}</td></tr>" for k, v in rows)

    if v["confirmed"] is None:
        verdict = '<div class="verdict na">NO VERDICT — price or smart-money signal missing/flat</div>'
    elif v["confirmed"]:
        verdict = '<div class="verdict ok">CONFIRMED — smart money agreed with the price move</div>'
    else:
        verdict = '<div class="verdict no">NOT confirmed — smart money went against the price move</div>'
    if predicted:
        verdict += f'<table style="margin-top:12px"><tr><td>Your alert said</td><td>{predicted}</td></tr>'
        if v["agrees"] is not None:
            verdict += (
                f'<tr><td>Smart money</td><td><strong class="{"pos" if v["agrees"] else "neg"}">'
                f'{"agrees" if v["agrees"] else "disagrees"}</strong> with your alert</td></tr>'
            )
        verdict += "</table>"

    return f'<div class="card"><table>{table}</table></div><div class="card">{verdict}</div>'


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}

        if url.path == "/":
            self._send(page(form_html()))
        elif url.path == "/check":
            try:
                body = result_html(params)
            except SystemExit as e:  # backtest.py exits on missing key / API errors
                body = f'<div class="error">{html.escape(str(e.code))}</div>'
            except Exception as e:
                body = f'<div class="error">{html.escape(str(e) or type(e).__name__)}</div>'
            self._send(page(body + form_html(params)))
        else:
            self._send(page('<div class="error">Not found.</div><a class="btn" href="/">Back</a>'), 404)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local web UI for the Nansen Alert Backtester.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Nansen Alert Backtester UI running at http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
