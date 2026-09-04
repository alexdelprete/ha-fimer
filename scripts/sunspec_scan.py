#!/usr/bin/env -S uv run --quiet --with modbus-connection[tmodbus]==4.10.0 python
"""Scan the SunSpec model chain of an ABB/FIMER inverter or VSN datalogger.

Walks the chain from the SunSpec marker, prints every model with its address
and length, decodes the common model, and dumps every register of every
model into a JSON snapshot. The snapshot uses the ``{"holding": {address:
value}}`` layout that ``modbus_connection.mock.MockModbusUnit.load_raw()``
accepts, so a capture from a real device can back a regression test.

Run it with uv (the shebang pulls the Modbus backend on the fly)::

    uv run --with "modbus-connection[tmodbus]==4.10.0" scripts/sunspec_scan.py 192.168.1.50

Behind a VSN300/VSN700 card the defaults apply: unit ID 2 and base address 0.
A natively-Modbus inverter usually needs ``--unit 1 --base 40000``. Without
``--base`` the script tries 0 first and then 40000.

The inverter must be awake: a PVI without grid-powered logger answers
nothing at night.
"""

# ruff: noqa: T201  (a CLI reports through print)
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

from modbus_connection import ModbusError, ModbusTcpParams, ModbusUnit
from modbus_connection.decode import decode_string
from modbus_connection.model.sunspec import SunSpecError, SunSpecModel, scan
from modbus_connection.tmodbus import ModbusConnection

# Header (2) + data registers of the SunSpec common model, per the spec.
COMMON_MODEL_ID = 1
ABB_VENDOR_MODEL_ID = 64061
# Old PVI firmware rejects wide reads; the previous integration used 64.
DEFAULT_CHUNK = 60
DEFAULT_BASES = (0, 40000)

# (offset from data start, register count, name) for the common model.
COMMON_FIELDS = (
    (0, 16, "Mn"),
    (16, 16, "Md"),
    (32, 8, "Opt"),
    (40, 8, "Vr"),
    (48, 16, "SN"),
)


async def read_block(unit: ModbusUnit, address: int, count: int, chunk: int) -> dict[int, int]:
    """Read ``count`` holding registers from ``address`` in chunks of ``chunk``."""
    words: dict[int, int] = {}
    for start in range(address, address + count, chunk):
        size = min(chunk, address + count - start)
        values = await unit.read_holding_registers(start, size)
        words.update(zip(range(start, start + size), values, strict=True))
    return words


async def find_chain(unit: ModbusUnit, bases: tuple[int, ...]) -> tuple[int, list[SunSpecModel]]:
    """Return the base address that carries a SunSpec marker and its model chain."""
    errors: list[str] = []
    for base in bases:
        try:
            models = await scan(unit, base)
        except SunSpecError as err:
            errors.append(f"base {base}: {err}")
            continue
        return base, models.chain
    raise SunSpecError("; ".join(errors))


def decode_common(words: dict[int, int], model: SunSpecModel) -> dict[str, str]:
    """Decode the string points of the common model from the raw words."""
    data_start = model.address + 2
    decoded: dict[str, str] = {}
    for offset, count, name in COMMON_FIELDS:
        registers = [words[data_start + offset + index] for index in range(count)]
        decoded[name] = decode_string(registers).strip("\x00 ")
    return decoded


def hex_dump(words: dict[int, int], address: int, count: int) -> str:
    """Render ``count`` registers from ``address`` as lines of eight hex words."""
    lines = []
    for start in range(address, address + count, 8):
        row = [
            f"{words[a]:04x}" for a in range(start, min(start + 8, address + count)) if a in words
        ]
        lines.append(f"  {start:5d}: {' '.join(row)}")
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    """Scan the device and write the snapshot."""
    connection = ModbusConnection(
        ModbusTcpParams(host=args.host, port=args.port), timeout=args.timeout
    )
    bases = (args.base,) if args.base is not None else DEFAULT_BASES
    try:
        unit = connection.for_unit(args.unit)
        base, chain = await find_chain(unit, bases)
        print(f"SunSpec marker at base {base}, unit {args.unit}, {len(chain)} models\n")
        print(f"{'model':>7}  {'address':>7}  {'length':>6}  {'span':>5}")
        for model in chain:
            print(f"{model.model_id:>7}  {model.address:>7}  {model.length:>6}  {model.span:>5}")

        registers: dict[int, int] = {}
        registers.update(await read_block(unit, base, 2, args.chunk))
        for model in chain:
            registers.update(await read_block(unit, model.address, model.span, args.chunk))
        end_marker = chain[-1].address + chain[-1].span if chain else base + 2
        registers.update(await read_block(unit, end_marker, 2, args.chunk))
    except (ModbusError, SunSpecError) as err:
        print(f"Scan failed: {err}", file=sys.stderr)
        return 1
    finally:
        await connection.close()

    common = next((m for m in chain if m.model_id == COMMON_MODEL_ID), None)
    if common is not None:
        print("\nCommon model:")
        for name, value in decode_common(registers, common).items():
            print(f"  {name:<4} {value}")

    vendor = next((m for m in chain if m.model_id == ABB_VENDOR_MODEL_ID), None)
    if vendor is not None:
        print(
            f"\nABB vendor model {ABB_VENDOR_MODEL_ID}: header at {vendor.address},"
            f" length {vendor.length} (2013 sheet says 124)"
        )
        print(hex_dump(registers, vendor.address, vendor.span))

    snapshot: dict[str, Any] = {
        "host": args.host,
        "port": args.port,
        "unit_id": args.unit,
        "base_address": base,
        "models": [
            {"model_id": m.model_id, "address": m.address, "length": m.length} for m in chain
        ],
        "holding": {str(address): value for address, value in sorted(registers.items())},
    }
    args.out.write_text(json.dumps(snapshot, indent=2))
    print(f"\nWrote {len(registers)} registers to {args.out}")
    print("The snapshot contains the device serial number; review it before sharing.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run the scan."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host", help="IP address or host name of the inverter or datalogger")
    parser.add_argument("--port", type=int, default=502, help="Modbus TCP port (default 502)")
    parser.add_argument("--unit", type=int, default=2, help="Modbus unit ID (default 2)")
    parser.add_argument(
        "--base",
        type=int,
        default=None,
        help="SunSpec base address; tries 0 then 40000 when omitted",
    )
    parser.add_argument(
        "--chunk", type=int, default=DEFAULT_CHUNK, help="Registers per read (default 60)"
    )
    parser.add_argument("--timeout", type=float, default=5.0, help="Per-request timeout in seconds")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("sunspec_snapshot.json"),
        help="Snapshot file to write (default sunspec_snapshot.json)",
    )
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
