# DL24P Control Kit (macOS)

Ren og genbrugelig mappe til styring af Atorch DL24P via BLE.

## Indhold

- `dl24p_control/` – genbrugeligt Python library
- `dl24_easy.py` – nem menu-app til daglig brug (scan, monitor, MPPT)
- `dl24_gui.py` – GUI app med knapper til scan/monitor/toggle/MPPT
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

## Nem app (anbefalet)

Start menu-app:

```bash
python dl24_easy.py
```

Her kan du vælge:
- scan og gem adresse
- quick on/off
- live monitor (med valgfri CSV logging)
- MPPT-CC med justerbare parametre

## GUI app (mest brugervenlig)

```bash
python dl24_gui.py
```

Brug knapperne i vinduet:
- `Scan` finder DL24 og sætter adresse
- `Quick ON/OFF` toggler output
- `Start Monitor` læser live data
- `Start MPPT` kører MPPT-CC loop
- `Stop` stopper monitor/MPPT
- `CSV log` gemmer live data til fil
- Live graf opdateres i vinduet (Volt/Amp)

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
