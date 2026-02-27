#!/usr/bin/env python3

import asyncio
import csv
import json
import threading
import time
import webbrowser
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request

from dl24p_control import DL24Client


app = Flask(__name__)


class ControllerState:
    def __init__(self):
        self.address = ""
        self.mode = "idle"
        self.running = False
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.last_reading = None
        self.log_lines: list[str] = []
        self.lock = threading.Lock()
        self.start_ts = 0.0
        self.chart_points: list[dict] = []
        self.max_points = 500

    def log(self, message: str):
        with self.lock:
            stamp = datetime.now().strftime("%H:%M:%S")
            self.log_lines.append(f"[{stamp}] {message}")
            self.log_lines = self.log_lines[-200:]

    def set_reading(self, reading):
        with self.lock:
            self.last_reading = reading
            t_s = time.time() - self.start_ts if self.start_ts else 0.0
            self.chart_points.append(
                {
                    "t": t_s,
                    "v": reading.voltage,
                    "a": reading.current,
                    "w": reading.power,
                    "temp": reading.temperature,
                    "crc_ok": reading.crc_ok,
                }
            )
            if len(self.chart_points) > self.max_points:
                self.chart_points = self.chart_points[-self.max_points :]


STATE = ControllerState()


def stop_worker():
    with STATE.lock:
        if STATE.worker_thread and STATE.worker_thread.is_alive():
            STATE.stop_event.set()
    thread = STATE.worker_thread
    if thread and thread.is_alive():
        thread.join(timeout=2.0)
    with STATE.lock:
        STATE.running = False
        STATE.mode = "idle"
        STATE.worker_thread = None


def start_worker(name: str, fn):
    stop_worker()
    STATE.stop_event.clear()
    with STATE.lock:
        STATE.mode = name
        STATE.running = True
        STATE.start_ts = time.time()
        STATE.chart_points = []
    thread = threading.Thread(target=fn, daemon=True)
    with STATE.lock:
        STATE.worker_thread = thread
    thread.start()


