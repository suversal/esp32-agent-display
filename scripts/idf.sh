#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
project_name="${IDF_PROJECT:-hello_screen}"
if [[ ! "$project_name" =~ ^[a-zA-Z0-9_-]+$ ]] || [[ ! -f "$project_root/$project_name/CMakeLists.txt" ]]; then
    echo "无效的 IDF_PROJECT：$project_name" >&2
    exit 2
fi
echo "正在编译/烧录：$project_name"
export IDF_PATH="$project_root/.tools/esp-idf"
export IDF_TOOLS_PATH="$project_root/.tools/idf-tools"
export PATH="$project_root/.tools/serial-venv/bin:/opt/homebrew/bin:$PATH"
source "$IDF_PATH/export.sh" >/dev/null
exec python "$IDF_PATH/tools/idf.py" -C "$project_root/$project_name" "$@"
