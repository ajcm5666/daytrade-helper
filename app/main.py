from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import connect, init_db, row_to_dict
from app.market import get_quote
from app.notify import (
    discord_configured,
    send_discord,
    send_discord_detailed,
    send_telegram,
    telegram_configured,
)
from app.scanner import scan_alerts

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")

app = FastAPI(title="Daytrade Helper")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
scheduler = AsyncIOScheduler()


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _trade_pnl(side: str, entry: float, exit_price: float, shares: float) -> float:
    if side == "long":
        return (exit_price - entry) * shares
    return (entry - exit_price) * shares


def _stats(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("exit_price") is not None]
    pnls = [float(t["pnl"] or 0) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {
        "open": len(trades) - len(closed),
        "closed": len(closed),
        "win_rate": (len(wins) / len(closed) * 100) if closed else 0.0,
        "total_pnl": sum(pnls) if pnls else 0.0,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
    }


@app.on_event("startup")
async def startup() -> None:
    init_db()
    interval = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
    scheduler.add_job(scan_alerts, "interval", seconds=max(30, interval), id="scan")
    scheduler.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    scheduler.shutdown(wait=False)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    with connect() as conn:
        trades = [row_to_dict(r) for r in conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT 50"
        ).fetchall()]
        alerts = [row_to_dict(r) for r in conn.execute(
            "SELECT * FROM alerts ORDER BY active DESC, id DESC LIMIT 50"
        ).fetchall()]
        events = [row_to_dict(r) for r in conn.execute(
            "SELECT * FROM alert_events ORDER BY id DESC LIMIT 20"
        ).fetchall()]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "trades": trades,
            "alerts": alerts,
            "events": events,
            "stats": _stats(trades),
            "telegram_ok": telegram_configured(),
            "discord_ok": discord_configured(),
            "discord_status": request.query_params.get("discord"),
            "discord_code": request.query_params.get("code"),
            "now": _utcnow(),
        },
    )


@app.post("/trades")
async def create_trade(
    symbol: str = Form(...),
    side: str = Form(...),
    entry_price: float = Form(...),
    shares: float = Form(...),
    stop_price: float | None = Form(None),
    setup: str = Form(""),
    notes: str = Form(""),
    entry_at: str = Form(""),
):
    symbol = symbol.strip().upper()
    side = side.strip().lower()
    if side not in ("long", "short"):
        side = "long"
    when = entry_at.strip() or _utcnow()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO trades (
                symbol, side, entry_price, shares, stop_price,
                entry_at, setup, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                side,
                entry_price,
                shares,
                stop_price or None,
                when,
                setup.strip() or None,
                notes.strip() or None,
            ),
        )
    return RedirectResponse("/", status_code=303)


@app.post("/trades/{trade_id}/close")
async def close_trade(
    trade_id: int,
    exit_price: float = Form(...),
    exit_at: str = Form(""),
):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        if row:
            trade = row_to_dict(row)
            pnl = _trade_pnl(
                trade["side"],
                float(trade["entry_price"]),
                float(exit_price),
                float(trade["shares"]),
            )
            conn.execute(
                """
                UPDATE trades
                SET exit_price = ?, exit_at = ?, pnl = ?
                WHERE id = ?
                """,
                (exit_price, exit_at.strip() or _utcnow(), pnl, trade_id),
            )
    return RedirectResponse("/", status_code=303)


@app.post("/trades/{trade_id}/delete")
async def delete_trade(trade_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
    return RedirectResponse("/", status_code=303)


@app.post("/alerts")
async def create_alert(
    symbol: str = Form(...),
    condition: str = Form(...),
    threshold: float = Form(...),
    note: str = Form(""),
):
    symbol = symbol.strip().upper()
    condition = condition.strip().lower()
    allowed = {"above", "below", "pct_up", "pct_down", "volume_spike"}
    if condition not in allowed:
        condition = "above"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO alerts (symbol, condition, threshold, note, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (symbol, condition, threshold, note.strip() or None),
        )
    return RedirectResponse("/", status_code=303)


@app.post("/alerts/{alert_id}/toggle")
async def toggle_alert(alert_id: int):
    with connect() as conn:
        row = conn.execute(
            "SELECT active FROM alerts WHERE id = ?", (alert_id,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE alerts SET active = ? WHERE id = ?",
                (0 if row["active"] else 1, alert_id),
            )
    return RedirectResponse("/", status_code=303)


@app.post("/alerts/{alert_id}/delete")
async def delete_alert(alert_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM alert_events WHERE alert_id = ?", (alert_id,))
        conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    return RedirectResponse("/", status_code=303)


@app.post("/scan-now")
async def scan_now():
    await scan_alerts()
    return RedirectResponse("/", status_code=303)


@app.post("/test-telegram")
async def test_telegram():
    ok = await send_telegram("Daytrade Helper connected. Alerts will land here.")
    return RedirectResponse(f"/?telegram={'ok' if ok else 'fail'}", status_code=303)


@app.post("/test-discord")
async def test_discord():
    result = await send_discord_detailed(
        "✅ Daytrade Helper connected. Alerts will land here."
    )
    if result["ok"]:
        return RedirectResponse("/?discord=ok", status_code=303)
    code = result.get("status_code") or 0
    return RedirectResponse(f"/?discord=fail&code={code}", status_code=303)


@app.get("/api/discord-test")
async def api_discord_test():
    """JSON debug for Discord delivery (no webhook secret returned)."""
    if not discord_configured():
        return {"ok": False, "error": "DISCORD_WEBHOOK_URL not configured"}
    result = await send_discord_detailed(
        "✅ Daytrade Helper Discord test from /api/discord-test"
    )
    return {
        "ok": result["ok"],
        "status_code": result["status_code"],
        "body": result["body"],
        "configured": True,
    }


@app.get("/api/quote/{symbol}")
async def api_quote(symbol: str):
    quote = get_quote(symbol)
    if not quote:
        return {"ok": False, "error": "No quote"}
    return {
        "ok": True,
        "symbol": quote.symbol,
        "price": quote.price,
        "prev_close": quote.prev_close,
        "pct_change": round(quote.pct_change, 2),
        "volume": quote.volume,
        "avg_volume": quote.avg_volume,
        "volume_ratio": round(quote.volume_ratio, 2),
    }


@app.get("/manifest.webmanifest")
async def manifest():
    return {
        "name": "Daytrade Helper",
        "short_name": "Daytrade",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f1419",
        "theme_color": "#0f1419",
        "icons": [
            {
                "src": "/static/icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }
        ],
    }