"""Tiny stand-in for the Stripe API, used only to rehearse scripts/staging_journey.py offline.

It implements just what the shop calls (Checkout Sessions create/expire, PaymentIntent retrieve, Refunds) and
sends signed webhooks to the shop exactly like Stripe does. Real validation happens against Stripe test mode.

Run:  python tests/fake_stripe.py <port> <shop-webhook-url> <webhook-secret>
Then start the shop with:  python tests/fake_stripe.py --serve-app <port-of-fake>  (patches stripe.api_base)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl

import httpx

SESSIONS: dict[str, dict] = {}
REFUNDS: dict[str, dict] = {}
IDEMPOTENT: dict[str, dict] = {}
EMAILS: list[dict] = []
LOCK = threading.Lock()
WEBHOOK_URL = ""
SECRET = ""


def _nest(pairs: list[tuple[str, str]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        parts = key.replace("]", "").split("[")
        cur = out
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            if last:
                cur[part] = value
            else:
                cur = cur.setdefault(part, {})
    return out


def _send_event(event_type: str, obj: dict) -> None:
    payload = json.dumps({"id": f"evt_{uuid.uuid4().hex}", "object": "event", "type": event_type,
                          "data": {"object": obj}})
    ts = int(time.time())
    sig = hmac.new(SECRET.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()

    def go() -> None:
        time.sleep(0.3)
        httpx.post(WEBHOOK_URL, content=payload, timeout=30,
                   headers={"stripe-signature": f"t={ts},v1={sig}", "content-type": "application/json"})

    threading.Thread(target=go, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path.startswith("/v1/payment_intents/"):
            return self._json({"id": path.rsplit("/", 1)[1], "object": "payment_intent",
                               "latest_charge": {"id": "ch_x", "balance_transaction": {"id": "txn_x", "fee": 56}}})
        if path == "/v1/refunds":
            return self._json({"object": "list", "data": list(REFUNDS.values()), "has_more": False})
        self._json({"error": {"message": f"fake: no GET {path}"}}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length).decode()
        form = json.loads(raw) if raw.startswith("{") else _nest(parse_qsl(raw, keep_blank_values=True))
        key = self.headers.get("Idempotency-Key")
        path = self.path.split("?")[0]
        with LOCK:
            if key and key in IDEMPOTENT:
                return self._json(IDEMPOTENT[key])
            result = self._handle(path, form)
            if key and result is not None:
                IDEMPOTENT[key] = result
        if result is None:
            return self._json({"error": {"message": f"fake: no POST {path}"}}, 404)
        self._json(result)

    def _handle(self, path: str, form: dict) -> dict | None:
        if path == "/v1/checkout/sessions":
            sid = f"cs_test_{uuid.uuid4().hex}"
            items = form.get("line_items", {}).values()
            total = sum(int(i["price_data"]["unit_amount"]) * int(i["quantity"]) for i in items)
            total += sum(int(o["shipping_rate_data"]["fixed_amount"]["amount"])
                         for o in form.get("shipping_options", {}).values())
            s = {"id": sid, "object": "checkout.session", "status": "open", "payment_status": "unpaid",
                 "url": f"https://checkout.stripe.com/c/pay/{sid}", "amount_total": total,
                 "client_reference_id": form.get("client_reference_id"), "metadata": form.get("metadata", {}),
                 "customer_email": form.get("customer_email"), "payment_intent": None,
                 "payment_method_types": ["card"]}
            SESSIONS[sid] = s
            return s
        if path.startswith("/v1/checkout/sessions/") and path.endswith("/expire"):
            s = SESSIONS[path.split("/")[-2]]
            if s["status"] == "open":
                s["status"] = "expired"
                _send_event("checkout.session.expired", s)
            return s
        if path.startswith("/_test/pay/"):
            s = SESSIONS[path.rsplit("/", 1)[1]]
            s.update(status="complete", payment_status="paid", payment_intent=f"pi_{uuid.uuid4().hex[:20]}",
                     customer_details={"name": "Test Customer", "email": s["customer_email"], "phone": "+447700900123",
                                       "address": {"line1": "1 Test Street", "city": "Manchester",
                                                   "postal_code": "M1 1AA", "country": "GB"}})
            _send_event("checkout.session.completed", s)
            return s
        if path == "/resend/emails":  # stand-in for https://api.resend.com/emails
            EMAILS.append(form)
            return {"id": str(uuid.uuid4())}
        if path == "/v1/refunds":
            rid = f"re_{uuid.uuid4().hex[:20]}"
            r = {"id": rid, "object": "refund", "amount": int(form["amount"]), "status": "succeeded",
                 "payment_intent": form["payment_intent"]}
            REFUNDS[rid] = r
            done = [x for x in REFUNDS.values() if x["payment_intent"] == r["payment_intent"]]
            charge = {"id": "ch_x", "object": "charge", "payment_intent": r["payment_intent"],
                      "amount_refunded": sum(x["amount"] for x in done),
                      "refunds": {"object": "list", "data": done}}
            _send_event("charge.refunded", charge)  # races the shop's own DB write, like real Stripe can
            return r
        return None


def serve_app(fake_port: int) -> None:
    import stripe
    import uvicorn

    stripe.api_base = f"http://127.0.0.1:{fake_port}"
    sys.path.insert(0, ".")
    real_post = httpx.post

    def post(url, *args, **kwargs):  # send Resend calls to the fake too
        if str(url).startswith("https://api.resend.com/"):
            url = f"http://127.0.0.1:{fake_port}/resend/" + str(url).split("api.resend.com/", 1)[1]
        return real_post(url, *args, **kwargs)

    httpx.post = post
    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="warning")


if __name__ == "__main__":
    if sys.argv[1] == "--serve-app":
        serve_app(int(sys.argv[2]))
    else:
        port, WEBHOOK_URL, SECRET = int(sys.argv[1]), sys.argv[2], sys.argv[3]
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
