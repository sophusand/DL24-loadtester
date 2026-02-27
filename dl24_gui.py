#!/usr/bin/env python3

import asyncio
import csv
import queue
import threading
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from dl24p_control import DL24Client


@dataclass
class MpptState:
    direction: int = 1
    last_power: float = 0.0
    initialized: bool = False


class DL24GuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("DL24P Mac Controller")
        self.root.geometry("840x620")

        self.event_queue: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.stop_event = threading.Event()

        self.address_var = tk.StringVar(value="")
        self.interval_var = tk.StringVar(value="0.5")
        self.deadband_var = tk.StringVar(value="0.05")
        self.mode_var = tk.StringVar(value="Idle")
        self.csv_enabled_var = tk.BooleanVar(value=False)
        self.csv_file_var = tk.StringVar(value="")

        self.voltage_var = tk.StringVar(value="-")
        self.current_var = tk.StringVar(value="-")
        self.power_var = tk.StringVar(value="-")
        self.temp_var = tk.StringVar(value="-")

        self.t_points = deque(maxlen=300)
        self.v_points = deque(maxlen=300)
        self.a_points = deque(maxlen=300)
        self.p_points = deque(maxlen=300)
        self.start_time = None

        self._build_ui()
        self.root.after(150, self._drain_events)

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Adresse:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.address_var, width=42).grid(row=0, column=1, sticky="we", padx=8)
        ttk.Button(top, text="Scan", command=self.scan_devices).grid(row=0, column=2, padx=4)
        ttk.Button(top, text="Quick ON/OFF", command=self.quick_toggle).grid(row=0, column=3, padx=4)

        ttk.Label(top, text="Interval (s):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(top, textvariable=self.interval_var, width=10).grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Label(top, text="MPPT deadband (W):").grid(row=1, column=2, sticky="e", pady=(8, 0))
        ttk.Entry(top, textvariable=self.deadband_var, width=10).grid(row=1, column=3, sticky="w", pady=(8, 0))

        controls = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="Start Monitor", command=self.start_monitor).pack(side=tk.LEFT, padx=4)
        ttk.Button(controls, text="Start MPPT", command=self.start_mppt).pack(side=tk.LEFT, padx=4)
        ttk.Button(controls, text="Stop", command=self.stop_worker).pack(side=tk.LEFT, padx=4)
        ttk.Label(controls, text="Mode:").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Label(controls, textvariable=self.mode_var).pack(side=tk.LEFT)

        csv_controls = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        csv_controls.pack(fill=tk.X)
        ttk.Checkbutton(csv_controls, text="CSV log", variable=self.csv_enabled_var).pack(side=tk.LEFT)
        ttk.Entry(csv_controls, textvariable=self.csv_file_var, width=45).pack(side=tk.LEFT, padx=6)
        ttk.Button(csv_controls, text="Auto filnavn", command=self.set_auto_csv_name).pack(side=tk.LEFT)

        readings = ttk.LabelFrame(self.root, text="Live data", padding=10)
        readings.pack(fill=tk.X, padx=10, pady=6)

        self._reading_line(readings, 0, "Voltage (V)", self.voltage_var)
        self._reading_line(readings, 1, "Current (A)", self.current_var)
        self._reading_line(readings, 2, "Power (W)", self.power_var)
        self._reading_line(readings, 3, "Temp (C)", self.temp_var)

        graph_frame = ttk.LabelFrame(self.root, text="Live graf", padding=8)
        graph_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        self.fig = Figure(figsize=(7, 3.2), dpi=100)
        self.ax_v = self.fig.add_subplot(211)
        self.ax_a = self.fig.add_subplot(212)
        self.ax_v.set_ylabel("Volt")
        self.ax_a.set_ylabel("Amp")
        self.ax_a.set_xlabel("Tid (s)")
        self.ax_v.grid(True, alpha=0.3)
        self.ax_a.grid(True, alpha=0.3)

        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        log_frame = ttk.LabelFrame(self.root, text="Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 10))

        self.log_text = tk.Text(log_frame, height=18, wrap="word")
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _reading_line(self, parent: ttk.LabelFrame, row: int, name: str, value_var: tk.StringVar):
        ttk.Label(parent, text=name + ":", width=14).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Label(parent, textvariable=value_var, width=20).grid(row=row, column=1, sticky="w", pady=2)

    def log(self, message: str):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def _start_worker(self, target):
        self.stop_worker()
        self.stop_event.clear()
        self.start_time = None
        self.t_points.clear()
        self.v_points.clear()
        self.a_points.clear()
        self.p_points.clear()
        self._redraw_graph()
        self.worker_thread = threading.Thread(target=target, daemon=True)
        self.worker_thread.start()

    def _resolve_csv_path(self) -> Path | None:
        if not self.csv_enabled_var.get():
            return None
        raw = self.csv_file_var.get().strip()
        if raw == "":
            self.set_auto_csv_name()
            raw = self.csv_file_var.get().strip()
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path

    def _append_csv(self, t_s: float, reading):
        path = self._resolve_csv_path()
        if path is None:
            return
        file_exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["t_s", "voltage_v", "current_a", "power_w", "temp_c", "crc_ok"])
            writer.writerow([
                f"{t_s:.3f}",
                f"{reading.voltage:.6f}",
                f"{reading.current:.6f}",
                f"{reading.power:.6f}",
                reading.temperature,
                int(reading.crc_ok),
            ])

    def set_auto_csv_name(self):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_file_var.set(f"dl24_log_{stamp}.csv")

    def _redraw_graph(self):
        self.ax_v.clear()
        self.ax_a.clear()

        self.ax_v.set_ylabel("Volt")
        self.ax_a.set_ylabel("Amp")
        self.ax_a.set_xlabel("Tid (s)")
        self.ax_v.grid(True, alpha=0.3)
        self.ax_a.grid(True, alpha=0.3)

        if self.t_points:
            self.ax_v.plot(list(self.t_points), list(self.v_points), color="tab:blue")
            self.ax_a.plot(list(self.t_points), list(self.a_points), color="tab:orange")

        self.canvas.draw_idle()

    def stop_worker(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_event.set()
            self.mode_var.set("Stopping...")

    def scan_devices(self):
        def work():
            async def run():
                self.event_queue.put(("mode", "Scanning"))
                devices = await DL24Client.scan(timeout=8.0)
                self.event_queue.put(("scan", devices))
                self.event_queue.put(("mode", "Idle"))

            asyncio.run(run())

        self._start_worker(work)

    def quick_toggle(self):
        address = self.address_var.get().strip()
        if not address:
            self.log("Sæt adresse først")
            return

        def work():
            async def run():
                self.event_queue.put(("mode", "Quick toggle"))
                async with DL24Client(address) as client:
                    await client.toggle_output()
                self.event_queue.put(("log", "Toggle sendt"))
                self.event_queue.put(("mode", "Idle"))

            try:
                asyncio.run(run())
            except Exception as e:
                self.event_queue.put(("log", f"Fejl: {e}"))
                self.event_queue.put(("mode", "Idle"))

        self._start_worker(work)

    def start_monitor(self):
        address = self.address_var.get().strip()
        if not address:
            self.log("Sæt adresse først")
            return
        try:
            interval = float(self.interval_var.get())
        except ValueError:
            self.log("Interval er ugyldigt")
            return

        def work():
            async def run():
                self.event_queue.put(("mode", "Monitor"))
                async with DL24Client(address) as client:
                    while not self.stop_event.is_set():
                        reading = client.latest
                        if reading is not None:
                            self.event_queue.put(("reading", reading))
                        await asyncio.sleep(interval)
                self.event_queue.put(("mode", "Idle"))

            try:
                asyncio.run(run())
            except Exception as e:
                self.event_queue.put(("log", f"Fejl: {e}"))
                self.event_queue.put(("mode", "Idle"))

        self._start_worker(work)

    def start_mppt(self):
        address = self.address_var.get().strip()
        if not address:
            self.log("Sæt adresse først")
            return
        try:
            interval = float(self.interval_var.get())
            deadband = float(self.deadband_var.get())
        except ValueError:
            self.log("Interval/deadband er ugyldig")
            return

        def work():
            async def run():
                state = MpptState()
                self.event_queue.put(("mode", "MPPT"))
                async with DL24Client(address) as client:
                    while not self.stop_event.is_set():
                        reading = client.latest
                        if reading is not None:
                            self.event_queue.put(("reading", reading))

                            if not state.initialized:
                                state.initialized = True
                                state.last_power = reading.power
                            else:
                                delta = reading.power - state.last_power
                                if abs(delta) > deadband:
                                    if delta < 0:
                                        state.direction *= -1
                                    if state.direction > 0:
                                        await client.step_up(1)
                                        self.event_queue.put(("log", "MPPT: step +"))
                                    else:
                                        await client.step_down(1)
                                        self.event_queue.put(("log", "MPPT: step -"))
                                state.last_power = reading.power

                        await asyncio.sleep(interval)

                self.event_queue.put(("mode", "Idle"))

            try:
                asyncio.run(run())
            except Exception as e:
                self.event_queue.put(("log", f"Fejl: {e}"))
                self.event_queue.put(("mode", "Idle"))

        self._start_worker(work)

    def _drain_events(self):
        while True:
            try:
                kind, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self.log(str(payload))
            elif kind == "mode":
                self.mode_var.set(str(payload))
            elif kind == "scan":
                devices = payload
                if not devices:
                    self.log("Ingen DL24 BLE enheder fundet")
                else:
                    self.log("Fundne enheder:")
                    for i, (address, name) in enumerate(devices, start=1):
                        self.log(f"  {i}. {address}  name={name}")
                    first_address = devices[0][0]
                    self.address_var.set(first_address)
                    self.log(f"Adresse sat til: {first_address}")
            elif kind == "reading":
                reading = payload
                if self.start_time is None:
                    self.start_time = datetime.now().timestamp()
                t_s = datetime.now().timestamp() - self.start_time

                self.voltage_var.set(f"{reading.voltage:.3f}")
                self.current_var.set(f"{reading.current:.3f}")
                self.power_var.set(f"{reading.power:.3f}")
                self.temp_var.set(f"{reading.temperature}")

                self.t_points.append(t_s)
                self.v_points.append(reading.voltage)
                self.a_points.append(reading.current)
                self.p_points.append(reading.power)
                self._redraw_graph()
                try:
                    self._append_csv(t_s, reading)
                except Exception as e:
                    self.log(f"CSV fejl: {e}")

        self.root.after(150, self._drain_events)


def main():
    root = tk.Tk()
    app = DL24GuiApp(root)

    def on_close():
        app.stop_worker()
        root.after(200, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
