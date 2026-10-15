"""Restore the factory program, selecting a complete image after larger writes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="/dev/cu.usbmodem1101")
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
if (root / "firmware/xiaozhi-v2.4.2/installation.json").exists():
    # The AI image exceeds the old partial backup, so use the complete stock image.
    backup = root / "firmware/waveshare-factory/factory-v1.bin"
    metadata = json.loads((backup.parent / "firmware.json").read_text())
    expected_size = metadata["bytes"]
    print("Restoring official Waveshare factory firmware; AI settings will be cleared.")
else:
    backup = root / "backups/factory-before-hello-screen-20261014.bin"
    metadata = json.loads(backup.with_suffix(".json").read_text())
    expected_size = metadata["backed_up_bytes"]
data = backup.read_bytes()
if len(data) != expected_size:
    raise SystemExit("Backup size does not match metadata; refusing to write.")
if hashlib.sha256(data).hexdigest() != metadata["sha256"]:
    raise SystemExit("Backup checksum does not match; refusing to write.")

subprocess.run([
    sys.executable, "-m", "esptool", "--chip", "esp32s3",
    "--port", args.port, "--baud", "115200", "write-flash",
    "--flash-mode", "keep", "--flash-size", "keep", "--flash-freq", "keep",
    "0x0", str(backup),
], check=True)
