"""Flash the built status display without erasing the saved NVS partition."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="/dev/cu.usbmodem1101")
parser.add_argument("--before", choices=("usb-reset", "no-reset"), default="usb-reset")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
build = root / "agent_display/build"
plan = json.loads((build / "flasher_args.json").read_text())
files = plan["flash_files"]
if set(files) != {"0x0", "0x8000", "0x20000"}:
    raise SystemExit("Unexpected flash plan; refusing to overwrite additional partitions.")
backups = sorted((root / "backups").glob("before-agent_display-*.json"))
if not backups:
    raise SystemExit("Run backup_project_flash.py before the first flash.")
end = max(int(offset, 0) + (build / name).stat().st_size for offset, name in files.items())
backup = backups[-1]
record = json.loads(backup.read_text())
image = backup.with_suffix(".bin")
if record["backed_up_bytes"] < end or hashlib.sha256(image.read_bytes()).hexdigest() != record["sha256"]:
    raise SystemExit("Backup is insufficient or failed checksum validation.")
flash_record = dict(started=datetime.now().isoformat(), status="started",
                    backup=backup.name, files={offset: dict(file=name, bytes=(build / name).stat().st_size,
                    sha256=hashlib.sha256((build / name).read_bytes()).hexdigest())
                    for offset, name in files.items()})
path = build / "installation.json"
path.write_text(json.dumps(flash_record, indent=2) + "\n")
command = [sys.executable, "-m", "esptool", "--chip", "esp32s3", "--port", args.port,
           "--baud", "115200", "--before", args.before,
           "--after", "watchdog-reset" if args.before == "no-reset" else "hard-reset",
           "write-flash", "--flash-mode", plan["flash_settings"]["flash_mode"],
           "--flash-freq", plan["flash_settings"]["flash_freq"], "--flash-size", "16MB"]
for offset, name in sorted(files.items(), key=lambda item: int(item[0], 0)):
    command += [offset, str(build / name)]
result = subprocess.run(command)
flash_record["status"] = "flash_verified" if result.returncode == 0 else "flash_failed"
flash_record["exit_code"] = result.returncode
path.write_text(json.dumps(flash_record, indent=2) + "\n")
raise SystemExit(result.returncode)
