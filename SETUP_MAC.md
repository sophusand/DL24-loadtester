# SETUP (macOS)

## 1) Installer

```bash
cd /Users/sophusandreassen/Desktop/dl24
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Find DL24P

```bash
python dl24_cli.py scan --timeout 10
```

## 3) Læs live data

Nem menu-app (anbefalet):

```bash
python dl24_easy.py
```

GUI app (mest brugervenlig):

```bash
python dl24_gui.py
```

Direkte kommando:

```bash
python dl24_cli.py monitor --address AA:BB:CC:DD:EE:FF --interval 0.5
```

## 4) Hurtig styring

```bash
python dl24_cli.py quick-on --address AA:BB:CC:DD:EE:FF
python dl24_cli.py quick-off --address AA:BB:CC:DD:EE:FF
```

## 5) MPPT-CC eksempel

```bash
python examples_mppt_cc.py --address AA:BB:CC:DD:EE:FF --interval 0.5 --seconds 60
```
