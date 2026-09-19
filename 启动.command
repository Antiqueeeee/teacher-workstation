#!/bin/bash
# macOS：双击运行（前台；关掉这个窗口就停）
cd "$(dirname "$0")" || exit 1
. ./_python.sh || exit 1
"$PY" launcher.py
if [ $? -ne 0 ]; then read -r -p "按回车关闭…" _; fi
