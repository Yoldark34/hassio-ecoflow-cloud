"""Which app-API device type a serial number belongs to, so discovered devices need no manual type.

EcoFlow publishes no prefix table. Only prefixes confirmed on real units (field reports and the
app's own device-code registry, as compiled by ha-ecoflow-iot's KNOWN_PREFIXES.md) are listed, and
only where they map to one type of this integration. Anything else falls back to a manual choice.
"""

# Longest prefix wins, so a specific prefix can carve a device out of a broader family.
_TYPE_BY_PREFIX: dict[str, str] = {
    "ES21": "STREAM_AC_5000",  # STREAM 5000: same telemetry as the AC 5000
    "ES22": "STREAM_AC_5000",
    "R33": "DELTA_2",
    "R35": "DELTA_2_MAX",
    "R62": "RIVER_2_PRO",
    "DCAB": "DELTA_PRO",
    "MR5": "DELTA_PRO_3",
    "HW51": "POWERSTREAM",
    "HW52": "SMART_PLUG",
    "BX1": "GLACIER",
    "KT2": "WAVE_2",
    "BK21": "SMART_METER",
    "BK": "STREAM_AC",  # AC / AC Pro / Ultra / Ultra X / Pro share one decoder
}

# Bound to accounts but not readable through MQTT by this integration
UNSUPPORTED_PREFIXES: frozenset[str] = frozenset({"ES81", "SM2A"})


def device_type_for(sn: str) -> str | None:
    for prefix in sorted(_TYPE_BY_PREFIX, key=len, reverse=True):
        if sn.startswith(prefix):
            return _TYPE_BY_PREFIX[prefix]
    return None


def is_unsupported(sn: str) -> bool:
    return any(sn.startswith(prefix) for prefix in UNSUPPORTED_PREFIXES)
