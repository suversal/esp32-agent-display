"""Verify and back up every flash sector a selected ESP-IDF build can overwrite."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import struct
import time
from esptool.cmds import attach_flash
from esptool.targets.esp32s3 import ESP32S3ROM

parser = argparse.ArgumentParser()
parser.add_argument("--project", default="firmware-status-display")
parser.add_argument("--port", default="/dev/cu.usbmodem1101")
parser.add_argument("--before", choices=("usb-reset", "no-reset"), default="usb-reset")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
project = root / args.project
if project.parent != root or not (project / "CMakeLists.txt").exists():
    parser.error("Invalid project")
build = project / "build"
plan = json.loads((build / "flasher_args.json").read_text())
capacity = 16 * 1024 * 1024
end = max(int(offset, 0) + (build / filename).stat().st_size
          for offset, filename in plan["flash_files"].items())
size = (end + 0xffff) // 0x10000 * 0x10000
if size > capacity:
    raise SystemExit("Flash plan exceeds device capacity.")
folder = root / "backups"
folder.mkdir(exist_ok=True)
# The on-device project and existing recovery metadata keep their stable identity.
backup_project = "agent_display" if args.project == "firmware-status-display" else args.project
output = folder / f"before-{backup_project}-{datetime.now():%Y%m%d-%H%M%S}.bin"
partial = output.with_suffix(".bin.partial")
partial.touch(mode=0o600)
rom = ESP32S3ROM(args.port, baud=115200)
device = rom
try:
    rom.connect(mode=args.before)
    device = rom.run_stub()
    device.change_baud(115200)
    attach_flash(device)
    device.flash_set_parameters(capacity)
    original_check = device.check_command
    def small_window(description, operation, data=b"", *args, **kwargs):
        if operation == device.ESP_CMDS["READ_FLASH"]:
            offset, length, block_size, _ = struct.unpack("<IIII", data)
            data = struct.pack("<IIII", offset, length, block_size, 4)
        return original_check(description, operation, data, *args, **kwargs)
    device.check_command = small_window
    started = time.monotonic()
    with partial.open("wb") as stream:
        for offset in range(0, size, 256 * 1024):
            data = device.read_flash(offset, min(256 * 1024, size - offset))
            stream.write(data)
            stream.flush()
            print(f"Verified backup: {offset + len(data)}/{size} bytes", flush=True)
    if partial.stat().st_size != size:
        raise RuntimeError("Incomplete backup")
    partial.replace(output)
    # Also preserve the saved Wi-Fi/activation partition for merged-image restoration.
    nvs = output.read_bytes()[0x9000:0xd000]
    nvs_file = output.with_suffix(".nvs.bin")
    nvs_file.touch(mode=0o600)
    nvs_file.write_bytes(nvs)
    record = {
        "project": backup_project, "chip": "esp32s3", "offset": 0,
        "backed_up_bytes": size, "written_end": end,
        "flash_files": plan["flash_files"],
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "nvs_file": nvs_file.name, "nvs_offset": 0x9000,
        "nvs_sha256": hashlib.sha256(nvs).hexdigest(),
        "verification": "Every chunk verified against device MD5; includes all overwritten sectors",
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    output.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"BACKUP_OK file={output.name} bytes={size}", flush=True)
finally:
    try:
        device.hard_reset()
    finally:
        device._port.close()
