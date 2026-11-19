"""Check one incoming message. Nothing is ever guessed or repaired here."""
from datetime import datetime

from simulator import config as C

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def validate(message):
    """Return (row, flags, reason).

    reason is None  -> the message is usable. row holds the cleaned values,
                       flags lists what was wrong with single values.
    reason is text  -> the whole message is rejected, row is None.
    """
    if not isinstance(message, dict):
        return None, [], "not a JSON object"
    if message.get("sensor_id") not in C.SENSOR_IDS:
        return None, [], "unknown sensor_id"
    try:
        datetime.strptime(message.get("ts"), TS_FORMAT)
    except (TypeError, ValueError):
        return None, [], "bad timestamp"

    row = {"sensor_id": message["sensor_id"], "ts": message["ts"]}
    flags = []
    for ch in C.CHANNELS:
        value = message.get(ch)
        low, high = C.VALID_RANGE[ch]
        if value is None:
            row[ch] = None
            flags.append("missing:" + ch)
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
            row[ch] = None                       # text, true/false or NaN
            flags.append("not_a_number:" + ch)
        elif value < low or value > high:
            row[ch] = None                       # cannot be a real measurement
            flags.append("out_of_range:" + ch)
        else:
            row[ch] = float(value)
    return row, flags, None
