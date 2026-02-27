#!/usr/bin/env python3

import argparse
import asyncio
from dataclasses import dataclass
from time import monotonic

from dl24p_control import DL24Client


@dataclass
class MpptState:
    direction: int = 1
    last_power: float = 0.0
    initialized: bool = False


async def run_mppt(address: str, interval: float, seconds: float, deadband_w: float):
    state = MpptState()

    async with DL24Client(address) as client:
        print("Forbundet. Starter MPPT-CC loop ...")
        start_t = monotonic()

        async def on_reading(reading):
            elapsed = monotonic() - start_t
            print(
                f"t={elapsed:6.2f}s V={reading.voltage:6.3f} A={reading.current:6.3f} "
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


async def main_async():
    parser = argparse.ArgumentParser(description="Simpel MPPT-lignende regulering i CC mode")
    parser.add_argument("--address", required=True)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--deadband-w", type=float, default=0.05)
    args = parser.parse_args()

    await run_mppt(args.address, args.interval, args.seconds, args.deadband_w)


if __name__ == "__main__":
    asyncio.run(main_async())
