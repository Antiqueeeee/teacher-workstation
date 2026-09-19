# 找自带的 Python 运行时。老师不装 Python：这个包自带一份（runtime/），
# 而且**不能**悄悄退回老师自己装的那个 python3 —— 那等于依赖了他的环境。
# 开发机专用：设 TWS_ALLOW_SYSTEM_PYTHON=1 才允许退回系统 python3。
# 这个文件是给别的脚本引用的，老师不需要点它。
PY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/runtime/bin/python3"
if [ -x "$PY" ]; then
  return 0 2>/dev/null || exit 0
fi

if [ "${TWS_ALLOW_SYSTEM_PYTHON:-}" = "1" ]; then
  PY="$(command -v python3 || true)"
  if [ -z "$PY" ]; then
    echo "TWS_ALLOW_SYSTEM_PYTHON=1，但系统里也没有 python3。"
    read -r -p "按回车关闭…" _
    return 1 2>/dev/null || exit 1
  fi
  echo "[dev] 正在用系统 python3 —— 交付包里本该自带 runtime/bin/python3"
  return 0 2>/dev/null || exit 0
fi

echo
echo "没找到自带的 Python 运行时：runtime/bin/python3"
echo "请重新解压一份**完整**的交付包（runtime/ 要和脚本在同一层）。"
echo "你的电脑上没有被安装或改动任何东西。"
echo
read -r -p "按回车关闭…" _
return 1 2>/dev/null || exit 1
