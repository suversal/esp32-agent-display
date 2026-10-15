"""Capture device output without intentionally resetting the board."""
import argparse
from pathlib import Path
import time

import serial
from esptool.reset import HardReset

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="/dev/cu.usbmodem1101")
parser.add_argument("--seconds", type=float, default=15)
parser.add_argument("--reset", action="store_true", help="Restart the board to capture boot output")
parser.add_argument("--output", type=Path, default=Path("logs/hello-screen-runtime.log"))
args = parser.parse_args()

connection = serial.Serial(port=None, baudrate=115200, timeout=0.2)
connection.dtr = False
connection.rts = False
connection.port = args.port
connection.open()
if args.reset:
    HardReset(connection, uses_usb=True)()

data = bytearray()
try:
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        data.extend(connection.read(connection.in_waiting or 1))
finally:
    connection.close()

args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_bytes(data)
print(data.decode("utf-8", errors="replace"))
