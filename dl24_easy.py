#!/usr/bin/env python3

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from dl24p_control import DL24Client


CONFIG_PATH = Path.home() / ".dl24p_easy.json"


@dataclass
class MpptState:
    direction: int = 1
    last_power: float = 0.0
    initialized: bool = False


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


async def scan_devices(timeout: float = 8.0):
    devices = await DL24Client.scan(timeout=timeout)
    if not devices:
        print("Ingen DL24 BLE enheder fundet")
        return []
    print("Fundne enheder:")
    for idx, (address, name) in enumerate(devices, start=1):
        print(f"  {idx}. {address}  name={name}")
    return devices


async def run_monitor(address: str, interval: float, seconds: float, csv_path: str | None = None):
    csv_file = None
    if csv_path:
        csv_file = Path(csv_path)
        if not csv_file.exists():
            csv_file.write_text("t_s,voltage_v,current_a,power_w,temp_c,crc_ok\n", encoding="utf-8")

    async with DL24Client(address) as client:
        print(f"Forbundet til {address}")
        start = monotonic()

        async def on_reading(reading):
            t = monotonic() - start
            line = (
                f"t={t:7.2f}s V={reading.voltage:6.3f} A={reading.current:6.3f} "
                f"W={reading.power:7.3f} T={reading.temperature:2d}C "
                f"crc={'ok' if reading.crc_ok else 'mismatch'}"
            )
            print(line)
            if csv_file is not None:
                with csv_file.open("a", encoding="utf-8") as f:
                    f.write(
                        f"{t:.3f},{reading.voltage:.6f},{reading.current:.6f},"
                        f"{reading.power:.6f},{reading.temperature},{int(reading.crc_ok)}\n"
                    )

        await client.monitor(interval=interval, callback=on_reading, seconds=seconds)


async def run_mppt(address: str, interval: float, seconds: float, deadband_w: float):
    state = MpptState()

    async with DL24Client(address) as client:
        print(f"Forbundet til {address}")
        print("Starter MPPT-CC (perturb & observe)")
        start_t = monotonic()

        async def on_reading(reading):
            elapsed = monotonic() - start_t
            print(
                f"t={elapsed:7.2f}s V={reading.voltage:6.3f} A={reading.current:6.3f} "
                f"W={reading.power:7.3f} dir={'+' if state.direction > 0 else '-'}"
            )

            if not state.initialized:
                state.last_power = reading.power
                state.initialized = True
                return

            delta = reading.power - state.last_power
            if abs(delta) <= deadband_w:
                state.last_power = reading.power
                return

            if delta < 0:
                state.direction *= -1

            if state.direction > 0:
                await client.step_up(1)
            else:
                await client.step_down(1)

            state.last_power = reading.power

        await client.monitor(interval=interval, callback=on_reading, seconds=seconds)


async def run_toggle(address: str):
    async with DL24Client(address) as client:
        await client.toggle_output()
    print("Toggle sendt")


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    if value == "" and default is not None:
        return default
    return value


async def menu_mode():
    cfg = load_config()
    address = cfg.get("address", "")

    while True:
        print("\n=== DL24 Easy App ===")
        print(f"Aktiv adresse: {address or '(ikke sat)'}")
        print("1) Scan enheder")
        print("2) Sæt adresse")
        print("3) Quick ON/OFF (toggle)")
        print("4) Live monitor")
        print("5) MPPT-CC")
        print("6) Afslut")

        choice = ask("Vælg", "1")

        if choice == "1":
            devices = await scan_devices(timeout=10.0)
            if devices:
                pick = ask("Brug enhed nr (0=nej)", "0")
                try:
                    index = int(pick)
                except ValueError:
                    index = 0
                if 1 <= index <= len(devices):
                    address = devices[index - 1][0]
                    cfg["address"] = address
                    save_config(cfg)
                    print(f"Adresse gemt: {address}")

        elif choice == "2":
            address = ask("Indtast BLE adresse")
            cfg["address"] = address
            save_config(cfg)
            print(f"Adresse gemt: {address}")

        elif choice == "3":
            if not address:
                print("Sæt adresse først")
                continue
            await run_toggle(address)

        elif choice == "4":
            if not address:
                print("Sæt adresse først")
                continue
            interval = float(ask("Interval sek", "0.5"))
            seconds = float(ask("Sekunder (0=indtil Ctrl+C)", "30"))
            csv_path = ask("CSV fil (tom=ingen)", "")
            try:
                await run_monitor(address, interval=interval, seconds=seconds, csv_path=csv_path or None)
            except KeyboardInterrupt:
                print("Monitor stoppet")

        elif choice == "5":
            if not address:
                print("Sæt adresse først")
                continue
            interval = float(ask("Interval sek", "0.5"))
            seconds = float(ask("Sekunder", "60"))
            deadband = float(ask("Deadband watt", "0.05"))
            try:
                await run_mppt(address, interval=interval, seconds=seconds, deadband_w=deadband)
            except KeyboardInterrupt:
                print("MPPT stoppet")

        elif choice == "6":
            print("Farvel")
            return
        else:
            print("Ugyldigt valg")


async def cli_mode(args):
    if args.mode == "scan":
        await scan_devices(args.timeout)
    elif args.mode == "toggle":
        await run_toggle(args.address)
    elif args.mode == "monitor":
        await run_monitor(args.address, args.interval, args.seconds, args.csv)
    elif args.mode == "mppt":
        await run_mppt(args.address, args.interval, args.seconds, args.deadband_w)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DL24 Easy App")
    sub = parser.add_subparsers(dest="mode")

    scan = sub.add_parser("scan", help="Scan DL24 BLE enheder")
    scan.add_argument("--timeout", type=float, default=8.0)

    toggle = sub.add_parser("toggle", help="Quick ON/OFF")
    toggle.add_argument("--address", required=True)

    monitor = sub.add_parser("monitor", help="Live monitor")
    monitor.add_argument("--address", required=True)
    monitor.add_argument("--interval", type=float, default=0.5)
    monitor.add_argument("--seconds", type=float, default=30.0)
    monitor.add_argument("--csv", default=None)

    mppt = sub.add_parser("mppt", help="MPPT-CC mode")
    mppt.add_argument("--address", required=True)
    mppt.add_argument("--interval", type=float, default=0.5)
    mppt.add_argument("--seconds", type=float, default=60.0)
    mppt.add_argument("--deadband-w", type=float, default=0.05)

    return parser


async def main_async():
    parser = build_parser()
    args = parser.parse_args()
    if args.mode is None:
        await menu_mode()
    else:
        await cli_mode(args)


if __name__ == "__main__":
    asyncio.run(main_async())
