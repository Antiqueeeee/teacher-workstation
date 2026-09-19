#!/bin/bash
# macOS：双击运行（后台；关掉这个窗口不影响使用）
cd "$(dirname "$0")" || exit 1
. ./_python.sh || exit 1
"$PY" launcher.py --daemon
echo
echo "服务已经在后台运行了，关掉这个窗口不影响使用。"
read -r -p "按回车关闭…" _
