"""Load generator for Brightcart incident scenarios.

Usage:
    python -m brightcart.loadgen --scenario inc-001 --out datasets/incidents/INC-001
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# INC-001 scenario constants
# ---------------------------------------------------------------------------

SEED = 7
WINDOW_START = datetime(2026, 9, 24, 8, 40, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 9, 24, 9, 40, 0, tzinfo=timezone.utc)
INTERVAL_S = 2          # ~1 checkout every 2 simulated seconds → 1800 over 60 min

# Deploy times
C1_TIME = datetime(2026, 9, 24, 8, 55, 0, tzinfo=timezone.utc)   # orders 2.3.0, flag on
C2_TIME = datetime(2026, 9, 24, 9, 3, 0, tzinfo=timezone.utc)    # payments 1.8.2

# DACH campaign starts → non-ASCII addresses appear
DACH_START = datetime(2026, 9, 24, 9, 6, 0, tzinfo=timezone.utc)

# Alert time
ALERT_TIME = datetime(2026, 9, 24, 9, 12, 0, tzinfo=timezone.utc)

# Latency warning window (p95 > 400 ms) from 09:04
LATENCY_HIGH_START = datetime(2026, 9, 24, 9, 4, 0, tzinfo=timezone.utc)
LATENCY_HIGH_END = datetime(2026, 9, 24, 9, 11, 59, tzinfo=timezone.utc)

# DB pool goes above 90% at 09:10
POOL_HIGH_START = datetime(2026, 9, 24, 9, 10, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Address fixtures
# ---------------------------------------------------------------------------

_ASCII_STREETS = [
    "12 Oak Lane", "45 Elm Street", "7 Maple Ave", "200 Pine Road",
    "33 Cedar Blvd", "88 Birch Court", "5 Walnut Drive", "17 Ash Close",
    "99 Poplar Way", "64 Willow Path",
]
_ASCII_CITIES = [
    ("Springfield", "12345", "US"),
    ("Shelbyville", "67890", "US"),
    ("Capital City", "11111", "US"),
    ("Ogdenville", "22222", "US"),
    ("Brockway", "33333", "US"),
    ("Paris", "75001", "FR"),
    ("Lyon", "69001", "FR"),
    ("Madrid", "28001", "ES"),
    ("Barcelona", "08001", "ES"),
    ("Rome", "00100", "IT"),
]
_DACH_CITIES = [
    ("München", "80331", "DE"),
    ("Berlin", "10115", "DE"),
    ("Hamburg", "20095", "DE"),
    ("Frankfurt am Main", "60311", "DE"),
    ("Wien", "1010", "AT"),
    ("Graz", "8010", "AT"),
    ("Zürich", "8001", "CH"),
    ("Bern", "3011", "CH"),
]
_DACH_UNICODE_STREETS = [
    "Schloßstraße 4",
    "Münchener Straße 12",
    "Göteborg Allee 3",
    "Äußere Bahnhofstraße 7",
    "Röntgenplatz 2",
    "Hügelweg 15",
    "Büropark 8",
    "Wößnerstraße 22",
]
_DACH_ASCII_STREETS = [
    "Bahnhofstrasse 1", "Hauptstrasse 5", "Kirchgasse 10",
    "Rathausplatz 3", "Marktstrasse 7",
]


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _ascii_address(rng: random.Random) -> dict[str, str]:
    street = rng.choice(_ASCII_STREETS)
    city, postal, country = rng.choice(_ASCII_CITIES)
    return {"street": street, "city": city, "postal_code": postal, "country": country}


def _dach_address(rng: random.Random, unicode_chance: float = 0.40) -> dict[str, str]:
    city, postal, country = rng.choice(_DACH_CITIES)
    if rng.random() < unicode_chance:
        street = rng.choice(_DACH_UNICODE_STREETS)
    else:
        street = rng.choice(_DACH_ASCII_STREETS)
    return {"street": street, "city": city, "postal_code": postal, "country": country}


def _make_address(rng: random.Random, ts: datetime, dach_active: bool) -> dict[str, str]:
    """Return an address. DACH share is 3% before campaign, 20% after.

    Before the DACH campaign starts all addresses are ASCII (including the
    rare DACH sample — those use ASCII streets only).
    """
    dach_share = 0.20 if dach_active else 0.03
    if rng.random() < dach_share:
        # Before the campaign, DACH addresses still use ASCII streets only
        unicode_chance = 0.40 if dach_active else 0.0
        return _dach_address(rng, unicode_chance=unicode_chance)
    return _ascii_address(rng)


def _payment(rng: random.Random) -> dict[str, Any]:
    return {
        "amount_cents": rng.randint(500, 20000),
        "currency": "EUR" if rng.random() < 0.4 else "USD",
        "card_token": f"tok_{rng.randint(10000, 99999)}",
    }


def _trace_id(n: int) -> str:
    return f"tr-{n:06d}"


def _order_id(n: int) -> str:
    return f"ord-{n:06d}"


def _is_unicode_address(addr: dict[str, str]) -> bool:
    try:
        addr["street"].encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------

def run_inc001(out_dir: Path) -> None:
    # Separate rngs so address/payment distributions are independent of timing jitter
    time_rng = random.Random(SEED)        # timing jitter
    addr_rng = random.Random(SEED + 1)    # address selection
    pay_rng = random.Random(SEED + 2)     # payment fields
    lat_rng = random.Random(SEED + 3)     # payment latency / pool noise

    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    gw_lines: list[str] = []
    ord_lines: list[str] = []
    pay_lines: list[str] = []
    metrics_lines: list[str] = []

    # Metrics accumulation per minute
    # key: (minute_ts_str, service, name) -> list of values
    metric_buckets: dict[tuple[str, str, str], list[float]] = {}

    def add_metric(ts: datetime, service: str, name: str, value: float) -> None:
        minute = ts.replace(second=0, microsecond=0)
        key = (_ts(minute), service, name)
        metric_buckets.setdefault(key, []).append(value)

    # Tracking state
    payments_version = "1.8.1"
    orders_version = "2.2.4"
    flag_ascii_fastpath = False
    total = 0
    failed = 0
    failed_after_first_error = 0
    total_after_first_error = 0
    first_error_ts: datetime | None = None
    last_latency_warn_minute: datetime | None = None
    last_pool_warn_minute: datetime | None = None

    # Build list of checkout times across the 60-minute window
    current = WINDOW_START
    checkout_times: list[datetime] = []
    while current < WINDOW_END:
        checkout_times.append(current)
        ms_jitter = time_rng.randint(-500, 500)
        current = current + timedelta(seconds=INTERVAL_S, milliseconds=ms_jitter)

    checkout_n = 0
    for ts in checkout_times:
        checkout_n += 1
        trace_id = _trace_id(checkout_n)
        order_id = _order_id(checkout_n)

        # Apply deploys at their timestamps
        dach_active = ts >= DACH_START
        if ts >= C1_TIME and orders_version == "2.2.4":
            orders_version = "2.3.0"
            flag_ascii_fastpath = True
        if ts >= C2_TIME and payments_version == "1.8.1":
            payments_version = "1.8.2"

        addr = _make_address(addr_rng, ts, dach_active)
        pmt = _payment(pay_rng)
        is_failing = flag_ascii_fastpath and _is_unicode_address(addr)

        # --- Payments log ---
        # Simulate payment latency
        if payments_version == "1.8.1":
            pay_lat = lat_rng.gauss(300, 30)
        else:
            pay_lat = lat_rng.gauss(350, 50)  # slightly higher after C2
        pay_lat = max(50, pay_lat)

        pay_log_ts = ts + timedelta(milliseconds=lat_rng.randint(10, 50))
        if not is_failing:
            pay_lines.append(json.dumps({
                "ts": _ts(pay_log_ts),
                "service": "payments",
                "level": "INFO",
                "logger": "brightcart.payments.app",
                "event": "charge_ok",
                "msg": "charge captured",
                "trace_id": trace_id,
                "charge_id": f"ch-{pay_rng.randint(100000, 999999)}",
                "latency_ms": round(pay_lat, 1),
            }))

        # Payments latency warnings (once per minute, 09:04 to 09:11)
        if LATENCY_HIGH_START <= ts <= LATENCY_HIGH_END:
            minute_ts = ts.replace(second=0, microsecond=0)
            if last_latency_warn_minute != minute_ts:
                last_latency_warn_minute = minute_ts
                p95 = round(400 + lat_rng.gauss(20, 5), 1)
                pay_lines.append(json.dumps({
                    "ts": _ts(minute_ts + timedelta(seconds=30)),
                    "service": "payments",
                    "level": "WARN",
                    "logger": "brightcart.payments.app",
                    "event": "latency_high",
                    "msg": f"p95 latency {p95}ms exceeds 400ms threshold",
                    "p95_ms": p95,
                }))
                add_metric(minute_ts, "payments", "p95_latency_ms", p95)
            else:
                add_metric(ts, "payments", "p95_latency_ms", round(pay_lat, 1))
        else:
            add_metric(ts, "payments", "p95_latency_ms", round(pay_lat, 1))

        # Orders log
        if is_failing:
            # Build the UnicodeEncodeError frame stack
            ord_err_ts = ts + timedelta(milliseconds=lat_rng.randint(5, 30))
            ord_lines.append(json.dumps({
                "ts": _ts(ord_err_ts),
                "service": "orders",
                "level": "ERROR",
                "logger": "brightcart.orders.app",
                "event": "order_failed",
                "msg": "order creation failed",
                "trace_id": trace_id,
                "order_id": order_id,
                "field": "street",
                "country": addr["country"],
                "exc_type": "UnicodeEncodeError",
                "exc_message": (
                    f"'ascii' codec can't encode character '\\xdf' in position "
                    f"{_first_nonascii_pos(addr['street'])}: ordinal not in range(128)"
                ),
                "frames": [
                    {"module": "brightcart.orders.app", "function": "create_order", "line": 58},
                    {"module": "brightcart.orders.labels", "function": "build_label", "line": 21},
                    {"module": "brightcart.orders.address", "function": "to_label_line", "line": 44},
                ],
            }))
            if first_error_ts is None:
                first_error_ts = ord_err_ts
        else:
            ord_ok_ts = ts + timedelta(milliseconds=lat_rng.randint(5, 80))
            ord_lines.append(json.dumps({
                "ts": _ts(ord_ok_ts),
                "service": "orders",
                "level": "INFO",
                "logger": "brightcart.orders.app",
                "event": "order_created",
                "msg": "order created",
                "trace_id": trace_id,
                "order_id": order_id,
            }))

        # DB pool high warnings starting at 09:10 (once per minute)
        if ts >= POOL_HIGH_START:
            minute_ts = ts.replace(second=0, microsecond=0)
            if last_pool_warn_minute != minute_ts:
                last_pool_warn_minute = minute_ts
                # Calculate pool usage: baseline ~60%, adds ~1% per minute after first error
                minutes_since_error = max(0, (ts - first_error_ts).total_seconds() / 60) if first_error_ts else 0
                usage_pct = min(98, 60 + minutes_since_error * 5 + lat_rng.gauss(2, 1))
                in_use = int(usage_pct / 100 * 20)
                ord_lines.append(json.dumps({
                    "ts": _ts(minute_ts + timedelta(seconds=15)),
                    "service": "orders",
                    "level": "WARN",
                    "logger": "brightcart.orders.db",
                    "event": "db_pool_high",
                    "msg": f"DB pool usage high: {usage_pct:.0f}%",
                    "pool_size": 20,
                    "in_use": in_use,
                    "usage_pct": round(usage_pct, 1),
                }))
                add_metric(minute_ts, "orders", "db_pool_usage_pct", round(usage_pct, 1))
            else:
                minutes_since_error = max(0, (ts - first_error_ts).total_seconds() / 60) if first_error_ts else 0
                usage_pct = min(98, 60 + minutes_since_error * 5 + lat_rng.gauss(2, 1))
            add_metric(ts, "orders", "db_pool_usage_pct", round(usage_pct, 1))
        else:
            # Baseline pool usage 55-65%
            base_usage = 55 + lat_rng.gauss(5, 2)
            add_metric(ts, "orders", "db_pool_usage_pct", round(base_usage, 1))

        # Gateway log
        if is_failing:
            gw_err_ts = ts + timedelta(milliseconds=lat_rng.randint(40, 80))
            gw_lines.append(json.dumps({
                "ts": _ts(gw_err_ts),
                "service": "gateway",
                "level": "ERROR",
                "logger": "brightcart.gateway.app",
                "event": "checkout_failed",
                "msg": "checkout failed",
                "trace_id": trace_id,
                "upstream": "orders",
                "status": 500,
            }))
        else:
            gw_ok_ts = ts + timedelta(milliseconds=lat_rng.randint(50, 200))
            gw_lines.append(json.dumps({
                "ts": _ts(gw_ok_ts),
                "service": "gateway",
                "level": "INFO",
                "logger": "brightcart.gateway.app",
                "event": "checkout_ok",
                "msg": "checkout succeeded",
                "trace_id": trace_id,
                "order_id": order_id,
            }))

        # Metrics: error rate and DACH share
        error_val = 100.0 if is_failing else 0.0
        add_metric(ts, "gateway", "error_rate_pct", error_val)
        dach_val = 1.0 if addr.get("country") in ("DE", "AT", "CH") else 0.0
        add_metric(ts, "gateway", "country_share_dach_pct", dach_val)

        total += 1
        if first_error_ts and ts >= first_error_ts:
            total_after_first_error += 1
            if is_failing:
                failed_after_first_error += 1
        if is_failing:
            failed += 1

    # Write per-minute aggregate metrics
    # Bucket keys are already minute-aligned ts strings
    minute_aggregates: dict[tuple[str, str, str], float] = {}
    for (minute_ts_str, service, name), values in metric_buckets.items():
        if name in ("error_rate_pct", "country_share_dach_pct"):
            agg = round(sum(values) / len(values), 2)
        else:
            # p95 or pool: use 95th percentile for latency, mean for pool
            if name == "p95_latency_ms":
                sorted_vals = sorted(values)
                idx = int(len(sorted_vals) * 0.95)
                agg = round(sorted_vals[min(idx, len(sorted_vals) - 1)], 1)
            else:
                agg = round(sum(values) / len(values), 1)
        minute_aggregates[(minute_ts_str, service, name)] = agg

    for (minute_ts_str, service, name), value in sorted(minute_aggregates.items()):
        metrics_lines.append(json.dumps({
            "ts": minute_ts_str,
            "service": service,
            "name": name,
            "value": value,
        }))

    # Write log files
    (logs_dir / "gateway.jsonl").write_text("\n".join(gw_lines) + "\n")
    (logs_dir / "orders.jsonl").write_text("\n".join(ord_lines) + "\n")
    (logs_dir / "payments.jsonl").write_text("\n".join(pay_lines) + "\n")
    (out_dir / "metrics.jsonl").write_text("\n".join(metrics_lines) + "\n")

    # Write changes.json
    changes = [
        {
            "id": "C1",
            "ts": _ts(C1_TIME),
            "service": "orders",
            "from_version": "2.2.4",
            "to_version": "2.3.0",
            "summary": "Print-ready shipping labels (ASCII fast path for legacy label printer)",
            "files": ["brightcart/orders/address.py", "brightcart/orders/labels.py"],
            "flags": {"LABEL_ASCII_FASTPATH": True},
            "commit": "c1deadbeef",
        },
        {
            "id": "C2",
            "ts": _ts(C2_TIME),
            "service": "payments",
            "from_version": "1.8.1",
            "to_version": "1.8.2",
            "summary": "Increase retry jitter from 50 ms to 120 ms",
            "files": ["brightcart/payments/retry.py"],
            "flags": {},
            "commit": "c2cafebabe",
        },
    ]
    (out_dir / "changes.json").write_text(json.dumps(changes, indent=2) + "\n")

    # Write architecture.json
    architecture = {
        "services": [
            {"name": "gateway", "depends_on": ["orders"], "user_facing": True},
            {"name": "orders", "depends_on": ["payments", "orders-db"]},
            {"name": "payments", "depends_on": []},
            {"name": "orders-db", "kind": "datastore", "depends_on": []},
        ]
    }
    (out_dir / "architecture.json").write_text(json.dumps(architecture, indent=2) + "\n")

    # Write meta.json (incident_commit filled in by caller)
    incident_commit = _git_head()
    meta = {
        "incident_id": "INC-001",
        "title": "Checkout failures after the DACH campaign launch",
        "alert_at": "2026-09-24T09:12:00.000Z",
        "window": {
            "start": "2026-09-24T08:40:00.000Z",
            "end": "2026-09-24T09:40:00.000Z",
        },
        "incident_commit": incident_commit,
        "seed": SEED,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    # Print summary
    fail_rate = failed_after_first_error / total_after_first_error * 100 if total_after_first_error else 0
    print(f"\n=== INC-001 dataset summary ===")
    print(f"Total checkouts simulated : {total}")
    print(f"Total failed checkouts    : {failed}")
    print(f"First orders ERROR        : {_ts(first_error_ts) if first_error_ts else 'none'}")
    print(f"Failure rate after error  : {fail_rate:.1f}% ({failed_after_first_error}/{total_after_first_error})")
    print(f"Gateway lines             : {len(gw_lines)}")
    print(f"Orders lines              : {len(ord_lines)}")
    print(f"Payments lines            : {len(pay_lines)}")
    print(f"Metrics lines             : {len(metrics_lines)}")
    print(f"Output directory          : {out_dir.resolve()}")
    print(f"incident_commit           : {incident_commit}")

    # Event counts by service and level
    for service, lines in [("gateway", gw_lines), ("orders", ord_lines), ("payments", pay_lines)]:
        by_level: dict[str, int] = {}
        for line in lines:
            try:
                rec = json.loads(line)
                lvl = rec.get("level", "?")
                by_level[lvl] = by_level.get(lvl, 0) + 1
            except Exception:
                pass
        print(f"  {service}: " + ", ".join(f"{lvl}={cnt}" for lvl, cnt in sorted(by_level.items())))


def _first_nonascii_pos(text: str) -> int:
    for i, ch in enumerate(text):
        if ord(ch) > 127:
            return i
    return 0


def _git_head() -> str:
    import subprocess
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Brightcart load generator")
    parser.add_argument("--scenario", required=True, choices=["inc-001"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out_path = Path(args.out)
    if args.scenario == "inc-001":
        run_inc001(out_path)
    else:
        print(f"Unknown scenario: {args.scenario}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
