#!/bin/bash
cd "$(dirname "$0")" || exit 1
. ./_python.sh || exit 1
"$PY" launcher.py --status
read -r -p "按回车关闭…" _
