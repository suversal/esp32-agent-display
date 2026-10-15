"""Restore the exact pre-status firmware sectors, including saved Wi-Fi config."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument("backup", type=Path, help="before-agent_display-*.json metadata")
parser.add_argument("--port", default="/dev/cu.usbmodem1101")
parser.add_argument("--before", choices=("usb-reset", "no-reset"), default="usb-reset")
args = parser.parse_args()
record = json.loads(args.backup.read_text())
image = args.backup.with_suffix(".bin")
if record.get("project") != "agent_display" or record.get("offset") != 0:
    raise SystemExit("Unexpected backup metadata.")
if image.stat().st_size != record["backed_up_bytes"] or hashlib.sha256(image.read_bytes()).hexdigest() != record["sha256"]:
    raise SystemExit("Backup checksum mismatch.")
subprocess.run([sys.executable, "-m", "esptool", "--chip", "esp32s3", "--port", args.port,
                "--baud", "115200", "--before", args.before,
                "--after", "watchdog-reset" if args.before == "no-reset" else "hard-reset",
                "write-flash", "--flash-mode", "keep", "--flash-freq", "keep",
                "--flash-size", "16MB", "0x0", str(image)], check=True)
