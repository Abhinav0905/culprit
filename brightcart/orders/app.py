"""Orders service: POST /orders."""
import traceback
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

from brightcart.common.logging import Logger
from brightcart.orders import db
from brightcart.orders.address import normalize_address
from brightcart.orders.labels import build_label

app = FastAPI()
_log = Logger("orders", "brightcart.orders.app")


class OrderRequest(BaseModel):
    customer_id: str
    items: list[dict[str, Any]]
    address: dict[str, Any]
    payment: dict[str, Any]


@app.post("/orders", status_code=201)
async def create_order(req: OrderRequest, request: Request) -> Any:
    trace_id = request.headers.get("X-Trace-Id", "")
    order_id = f"ord-{uuid.uuid4().hex[:6]}"
    conn = db.acquire()
    try:
        addr = normalize_address(req.address)
        build_label(addr)

        transport = request.app.state.payments_transport
        headers = {"X-Trace-Id": trace_id} if trace_id else {}
        async with httpx.AsyncClient(transport=transport, base_url="http://payments") as client:
            charge_resp = await client.post(
                "/charges",
                json=req.payment,
                headers=headers,
            )
            if charge_resp.status_code >= 400:
                _log.error(
                    "order_failed",
                    "payment failed",
                    trace_id=trace_id,
                    order_id=order_id,
                    status=charge_resp.status_code,
                )
                return Response(status_code=500, content='{"detail":"payment error"}', media_type="application/json")

        _log.info("order_created", "order created", trace_id=trace_id, order_id=order_id)
        return {"order_id": order_id, "status": "created"}
    except Exception as exc:
        # Extract brightcart frames from the traceback
        tb = traceback.extract_tb(exc.__traceback__)
        frames = [
            {"module": _path_to_module(f.filename), "function": f.name, "line": f.lineno}
            for f in tb
            if "brightcart" in f.filename
        ]
        _log.error_exc(
            "order_failed",
            "order creation failed",
            exc=exc,
            frames=frames,
            trace_id=trace_id,
            order_id=order_id,
            field=_guess_field(exc),
            country=req.address.get("country", "").upper(),
        )
        return Response(status_code=500, content='{"detail":"internal error"}', media_type="application/json")
    finally:
        conn.close()


def _path_to_module(path: str) -> str:
    """Convert a file path to a dotted module name for brightcart frames."""
    import re
    m = re.search(r"brightcart[/\\](.+)\.py$", path)
    if not m:
        return path
    return "brightcart." + m.group(1).replace("/", ".").replace("\\", ".")


def _guess_field(exc: BaseException) -> str:
    """Best-effort field extraction from address-related errors."""
    msg = str(exc).lower()
    for field in ("street", "city", "postal_code", "country"):
        if field in msg:
            return field
    return "street"
