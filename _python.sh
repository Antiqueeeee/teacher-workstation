# 找自带的 Python 运行时；找不到就退回系统 python3（只在开发机上会遇到）。
# 这个文件是「给别的脚本引用」的，老师不需要点它。
PY="./runtime/bin/python3"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ]; then
  echo "没找到 Python 运行时。这个包应该自带 runtime/ 目录 —— 请重新解压一份完整交付包。"
  read -r -p "按回车关闭…" _
  return 1 2>/dev/null || exit 1
fi
