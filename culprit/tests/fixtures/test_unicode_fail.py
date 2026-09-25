"""
suspect: S2
mechanism: Calls to_label_line with a non-ASCII street and LABEL_ASCII_FASTPATH on to reproduce UnicodeEncodeError.
evidence: E02859
"""
from brightcart.common import flags
from brightcart.orders.address import NormalizedAddress, to_label_line


def test_unicode_label_line():
    """Reproducing the bug: label line must contain the street name unchanged."""
    flags.set_flag("LABEL_ASCII_FASTPATH", True)
    addr = NormalizedAddress(street="Schloßstraße 4", city="Wien", postal_code="1010", country="AT")
    # With LABEL_ASCII_FASTPATH on this raises UnicodeEncodeError.
    # After the fix it should return a label containing the street name.
    result = to_label_line(addr)
    flags.clear_flags()
    assert "Schloßstraße 4" in result
