"""Generate a private device header from the existing local bridge config."""
import argparse
import json
from pathlib import Path
import subprocess
import tomllib
from urllib.parse import quote

def command(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""

parser = argparse.ArgumentParser()
parser.add_argument("--config", type=Path, default=Path.home() / ".config/agent-display/config.toml")
parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "firmware-status-display/main/secrets.h")
parser.add_argument("--force", action="store_true")
args = parser.parse_args()
if args.output.exists() and not args.force:
    parser.error("Private header already exists; use --force to regenerate.")
config = tomllib.loads(args.config.read_text())
host = command("/usr/sbin/scutil", "--get", "LocalHostName")
ip = command("/usr/sbin/ipconfig", "getifaddr", "en0") or command("/usr/sbin/ipconfig", "getifaddr", "en1")
token = config["token"]
if not token or not (host or ip):
    raise SystemExit("Bridge token or local network address is unavailable.")
values = {"WIFI_SSID": "", "WIFI_PASSWORD": "", "BRIDGE_HOST": host,
          "BRIDGE_FALLBACK_IP": ip, "BRIDGE_PORT": config.get("port", 8787),
          "BRIDGE_TOKEN_URLENCODED": quote(token, safe="")}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.touch(mode=0o600)
args.output.chmod(0o600)
args.output.write_text("#pragma once\n// Private generated configuration. Do not publish.\n" +
                       "".join(f"#define {key} {json.dumps(value)}\n" for key, value in values.items()))
print("Private bridge header generated; credentials were not printed.")
