"""Capture private serial output; print only the status display's safe diagnostics."""
import argparse
from pathlib import Path
import re
import time
import serial
from esptool.reset import HardReset

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="/dev/cu.usbmodem1101")
parser.add_argument("--seconds", type=float, default=25)
parser.add_argument("--reset", action="store_true")
parser.add_argument("--output", type=Path, default=Path("logs/agent-display-runtime.log"))
parser.add_argument("--stop-file", type=Path, help="Stop when this task-owned marker exists")
args = parser.parse_args()
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.touch(mode=0o600)
args.output.chmod(0o600)
connection = serial.Serial(port=None, baudrate=115200, timeout=0.2)
connection.dtr = False
connection.rts = False
connection.port = args.port
connection.open()
if args.reset:
    HardReset(connection, uses_usb=True)()
data = bytearray()
pending = bytearray()
safe = re.compile(r"(DISPLAY_READY|NETWORK_INIT_FAILED|WIFI_(CONFIG_UNAVAILABLE|CONNECTED|DISCONNECTED|CONNECT_ATTEMPT)|BRIDGE_(CONNECTED|DISCONNECTED|ADDRESS_RESOLVED)|SNAPSHOT_(READY|FRAME_REJECTED|JSON_REJECTED)|HELLO_SENT|ACK_(SENT|QUEUE_FULL)|SOUND_(REQUEST|STARTED|RESULT|SKIPPED|TEST)|AUDIO_(READY|INIT_FAILED|WRITE_FAILED|START_FAILED|MUTE)|Guru Meditation|Backtrace:|waiting for download|rst:0x)")
try:
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline and not (args.stop_file and args.stop_file.exists()):
        received = connection.read(connection.in_waiting or 1)
        data.extend(received)
        pending.extend(received)
        while b"\n" in pending:
            line, _, rest = pending.partition(b"\n")
            pending = bytearray(rest)
            text = line.decode("utf-8", errors="replace")
            if safe.search(text):
                print(text, flush=True)
finally:
    connection.close()
args.output.write_bytes(data)
if pending and safe.search(pending.decode("utf-8", errors="replace")):
    print(pending.decode("utf-8", errors="replace"))
print(f"SERIAL_CAPTURE_OK bytes={len(data)} file={args.output}")
