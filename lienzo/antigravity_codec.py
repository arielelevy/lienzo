"""Bounded allowlist for the observed agy 1.4.3 gemini_coder.Step wire format.

This is a history decoder, never a completion/state detector. Unknown fields are
skipped without decoding their contents. Thinking, signatures and tool arguments
are deliberately absent from the returned contract.
"""

from datetime import UTC, datetime
from uuid import UUID

from captura import tapar

MAX_BLOB = 1024 * 1024
MAX_FIELDS = 512


class CodecError(ValueError):
    pass


def _varint(blob, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(blob):
            raise CodecError("truncated_wire")
        byte = blob[pos]
        pos += 1
        if shift == 63 and byte > 1:
            raise CodecError("oversized_varint")
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise CodecError("oversized_varint")


def fields(blob):
    if not isinstance(blob, bytes) or len(blob) > MAX_BLOB:
        raise CodecError("blob_limit")
    pos, result, count = 0, {}, 0
    while pos < len(blob):
        count += 1
        if count > MAX_FIELDS:
            raise CodecError("field_limit")
        tag, pos = _varint(blob, pos)
        number, wire = tag >> 3, tag & 7
        if not 0 < number < 2**29:
            raise CodecError("invalid_field")
        if wire == 0:
            value, pos = _varint(blob, pos)
        elif wire in (1, 2, 5):
            if wire == 2:
                size, pos = _varint(blob, pos)
            else:
                size = 8 if wire == 1 else 4
            if size > len(blob) - pos:
                raise CodecError("truncated_wire")
            value = blob[pos : pos + size]
            pos += size
        else:
            raise CodecError("unsupported_wire")
        result.setdefault(number, []).append((wire, value))
    return result


def one(data, number, wire, default=None):
    values = data.get(number, [])
    if not values:
        return default
    if len(values) != 1 or values[0][0] != wire:
        raise CodecError("ambiguous_field")
    return values[0][1]


def _text(blob):
    try:
        value = blob.decode("utf-8", errors="strict")
    except UnicodeError:
        raise CodecError("invalid_utf8") from None
    return tapar(value)[0]


def _timestamp(blob):
    if blob is None:
        return None
    data = fields(blob)
    seconds, nanos = one(data, 1, 0, 0), one(data, 2, 0, 0)
    if not 0 <= nanos < 1_000_000_000:
        raise CodecError("invalid_timestamp")
    try:
        return datetime.fromtimestamp(seconds, UTC).isoformat()
    except ValueError, OverflowError, OSError:
        raise CodecError("invalid_timestamp") from None


def decode_step(idx, step_type, status, step_format, metadata, payload):
    if step_format != 0 or step_type not in (14, 15, 101, 132):
        raise CodecError("unsupported_step")
    data, meta = fields(payload), fields(metadata)
    if one(data, 1, 0, 0) != step_type or one(data, 4, 0, 0) != status:
        raise CodecError("step_mismatch")
    if one(data, 5, 2) != metadata:
        raise CodecError("metadata_mismatch")
    execution = one(meta, 12, 2, b"")
    try:
        execution = execution.decode("ascii")
        if str(UUID(execution)) != execution:
            raise ValueError
    except ValueError, UnicodeError:
        raise CodecError("invalid_execution_id") from None
    result = {
        "idx": idx,
        "execution": execution,
        "ts": _timestamp(one(meta, 1, 2)),
        "prompt": "",
        "text": "",
        "tool": None,
    }
    if step_type == 14:
        user = fields(one(data, 19, 2, b""))
        result["prompt"] = "\n".join(_text(value) for field in (1, 2) if (value := one(user, field, 2)))
    elif step_type == 15:
        planner = fields(one(data, 20, 2, b""))
        result["text"] = _text(one(planner, 1, 2, b""))
    elif step_type == 132:
        tool = fields(one(meta, 4, 2, b""))
        name = one(tool, 2, 2, b"")
        # Tool names are identifiers, not free-form arguments or results.
        if name:
            text = _text(name)
            if len(text) > 120 or not all(c.isalnum() or c in "_.-" for c in text):
                text = "herramienta"
            result["tool"] = text
    return result
