import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from bleak import BleakClient, BleakScanner


REPORT_UUID = "0000FFE1-0000-1000-8000-00805F9B34FB"
COMMAND_UUID = "0000FFE2-0000-1000-8000-00805F9B34FB"


def packet_crc(payload_without_header_and_crc: bytes) -> int:
    return (sum(payload_without_header_and_crc) & 0xFF) ^ 0x44


def _u24_be(data: bytes, offset: int) -> int:
    return (data[offset] << 16) | (data[offset + 1] << 8) | data[offset + 2]


@dataclass
class DL24Reading:
    device_type: int
    voltage: float
    current: float
    power: float
    temperature: int
    crc_ok: bool


class DL24Commands:
    ENTER = 0x32
    PLUS = 0x11
    MINUS = 0x12


def parse_report(frame: bytes) -> Optional[DL24Reading]:
    if len(frame) != 36:
        return None
    if frame[0] != 0xFF or frame[1] != 0x55 or frame[2] != 0x01:
        return None

    remote_crc = frame[-1]
    local_crc = packet_crc(frame[2:-1])
    crc_ok = remote_crc == local_crc

    device_type = frame[3]
    if device_type in (0x01, 0x02):
        voltage = _u24_be(frame, 4) * 0.1
        current = _u24_be(frame, 7) * 0.001
        temperature = (frame[24] << 8) | frame[25]
    elif device_type == 0x03:
        voltage = _u24_be(frame, 4) * 0.01
        current = _u24_be(frame, 7) * 0.01
        temperature = (frame[21] << 8) | frame[22]
    else:
        return None

    return DL24Reading(
        device_type=device_type,
        voltage=voltage,
        current=current,
        power=voltage * current,
        temperature=temperature,
        crc_ok=crc_ok,
    )


class _FrameCollector:
    def __init__(self):
        self.buffer = bytearray()
        self.latest: Optional[DL24Reading] = None

    def feed(self, payload: bytes):
        if len(payload) >= 2 and payload[0] == 0xFF and payload[1] == 0x55:
            self.buffer = bytearray(payload)
        else:
            self.buffer.extend(payload)

        while True:
            if len(self.buffer) >= 8 and self.buffer[0] == 0xFF and self.buffer[1] == 0x55 and self.buffer[2] == 0x02:
                self.buffer = self.buffer[8:]
                continue

            if len(self.buffer) >= 36 and self.buffer[0] == 0xFF and self.buffer[1] == 0x55 and self.buffer[2] == 0x01:
                frame = bytes(self.buffer[:36])
                reading = parse_report(frame)
                if reading is not None:
                    self.latest = reading
                self.buffer = self.buffer[36:]
                continue

            break


class DL24Client:
    def __init__(self, address: str, default_device_type: int = 0x02):
        self.address = address
        self.default_device_type = default_device_type
        self._client: Optional[BleakClient] = None
        self._collector = _FrameCollector()

    @staticmethod
    async def scan(timeout: float = 8.0) -> list[tuple[str, str]]:
        devices = await BleakScanner.discover(timeout=timeout)
        found: list[tuple[str, str]] = []
        for ble_device in devices:
            name = ble_device.name or ""
            if "BLE" in name.upper() or "ATORCH" in name.upper() or "DL24" in name.upper():
                found.append((ble_device.address, name))
        return found

    async def connect(self):
        self._client = BleakClient(self.address)
        await self._client.connect()
        await self._client.start_notify(REPORT_UUID, self._on_notify)

    async def close(self):
        if self._client is None:
            return
        try:
            await self._client.stop_notify(REPORT_UUID)
        except Exception:
            pass
        await self._client.disconnect()
        self._client = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    def _on_notify(self, _: int, payload: bytearray):
        self._collector.feed(bytes(payload))

    @property
    def latest(self) -> Optional[DL24Reading]:
        return self._collector.latest

    def _build_packet(self, command: int, value: int, device_type: Optional[int] = None) -> bytes:
        dt = self.default_device_type if device_type is None else device_type
        frame = bytearray(10)
        frame[0] = 0xFF
        frame[1] = 0x55
        frame[2] = 0x11
        frame[3] = dt & 0xFF
        frame[4] = command & 0xFF
        frame[5] = (value >> 24) & 0xFF
        frame[6] = (value >> 16) & 0xFF
        frame[7] = (value >> 8) & 0xFF
        frame[8] = value & 0xFF
        frame[9] = packet_crc(frame[2:9])
        return bytes(frame)

    async def send_command(self, command: int, value: int = 0, device_type: Optional[int] = None):
        if self._client is None:
            raise RuntimeError("DL24Client is not connected")
        packet = self._build_packet(command, value, device_type)
        await self._client.write_gatt_char(COMMAND_UUID, packet, response=False)

    async def toggle_output(self):
        await self.send_command(DL24Commands.ENTER, 0)

    async def step_up(self, steps: int = 1):
        for _ in range(max(1, steps)):
            await self.send_command(DL24Commands.PLUS, 0)
            await asyncio.sleep(0.08)

    async def step_down(self, steps: int = 1):
        for _ in range(max(1, steps)):
            await self.send_command(DL24Commands.MINUS, 0)
            await asyncio.sleep(0.08)

    async def monitor(
        self,
        interval: float,
        callback: Callable[[DL24Reading], Awaitable[None] | None],
        seconds: float = 0.0,
    ):
        start = asyncio.get_event_loop().time()
        while True:
            now = asyncio.get_event_loop().time()
            if seconds > 0 and now - start >= seconds:
                return
            reading = self.latest
            if reading is not None:
                maybe = callback(reading)
                if asyncio.iscoroutine(maybe):
                    await maybe
            await asyncio.sleep(interval)
