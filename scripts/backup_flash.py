"""Back up flash with a smaller read window for the Mac USB serial buffer."""
import hashlib
import json
from pathlib import Path
import struct
import time

from esptool.cmds import attach_flash
from esptool.targets.esp32s3 import ESP32S3ROM

output = Path("backups/factory-before-hello-screen-20261014.bin")
partial = output.with_suffix(".bin.partial")
flash_capacity = 16 * 1024 * 1024
flash_plan = json.loads(Path("hello_screen/build/flasher_args.json").read_text())
flash_files = flash_plan["flash_files"]
written_end = max(int(offset, 0) + (Path("hello_screen/build") / filename).stat().st_size
                  for offset, filename in flash_files.items())
# Save every sector that this build can overwrite, including gaps between images.
size = (written_end + 0xFFFF) // 0x10000 * 0x10000
if size > flash_capacity:
    raise RuntimeError("Flash plan exceeds device capacity")
chunk_size = 256 * 1024

rom = ESP32S3ROM("/dev/cu.usbmodem1101", baud=115200)
device = rom
try:
    rom.connect()
    device = rom.run_stub()
    device.change_baud(115200)
    attach_flash(device)
    device.flash_set_parameters(flash_capacity)

    original_check = device.check_command

    def small_window_check(description, operation, data=b"", *args, **kwargs):
        if operation == device.ESP_CMDS["READ_FLASH"]:
            offset, length, block_size, _ = struct.unpack("<IIII", data)
            data = struct.pack("<IIII", offset, length, block_size, 4)
        return original_check(description, operation, data, *args, **kwargs)

    device.check_command = small_window_check
    started = time.monotonic()
    with partial.open("wb") as backup:
        for offset in range(0, size, chunk_size):
            # esptool verifies each read against the device's MD5 before returning.
            data = device.read_flash(offset, min(chunk_size, size - offset))
            backup.write(data)
            backup.flush()
            print(f"Verified backup: {offset + len(data)}/{size} bytes", flush=True)
    if partial.stat().st_size != size:
        raise RuntimeError("Incomplete backup")
    partial.replace(output)
    metadata = {
        "chip": "esp32s3",
        "flash_capacity": flash_capacity,
        "offset": 0,
        "backed_up_bytes": size,
        "written_end": written_end,
        "flash_files": flash_files,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "verification": "device MD5 checked for every chunk, all overwritten sectors covered",
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("BACKUP_OK", json.dumps(metadata), flush=True)
finally:
    try:
        device.hard_reset()
    finally:
        device._port.close()
