"""Happy-path tests for the Brightcart services.

All addresses are ASCII-only.  The missing Unicode coverage is deliberate —
it matches an open action item from the July 2026 postmortem.
"""
import pytest
import httpx
from fastapi.testclient import TestClient

from brightcart.common import flags
from brightcart.orders import db as pool


@pytest.fixture(autouse=True)
def reset_state():
    """Reset shared state between tests."""
    flags.clear_flags()
    pool.reset()
    yield
    flags.clear_flags()
    pool.reset()


def _make_clients():
    """Return (gateway_client, orders_client, payments_client) wired in-process."""
    from brightcart.gateway.app import app as gw_app
    from brightcart.orders.app import app as ord_app
    from brightcart.payments.app import app as pay_app

    pay_transport = httpx.ASGITransport(app=pay_app)
    ord_app.state.payments_transport = pay_transport

    ord_transport = httpx.ASGITransport(app=ord_app)
    gw_app.state.orders_transport = ord_transport

    gw_client = TestClient(gw_app, raise_server_exceptions=False)
    return gw_client


ASCII_ADDRESS = {
    "street": "123 Main St",
    "city": "Springfield",
    "postal_code": "12345",
    "country": "US",
}

PAYMENT = {
    "amount_cents": 1999,
    "currency": "USD",
    "card_token": "tok_test_visa",
}


def test_checkout_ascii_address_succeeds():
    """A checkout with an ASCII address should return 200 with order_id."""
    client = _make_clients()
    resp = client.post(
        "/checkout",
        json={
            "customer_id": "cust-1",
            "items": [{"sku": "WIDGET-A", "qty": 2}],
            "address": ASCII_ADDRESS,
            "payment": PAYMENT,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "order_id" in data
    assert data["status"] == "ok"


def test_checkout_flag_off_ascii_still_succeeds():
    """With LABEL_ASCII_FASTPATH off, ASCII addresses still work fine."""
    flags.set_flag("LABEL_ASCII_FASTPATH", False)
    client = _make_clients()
    resp = client.post(
        "/checkout",
        json={
            "customer_id": "cust-2",
            "items": [{"sku": "WIDGET-B", "qty": 1}],
            "address": ASCII_ADDRESS,
            "payment": PAYMENT,
        },
    )
    assert resp.status_code == 200


def test_checkout_flag_on_ascii_still_succeeds():
    """With LABEL_ASCII_FASTPATH on, ASCII addresses still go through."""
    flags.set_flag("LABEL_ASCII_FASTPATH", True)
    client = _make_clients()
    resp = client.post(
        "/checkout",
        json={
            "customer_id": "cust-3",
            "items": [{"sku": "WIDGET-C", "qty": 3}],
            "address": ASCII_ADDRESS,
            "payment": PAYMENT,
        },
    )
    assert resp.status_code == 200


def test_normalize_address_trims_whitespace():
    """normalize_address should collapse internal spaces and strip edges."""
    from brightcart.orders.address import normalize_address

    addr = normalize_address({"street": "  10  Elm  St  ", "city": "Shelbyville", "postal_code": "67890", "country": "us"})
    assert addr.street == "10 Elm St"
    assert addr.country == "US"


def test_to_label_line_format():
    """to_label_line builds the expected STREET, POSTAL CITY, COUNTRY format."""
    from brightcart.orders.address import NormalizedAddress, to_label_line

    flags.set_flag("LABEL_ASCII_FASTPATH", False)
    addr = NormalizedAddress(street="10 Elm St", city="Shelbyville", postal_code="67890", country="US")
    assert to_label_line(addr) == "10 Elm St, 67890 Shelbyville, US"


def test_pool_acquires_and_releases():
    """Pool acquire/release should not raise for a single connection."""
    conn = pool.acquire()
    conn.close()


def test_payments_charge_endpoint():
    """Payments /charges should return 201 with a charge_id."""
    from brightcart.payments.app import app as pay_app

    client = TestClient(pay_app)
    resp = client.post("/charges", json={"amount_cents": 500, "currency": "USD", "card_token": "tok_abc"})
    assert resp.status_code == 201
    assert "charge_id" in resp.json()
