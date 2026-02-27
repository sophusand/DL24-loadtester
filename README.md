# DL24P Control Kit (macOS)

Ren og genbrugelig mappe til styring af Atorch DL24P via BLE.

## Indhold

- `dl24p_control/` – genbrugeligt Python library
- `dl24_cli.py` – nem CLI (`scan`, `monitor`, `quick-on`, `quick-off`)
- `examples_mppt_cc.py` – eksempel på MPPT-lignende CC-regulering
- `requirements.txt`

## Quickstart

```bash
cd /Users/sophusandreassen/Desktop/dl24
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Scan efter enhed:

```bash
python dl24_cli.py scan --timeout 10
```

Live data hver 0.5 s:

```bash
python dl24_cli.py monitor --address AA:BB:CC:DD:EE:FF --interval 0.5
```

Hurtig toggle:

```bash
python dl24_cli.py quick-on --address AA:BB:CC:DD:EE:FF
python dl24_cli.py quick-off --address AA:BB:CC:DD:EE:FF
```

MPPT-CC eksempel:

```bash
python examples_mppt_cc.py --address AA:BB:CC:DD:EE:FF --interval 0.5 --seconds 60
```

## Brug library i egne projekter

```python
import asyncio
from dl24p_control import DL24Client

async def main():
    async with DL24Client("AA:BB:CC:DD:EE:FF") as dl24:
        await dl24.toggle_output()
        await dl24.step_up(2)

asyncio.run(main())
```
