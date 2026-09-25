"""Payments service: POST /charges."""
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from brightcart.common.logging import Logger
from brightcart.payments.retry import call_provider

app = FastAPI()
_log = Logger("payments", "brightcart.payments.app")


class ChargeRequest(BaseModel):
    amount_cents: int
    currency: str
    card_token: str


@app.post("/charges", status_code=201)
async def charge(req: ChargeRequest) -> Any:
    if req.amount_cents <= 0:
        _log.error("charge_failed", "invalid amount", amount_cents=req.amount_cents)
        return {"error": "invalid amount"}
    if not req.currency:
        _log.error("charge_failed", "missing currency")
        return {"error": "missing currency"}
    if not req.card_token:
        _log.error("charge_failed", "missing card_token")
        return {"error": "missing card_token"}

    result = call_provider(req.amount_cents, req.currency, req.card_token)
    _log.info("charge_ok", "charge captured", charge_id=result["charge_id"])
    return result
