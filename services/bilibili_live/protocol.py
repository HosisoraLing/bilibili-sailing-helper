from __future__ import annotations

import json
import struct
import zlib
from typing import Any


HEADER_LEN = 16
VERSION_DEFLATE = 2
VERSION_BROTLI = 3

OP_HEARTBEAT = 2
OP_HEARTBEAT_REPLY = 3
OP_MESSAGE = 5
OP_AUTH = 7
OP_AUTH_REPLY = 8


def pack_packet(operation: int, body: bytes = b"", version: int = 1, sequence: int = 1) -> bytes:
    packet_len = HEADER_LEN + len(body)
    header = struct.pack("!IHHII", packet_len, HEADER_LEN, version, operation, sequence)
    return header + body


def pack_heartbeat() -> bytes:
    return pack_packet(OP_HEARTBEAT)


def pack_auth(payload: dict[str, Any]) -> bytes:
    return pack_packet(
        OP_AUTH,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )


def unpack_packets(raw: bytes) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    offset = 0
    while offset + HEADER_LEN <= len(raw):
        packet_len, header_len, version, operation, sequence = struct.unpack(
            "!IHHII",
            raw[offset: offset + HEADER_LEN],
        )
        if packet_len < header_len or header_len < HEADER_LEN:
            break
        if offset + packet_len > len(raw):
            break

        body = raw[offset + header_len: offset + packet_len]
        if version == VERSION_DEFLATE:
            packets.extend(unpack_packets(zlib.decompress(body)))
        elif version == VERSION_BROTLI:
            import brotli

            packets.extend(unpack_packets(brotli.decompress(body)))
        else:
            packets.append({
                "operation": operation,
                "body": body,
                "version": version,
                "sequence": sequence,
            })
        offset += packet_len
    return packets
