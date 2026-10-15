"""Measure bridge-restart recovery while keeping the USB monitor open throughout."""
import os
from datetime import datetime
from pathlib import Path
import re
import signal
import subprocess
import time
import serial
from esptool.reset import HardReset

root = Path(__file__).resolve().parents[1]
pid_text = subprocess.check_output(["lsof", "-tiTCP:8787", "-sTCP:LISTEN"], text=True).strip()
if not pid_text.isdigit():
    raise SystemExit("Expected exactly one bridge listener.")
pid = int(pid_text)
command = subprocess.check_output(["ps", "-p", pid_text, "-o", "command="], text=True)
cwd = subprocess.check_output(["lsof", "-a", "-p", pid_text, "-d", "cwd", "-Fn"], text=True)
if not command.strip().endswith(" -m bridge") or f"n{root}\n" not in cwd:
    raise SystemExit("Listener does not match this task's bridge.")
connection = serial.Serial(port=None, baudrate=115200, timeout=0.2)
connection.dtr = False
connection.rts = False
connection.port = "/dev/cu.usbmodem1101"
connection.open()
HardReset(connection, uses_usb=True)()
output = root / f"logs/agent-display-reconnect-check-{datetime.now():%Y%m%d-%H%M%S}.log"
output.touch(mode=0o600)
output.chmod(0o600)
safe = re.compile(r"agent_net: (BRIDGE_|SNAPSHOT_|HELLO_|WIFI_|SOUND_)|DISPLAY_READY|rst:0x")
pending = bytearray()
def read_until(predicate, timeout, stream):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending.extend(connection.read(connection.in_waiting or 1))
        while b"\n" in pending:
            raw, _, rest = pending.partition(b"\n")
            pending[:] = rest
            line = raw.decode("utf-8", errors="replace").strip()
            stream.write(line + "\n")
            stream.flush()
            if safe.search(line):
                print(line, flush=True)
            if predicate(line):
                return line
    raise TimeoutError("Device did not reach the expected connection state.")
try:
    with output.open("w") as stream:
        read_until(lambda line: "SNAPSHOT_READY" in line and "first=1" in line, 20, stream)
        started = time.monotonic()
        os.kill(pid, signal.SIGINT)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            active = subprocess.run(["lsof", "-tiTCP:8787", "-sTCP:LISTEN"],
                                    capture_output=True, text=True).stdout.strip()
            if not active:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Bridge did not stop; refused to start a duplicate.")
        with (root / "logs/agent-display-service.log").open("a") as service_log:
            process = subprocess.Popen(
                [str(root / "mac-bridge/.venv/bin/python"), "-m", "bridge"],
                cwd=root, stdin=subprocess.DEVNULL, stdout=service_log, stderr=subprocess.STDOUT,
                start_new_session=True)
        reset_seen = False
        disconnected = False
        def recovered(line):
            global reset_seen, disconnected
            reset_seen |= "rst:0x" in line
            disconnected |= "BRIDGE_DISCONNECTED" in line
            return "SNAPSHOT_READY" in line and "first=1" in line
        read_until(recovered, 30, stream)
        elapsed = time.monotonic() - started
        assert disconnected and not reset_seen
        result = f"RECONNECT_CHECK_OK seconds={elapsed:.2f} device_reset=0 first_snapshot=1 bridge_pid={process.pid}"
        stream.write(result + "\n")
        print(result, flush=True)
finally:
    connection.close()
