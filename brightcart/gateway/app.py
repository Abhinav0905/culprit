"""Gateway service: POST /checkout."""
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

from brightcart.common.logging import Logger

app = FastAPI()
_log = Logger("gateway", "brightcart.gateway.app")


class CheckoutRequest(BaseModel):
    customer_id: str
    items: list[dict[str, Any]]
    address: dict[str, Any]
    payment: dict[str, Any]


class CheckoutResponse(BaseModel):
    order_id: str
    status: str


@app.post("/checkout", response_model=CheckoutResponse)
async def checkout(req: CheckoutRequest, request: Request) -> Any:
    trace_id = request.headers.get("X-Trace-Id", "")
    transport = request.app.state.orders_transport  # httpx.ASGITransport
    headers = {"X-Trace-Id": trace_id} if trace_id else {}

    async with httpx.AsyncClient(transport=transport, base_url="http://orders") as client:
        payload = {
            "customer_id": req.customer_id,
            "items": req.items,
            "address": req.address,
            "payment": req.payment,
        }

        resp = await client.post("/orders", json=payload, headers=headers)
        if resp.status_code >= 500:
            # one retry
            resp = await client.post("/orders", json=payload, headers=headers)

        if resp.status_code >= 500:
            _log.error(
                "checkout_failed",
                "checkout failed",
                trace_id=trace_id,
                upstream="orders",
                status=resp.status_code,
            )
            return Response(content='{"detail":"upstream error"}', status_code=502, media_type="application/json")

    data = resp.json()
    _log.info("checkout_ok", "checkout succeeded", trace_id=trace_id, order_id=data.get("order_id", ""))
    return CheckoutResponse(order_id=data["order_id"], status="ok")
