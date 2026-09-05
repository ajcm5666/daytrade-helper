from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request

import httpx

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DaytradeHelper/1.2; +https://daytrade-helper.onrender.com)",
    "Accept": "application/json",
}


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def discord_webhook_configured() -> bool:
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    return url.startswith("https://discord.com/api/webhooks/") or url.startswith(
        "https://discordapp.com/api/webhooks/"
    )


def discord_bot_configured() -> bool:
    return bool(
        os.getenv("DISCORD_BOT_TOKEN", "").strip()
        and os.getenv("DISCORD_CHANNEL_ID", "").strip()
    )


def discord_configured() -> bool:
    return discord_webhook_configured() or discord_bot_configured()


def any_notify_configured() -> bool:
    return telegram_configured() or discord_configured()


async def send_telegram(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_HTTP_HEADERS) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception:
        return False


def _discord_bot_post_sync(message: str) -> tuple[bool, int, str]:
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.getenv("DISCORD_CHANNEL_ID", "").strip()
    if not token or not channel_id:
        return False, 0, "missing_bot_token_or_channel"

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload = json.dumps(
        {
            "content": message[:1900],
            "allowed_mentions": {"parse": []},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": _HTTP_HEADERS["User-Agent"],
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:200]
            return True, getattr(resp, "status", 200) or 200, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return False, int(e.code), body
    except Exception as e:
        return False, 0, str(e)[:200]


def _discord_webhook_post_sync(message: str) -> tuple[bool, int, str]:
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not (
        webhook.startswith("https://discord.com/api/webhooks/")
        or webhook.startswith("https://discordapp.com/api/webhooks/")
    ):
        return False, 0, "missing_or_invalid_webhook"

    target = webhook if "wait=" in webhook else (
        webhook + ("&" if "?" in webhook else "?") + "wait=true"
    )
    payload = json.dumps(
        {
            "content": message[:1900],
            "username": "Daytrade Helper",
            "allowed_mentions": {"parse": []},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        target,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": _HTTP_HEADERS["User-Agent"],
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:200]
            return True, getattr(resp, "status", 200) or 200, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        # Do not retry Cloudflare 1015 / IP bans — retries make the ban longer.
        return False, int(e.code), body
    except Exception as e:
        return False, 0, str(e)[:200]


def _discord_post_sync(message: str) -> tuple[bool, int, str]:
    # Prefer bot API when configured (often healthier rate limits than webhooks
    # on shared cloud host IPs).
    if discord_bot_configured():
        return _discord_bot_post_sync(message)
    return _discord_webhook_post_sync(message)


async def send_discord(message: str) -> bool:
    ok, _code, _body = await asyncio.to_thread(_discord_post_sync, message)
    return ok


async def send_discord_detailed(message: str) -> dict:
    ok, code, body = await asyncio.to_thread(_discord_post_sync, message)
    return {"ok": ok, "status_code": code, "body": body}


async def send_alert(message: str) -> dict[str, bool]:
    return {
        "telegram": await send_telegram(message) if telegram_configured() else False,
        "discord": await send_discord(message) if discord_configured() else False,
    }
