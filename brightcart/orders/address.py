"""Address normalisation for orders."""
import re
from typing import NamedTuple

from brightcart.common import flags


class NormalizedAddress(NamedTuple):
    street: str
    city: str
    postal_code: str
    country: str


def normalize_address(addr: dict) -> NormalizedAddress:
    """Trim, collapse spaces, uppercase country, validate postal code."""
    street = re.sub(r"\s+", " ", addr.get("street", "")).strip()
    city = re.sub(r"\s+", " ", addr.get("city", "")).strip()
    postal_code = re.sub(r"\s+", " ", addr.get("postal_code", "")).strip()
    country = addr.get("country", "").strip().upper()
    if not postal_code:
        raise ValueError("postal_code is required")
    return NormalizedAddress(street=street, city=city, postal_code=postal_code, country=country)


def to_label_line(addr: NormalizedAddress) -> str:
    """Build label line: 'STREET, POSTAL CITY, COUNTRY'.

    When LABEL_ASCII_FASTPATH is on (orders v2.3.0), the result is
    ASCII-encoded for a legacy label printer.  Any non-ASCII character
    raises UnicodeEncodeError.
    """
    line = f"{addr.street}, {addr.postal_code} {addr.city}, {addr.country}"
    if flags.is_enabled("LABEL_ASCII_FASTPATH"):
        line = line.encode("ascii").decode("ascii")
    return line
