"""
Broadcast Service
=================
Sends a message to a list of users via one or more channels.

Channels:
  whatsapp  — Twilio Messaging API  (WHATSAPP_PROVIDER=twilio, default)
             OR Meta Cloud API     (WHATSAPP_PROVIDER=meta)
  telegram  — Telegram Bot API     (TELEGRAM_BOT_TOKEN)

Each channel returns a ChannelResult: {sent, failed, skipped, errors[]}.
All HTTP calls inside a channel run concurrently via asyncio.gather,
so a 100-user broadcast with 200 ms latency per call takes ~200 ms total.

Environment variables
─────────────────────
  WHATSAPP_PROVIDER          twilio | meta               (default: twilio)

  # Twilio
  TWILIO_ACCOUNT_SID         AC...
  TWILIO_AUTH_TOKEN          secret
  TWILIO_WHATSAPP_FROM       +14155238886  (Twilio sandbox / approved number)

  # Meta Cloud API
  META_WHATSAPP_ACCESS_TOKEN  Bearer token from Meta Developer Console
  META_PHONE_NUMBER_ID        Numeric phone number ID from Meta

  # Telegram
  TELEGRAM_BOT_TOKEN          From @BotFather — only needed for Telegram broadcasts.
                              (Separate from any previous 2FA use; 2FA now uses TOTP.)
"""

import asyncio
import os
import re
from dataclasses import dataclass, field

import httpx

from app.models.user import User


# ── Result type ────────────────────────────────────────────────────────────────

@dataclass
class ChannelResult:
    sent:    int = 0
    failed:  int = 0
    skipped: int = 0
    errors:  list[str] = field(default_factory=list)


# ── Mobile number normaliser ───────────────────────────────────────────────────

def _e164(mobile: str) -> str:
    """Strip non-digits; keep leading '+'. Returns e.g. '+919876543210'."""
    digits = re.sub(r"[^\d+]", "", mobile)
    # Ensure leading +
    if not digits.startswith("+"):
        digits = "+" + digits
    return digits


# ── Telegram ───────────────────────────────────────────────────────────────────

async def _send_telegram_one(client: httpx.AsyncClient, chat_id: str, text: str) -> bool:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = await client.post(url, json={
            "chat_id":    chat_id,
            "text":       text,
            "parse_mode": "Markdown",
        }, timeout=10.0)
        return resp.status_code == 200
    except Exception:
        return False


async def send_telegram(users: list[User], message: str) -> ChannelResult:
    """Send `message` to every user that has a telegram_chat_id."""
    result = ChannelResult()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    if not bot_token:
        result.skipped = len(users)
        result.errors.append("TELEGRAM_BOT_TOKEN is not configured.")
        return result

    targets = [u for u in users if u.telegram_chat_id]
    result.skipped = len(users) - len(targets)

    if not targets:
        result.errors.append("No users have a telegram_chat_id set.")
        return result

    async with httpx.AsyncClient() as client:
        outcomes = await asyncio.gather(
            *[_send_telegram_one(client, u.telegram_chat_id, message) for u in targets],
            return_exceptions=True,
        )

    for ok in outcomes:
        if ok is True:
            result.sent += 1
        else:
            result.failed += 1

    return result


# ── WhatsApp via Twilio ────────────────────────────────────────────────────────

async def _send_twilio_one(client: httpx.AsyncClient, mobile: str, message: str) -> bool:
    sid   = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    frm   = os.getenv("TWILIO_WHATSAPP_FROM", "")
    if not all([sid, token, frm]):
        return False
    number = _e164(mobile)
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    try:
        resp = await client.post(url, data={
            "From": f"whatsapp:{frm}",
            "To":   f"whatsapp:{number}",
            "Body": message,
        }, auth=(sid, token), timeout=15.0)
        return resp.status_code in (200, 201)
    except Exception:
        return False


# ── WhatsApp via Meta Cloud API ────────────────────────────────────────────────

async def _send_meta_one(client: httpx.AsyncClient, mobile: str, message: str) -> bool:
    access_token   = os.getenv("META_WHATSAPP_ACCESS_TOKEN", "")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID", "")
    if not all([access_token, phone_number_id]):
        return False
    # Meta expects the number without '+', just digits
    number = re.sub(r"[^\d]", "", mobile)
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    try:
        resp = await client.post(url,
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "messaging_product": "whatsapp",
                "to":   number,
                "type": "text",
                "text": {"body": message},
            },
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


async def send_whatsapp(users: list[User], message: str) -> ChannelResult:
    """Send `message` to every user via WhatsApp (Twilio or Meta provider)."""
    result   = ChannelResult()
    provider = os.getenv("WHATSAPP_PROVIDER", "twilio").lower().strip()

    # Check credentials
    if provider == "twilio":
        ready = all(os.getenv(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM"))
        send_fn = _send_twilio_one
    elif provider == "meta":
        ready = all(os.getenv(k) for k in ("META_WHATSAPP_ACCESS_TOKEN", "META_PHONE_NUMBER_ID"))
        send_fn = _send_meta_one
    else:
        result.skipped = len(users)
        result.errors.append(f"Unknown WHATSAPP_PROVIDER '{provider}'. Use 'twilio' or 'meta'.")
        return result

    if not ready:
        result.skipped = len(users)
        result.errors.append(f"WhatsApp credentials for provider '{provider}' are not configured.")
        return result

    async with httpx.AsyncClient() as client:
        outcomes = await asyncio.gather(
            *[send_fn(client, u.mobile, message) for u in users],
            return_exceptions=True,
        )

    for ok in outcomes:
        if ok is True:
            result.sent += 1
        else:
            result.failed += 1

    return result


# ── Dispatcher ─────────────────────────────────────────────────────────────────

async def dispatch(
    users:    list[User],
    message:  str,
    channels: list[str],
) -> dict[str, dict]:
    """
    Broadcast `message` to `users` over each requested channel.
    Returns a dict keyed by channel name.
    """
    tasks = {}
    if "telegram" in channels:
        tasks["telegram"] = send_telegram(users, message)
    if "whatsapp" in channels:
        tasks["whatsapp"] = send_whatsapp(users, message)

    results = {}
    for channel, coro in tasks.items():
        res = await coro
        results[channel] = {
            "sent":    res.sent,
            "failed":  res.failed,
            "skipped": res.skipped,
            "errors":  res.errors,
        }
    return results
