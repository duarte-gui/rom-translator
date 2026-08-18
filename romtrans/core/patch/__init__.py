from .ips import apply_ips, create_ips
from .bps import apply_bps, create_bps

__all__ = ["apply_ips", "create_ips", "apply_bps", "create_bps", "detect_format"]


def detect_format(blob: bytes) -> str:
    if blob[:5] == b"PATCH":
        return "ips"
    if blob[:4] == b"BPS1":
        return "bps"
    if blob[:4] == b"UPS1":
        return "ups"
    if blob[:4] == b"\xd6\xc3\xc4\x00":
        return "xdelta3"
    if blob[:5] == b"PPF30" or blob[:3] == b"PPF":
        return "ppf"
    return "unknown"
