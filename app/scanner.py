from __future__ import annotations

from datetime import datetime, timezone

from app.db import connect, row_to_dict
from app.market import get_quote
from app.notify import send_alert


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def evaluate_alert(alert: dict, quote) -> str | None:
    cond = alert["condition"]
    thr = float(alert["threshold"])
    if cond == "above" and quote.price >= thr:
        return f"{quote.symbol} hit ${quote.price:.2f} (above ${thr:.2f})"
    if cond == "below" and quote.price <= thr:
        return f"{quote.symbol} hit ${quote.price:.2f} (below ${thr:.2f})"
    if cond == "pct_up" and quote.pct_change >= thr:
        return (
            f"{quote.symbol} up {quote.pct_change:.2f}% "
            f"(alert ≥ {thr:.2f}%) @ ${quote.price:.2f}"
        )
    if cond == "pct_down" and quote.pct_change <= -abs(thr):
        return (
            f"{quote.symbol} down {quote.pct_change:.2f}% "
            f"(alert ≤ -{abs(thr):.2f}%) @ ${quote.price:.2f}"
        )
    if cond == "volume_spike" and quote.volume_ratio >= thr:
        return (
            f"{quote.symbol} volume {quote.volume_ratio:.1f}x avg "
            f"(alert ≥ {thr:.1f}x) @ ${quote.price:.2f}"
        )
    return None


async def scan_alerts() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE active = 1 ORDER BY id"
        ).fetchall()
    alerts = [row_to_dict(r) for r in rows]
    fired: list[dict] = []

    for alert in alerts:
        quote = get_quote(alert["symbol"])
        if not quote:
            continue
        message = evaluate_alert(alert, quote)
        if not message:
            continue

        note = (alert.get("note") or "").strip()
        if note:
            message = f"{message}\nNote: {note}"

        with connect() as conn:
            conn.execute(
                """
                UPDATE alerts
                SET last_triggered_at = ?, active = 0
                WHERE id = ?
                """,
                (_utcnow(), alert["id"]),
            )
            conn.execute(
                """
                INSERT INTO alert_events (alert_id, symbol, message, price)
                VALUES (?, ?, ?, ?)
                """,
                (alert["id"], alert["symbol"], message, quote.price),
            )

        await send_alert(f"**ALERT**\n{message}")
        fired.append({"alert_id": alert["id"], "message": message, "price": quote.price})

    return fired