"""Safaricom Daraja M-Pesa Express (STK push). Fill the MPESA_* values in .env."""
import base64
import logging
import re
from datetime import datetime

import requests
from django.conf import settings

log = logging.getLogger("vipi")


class MpesaError(Exception):
    pass


def _base():
    return "https://api.safaricom.co.ke" if settings.MPESA["ENV"] == "production" else "https://sandbox.safaricom.co.ke"


def normalize_phone(phone: str) -> str:
    """0712 345678 / +254712345678 / 712345678 → 254712345678."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    elif len(digits) == 9:
        digits = "254" + digits
    if not re.fullmatch(r"254[17]\d{8}", digits):
        raise MpesaError("Enter a Kenyan M-Pesa number like 0712 345 678.")
    return digits


def is_configured() -> bool:
    m = settings.MPESA
    return bool(m["CONSUMER_KEY"] and m["CONSUMER_SECRET"] and m["PASSKEY"] and m["CALLBACK_URL"])


def _token() -> str:
    m = settings.MPESA
    r = requests.get(f"{_base()}/oauth/v1/generate?grant_type=client_credentials",
                     auth=(m["CONSUMER_KEY"], m["CONSUMER_SECRET"]), timeout=20)
    if r.status_code != 200:
        raise MpesaError(f"M-Pesa auth failed ({r.status_code}).")
    return r.json()["access_token"]


def stk_push(phone: str, amount_kes: int, reference: str, description: str) -> dict:
    m = settings.MPESA
    if not is_configured():
        raise MpesaError("M-Pesa is not configured on the server yet.")
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(f"{m['SHORTCODE']}{m['PASSKEY']}{ts}".encode()).decode()
    callback = m["CALLBACK_URL"]
    if m["CALLBACK_SECRET"]:
        callback += ("&" if "?" in callback else "?") + f"k={m['CALLBACK_SECRET']}"
    payload = {
        "BusinessShortCode": m["SHORTCODE"],
        "Password": password,
        "Timestamp": ts,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount_kes),
        "PartyA": phone,
        "PartyB": m["SHORTCODE"],
        "PhoneNumber": phone,
        "CallBackURL": callback,
        "AccountReference": reference[:12],
        "TransactionDesc": description[:13] or "Vipi pass",
    }
    r = requests.post(f"{_base()}/mpesa/stkpush/v1/processrequest", json=payload,
                      headers={"Authorization": f"Bearer {_token()}"}, timeout=30)
    data = r.json() if r.content else {}
    if r.status_code != 200 or data.get("ResponseCode") != "0":
        raise MpesaError(data.get("errorMessage") or data.get("ResponseDescription") or f"STK push failed ({r.status_code}).")
    return data


def parse_callback(body: dict) -> dict:
    """Returns {checkout_request_id, ok, receipt, amount, phone, reason}."""
    cb = body.get("Body", {}).get("stkCallback", {})
    items = {i.get("Name"): i.get("Value") for i in cb.get("CallbackMetadata", {}).get("Item", [])}
    return {
        "checkout_request_id": cb.get("CheckoutRequestID", ""),
        "ok": cb.get("ResultCode") == 0,
        "reason": cb.get("ResultDesc", ""),
        "receipt": str(items.get("MpesaReceiptNumber", "")),
        "amount": items.get("Amount"),
        "phone": str(items.get("PhoneNumber", "")),
    }
