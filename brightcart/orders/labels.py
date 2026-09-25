"""Shipping label builder."""
from brightcart.orders.address import NormalizedAddress, to_label_line


def build_label(addr: NormalizedAddress) -> str:
    """Return the full label string for printing."""
    return to_label_line(addr)
