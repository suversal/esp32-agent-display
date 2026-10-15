"""Install the verified official firmware for this board."""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="/dev/cu.usbmodem1101")
parser.add_argument("--before", choices=("usb-reset", "no-reset"), default="usb-reset")
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
folder = root / "firmware/xiaozhi-v2.4.2"
image = folder / "merged-binary.bin"
expected = "cd647c510593d0325b632ad3e8eb88f7b88cc2b175455eb3a4055b5c73451bc1"
if hashlib.sha256(image.read_bytes()).hexdigest() != expected:
    raise SystemExit("Firmware checksum mismatch; refusing to write.")

record_path = folder / "installation.json"
record = {
    "board": "ESP32-S3-RLCD-4.2",
    "version": "2.4.2",
    "status": "flash_started",
    "written_bytes": image.stat().st_size,
    "cloud_activation_verified": False,
    "voice_conversation_verified": False,
}
record_path.write_text(json.dumps(record, indent=2) + "\n")
try:
    subprocess.run([
        sys.executable, "-m", "esptool", "--chip", "esp32s3",
        "--port", args.port, "--baud", "115200",
        "--before", args.before,
        "--after", "watchdog-reset" if args.before == "no-reset" else "hard-reset",
        "write-flash", "--flash-mode", "keep", "--flash-freq", "keep",
        "--flash-size", "16MB", "0x0", str(image),
    ], check=True)
except subprocess.CalledProcessError as error:
    record["status"] = "flash_failed"
    record["exit_code"] = error.returncode
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    raise
record["status"] = "flash_verified"
record_path.write_text(json.dumps(record, indent=2) + "\n")