async def monitor_loop(address: str, interval: float, csv_path: str | None = None):
    csv_file = None
    if csv_path:
        csv_file = Path(csv_path).expanduser()
        if not csv_file.is_absolute():
            csv_file = Path.cwd() / csv_file

    async with DL24Client(address) as client:
        STATE.log(f"Forbundet til {address}")
        if csv_file and not csv_file.exists():
            with csv_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["t_s", "voltage_v", "current_a", "power_w", "temp_c", "crc_ok"])

        while not STATE.stop_event.is_set():
            reading = client.latest
            if reading is not None:
                STATE.set_reading(reading)
                if csv_file:
                    t_s = time.time() - STATE.start_ts
                    with csv_file.open("a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow([f"{t_s:.3f}", reading.voltage, reading.current, reading.power, reading.temperature, int(reading.crc_ok)])
            await asyncio.sleep(interval)


async def mppt_loop(address: str, interval: float, deadband_w: float):
    direction = 1
    last_power = 0.0
    initialized = False

    async with DL24Client(address) as client:
        STATE.log(f"Forbundet til {address}")
        while not STATE.stop_event.is_set():
            reading = client.latest
            if reading is not None:
                STATE.set_reading(reading)

                if not initialized:
                    initialized = True
                    last_power = reading.power
                else:
                    delta = reading.power - last_power
                    if abs(delta) > deadband_w:
                        if delta < 0:
                            direction *= -1
                        if direction > 0:
                            await client.step_up(1)
                            STATE.log("MPPT: step +")
                        else:
                            await client.step_down(1)
                            STATE.log("MPPT: step -")
                    last_power = reading.power
            await asyncio.sleep(interval)


def run_async(coro):
    try:
        asyncio.run(coro)
    except Exception as exc:
        STATE.log(f"Fejl: {exc}")
    finally:
        with STATE.lock:
            STATE.running = False
            STATE.mode = "idle"


@app.get("/")
def index():
    return """
<!doctype html>
<html>
<head>
  <meta charset='utf-8'>
  <title>DL24P Controller</title>
  <script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
  <style>
    body{font-family:Arial,sans-serif;margin:20px;max-width:1000px}
    .row{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
    input,button{padding:8px}
    #log{height:180px;overflow:auto;background:#111;color:#ddd;padding:10px;border-radius:6px;white-space:pre-wrap}
    .card{padding:12px;border:1px solid #ddd;border-radius:8px;margin:10px 0}
  </style>
</head>
<body>
  <h2>DL24P Mac Controller (Web GUI)</h2>

  <div class='card'>
    <div class='row'>
      <button onclick='scan()'>Scan</button>
      <span id='scanResult'></span>
    </div>
    <div class='row'>
      <label>Address</label>
      <input id='address' size='44' placeholder='BLE address'>
      <label>Interval</label>
      <input id='interval' value='0.5' size='6'>
      <label>Deadband W</label>
      <input id='deadband' value='0.05' size='6'>
      <label>CSV</label>
      <input id='csv' placeholder='fx dl24_log.csv' size='20'>
    </div>
    <div class='row'>
      <button onclick='postAction("toggle")'>Quick ON/OFF</button>
      <button onclick='postAction("monitor")'>Start Monitor</button>
      <button onclick='postAction("mppt")'>Start MPPT</button>
      <button onclick='postAction("stop")'>Stop</button>
      <strong>Mode: <span id='mode'>idle</span></strong>
    </div>
  </div>

  <div class='card'>
    <div>V: <span id='v'>-</span> | A: <span id='a'>-</span> | W: <span id='w'>-</span> | T: <span id='t'>-</span></div>
    <canvas id='chart' height='120'></canvas>
  </div>

  <div class='card'><div id='log'></div></div>

<script>
let chart;
function initChart(){
  const ctx=document.getElementById('chart');
  chart=new Chart(ctx,{type:'line',data:{labels:[],datasets:[
    {label:'Volt',data:[],borderColor:'#1976d2',yAxisID:'y1'},
    {label:'Amp',data:[],borderColor:'#ef6c00',yAxisID:'y2'}
  ]},options:{animation:false,scales:{y1:{position:'left'},y2:{position:'right'}}}});
}
async function scan(){
  const r=await fetch('/api/scan'); const j=await r.json();
  document.getElementById('scanResult').textContent = JSON.stringify(j.devices);
  if(j.devices.length>0){document.getElementById('address').value=j.devices[0][0];}
}
async function postAction(mode){
  const body={
    address:document.getElementById('address').value.trim(),
    interval:parseFloat(document.getElementById('interval').value||'0.5'),
    deadband_w:parseFloat(document.getElementById('deadband').value||'0.05'),
    csv:document.getElementById('csv').value.trim(),
  };
  await fetch('/api/'+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}
async function refresh(){
  const r=await fetch('/api/status'); const s=await r.json();
  document.getElementById('mode').textContent=s.mode;
  if(s.reading){
    document.getElementById('v').textContent=s.reading.voltage.toFixed(3);
    document.getElementById('a').textContent=s.reading.current.toFixed(3);
    document.getElementById('w').textContent=s.reading.power.toFixed(3);
    document.getElementById('t').textContent=s.reading.temperature;
  }
  chart.data.labels=s.chart.map(p=>p.t.toFixed(1));
  chart.data.datasets[0].data=s.chart.map(p=>p.v);
  chart.data.datasets[1].data=s.chart.map(p=>p.a);
  chart.update();
  document.getElementById('log').textContent=s.log.join('\n');
  document.getElementById('log').scrollTop=999999;
}
initChart();
setInterval(refresh,500);
</script>
</body>
</html>
"""


@app.get("/api/scan")
def api_scan():
    devices = asyncio.run(DL24Client.scan(timeout=8.0))
    if devices:
        STATE.address = devices[0][0]
    return jsonify({"devices": devices})


@app.get("/api/status")
def api_status():
    with STATE.lock:
        reading = asdict(STATE.last_reading) if STATE.last_reading else None
        return jsonify(
            {
                "address": STATE.address,
                "mode": STATE.mode,
                "running": STATE.running,
                "reading": reading,
                "log": STATE.log_lines,
                "chart": STATE.chart_points,
            }
        )


@app.post("/api/toggle")
def api_toggle():
    data = request.get_json(silent=True) or {}
    address = (data.get("address") or STATE.address or "").strip()
    if not address:
        return jsonify({"ok": False, "error": "address missing"}), 400

    def worker():
        async def run():
            async with DL24Client(address) as client:
                await client.toggle_output()
                STATE.log("Toggle sendt")

        run_async(run())

    start_worker("toggle", worker)
    return jsonify({"ok": True})


@app.post("/api/monitor")
def api_monitor():
    data = request.get_json(silent=True) or {}
    address = (data.get("address") or STATE.address or "").strip()
    interval = float(data.get("interval", 0.5))
    csv_path = (data.get("csv") or "").strip() or None
    if not address:
        return jsonify({"ok": False, "error": "address missing"}), 400

    def worker():
        run_async(monitor_loop(address, interval, csv_path))

    start_worker("monitor", worker)
    return jsonify({"ok": True})


@app.post("/api/mppt")
def api_mppt():
    data = request.get_json(silent=True) or {}
    address = (data.get("address") or STATE.address or "").strip()
    interval = float(data.get("interval", 0.5))
    deadband_w = float(data.get("deadband_w", 0.05))
    if not address:
        return jsonify({"ok": False, "error": "address missing"}), 400

    def worker():
        run_async(mppt_loop(address, interval, deadband_w))

    start_worker("mppt", worker)
    return jsonify({"ok": True})


@app.post("/api/stop")
def api_stop():
    stop_worker()
    STATE.log("Stoppet")
    return jsonify({"ok": True})


def main():
    url = "http://127.0.0.1:8765"
    print(f"Starter DL24 web GUI på {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    app.run(host="127.0.0.1", port=8765, debug=False)


if __name__ == "__main__":
    main()
