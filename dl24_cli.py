#!/usr/bin/env python3

import argparse
import asyncio
from time import monotonic

from dl24p_control import DL24Client


async def run_scan(timeout: float):
    devices = await DL24Client.scan(timeout=timeout)
    if not devices:
        print("Ingen DL24 BLE enheder fundet")
        return
    for address, name in devices:
        print(f"- {address}  name={name}")


async def run_monitor(address: str, interval: float, seconds: float):
    async with DL24Client(address) as client:
        print(f"Forbundet til {address}")
        start = monotonic()

        async def on_reading(reading):
            t = monotonic() - start
            print(
                f"t={t:6.2f}s V={reading.voltage:6.3f} A={reading.current:6.3f} "
                f"W={reading.power:7.3f} T={reading.temperature:2d}C "
                f"crc={'ok' if reading.crc_ok else 'mismatch'}"
            )

        await client.monitor(interval=interval, callback=on_reading, seconds=seconds)


async def run_quick_toggle(address: str):
    async with DL24Client(address) as client:
        await client.toggle_output()
    print("Toggle sendt")


async def main_async():
    parser = argparse.ArgumentParser(description="DL24P BLE CLI")
    sub = parser.add_subparsers(dest="mode", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--timeout", type=float, default=8.0)

    monitor = sub.add_parser("monitor")
    monitor.add_argument("--address", required=True)
    monitor.add_argument("--interval", type=float, default=0.5)
    monitor.add_argument("--seconds", type=float, default=0.0, help="0 = indtil Ctrl+C")

    on = sub.add_parser("quick-on")
    on.add_argument("--address", required=True)

    off = sub.add_parser("quick-off")
    off.add_argument("--address", required=True)

    args = parser.parse_args()

    if args.mode == "scan":
        await run_scan(args.timeout)
        return
    if args.mode == "monitor":
        await run_monitor(args.address, args.interval, args.seconds)
        return
    await run_quick_toggle(args.address)


if __name__ == "__main__":
    asyncio.run(main_async())
