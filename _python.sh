# 找 Python 运行时。老师不装 Python：这个项目自带一份（runtime/），
# 第一次运行时由 tools/bootstrap.py 装进去。**不能**悄悄用老师自己装的 Python3。
# 这个文件是给别的脚本引用的，老师不需要点它。
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$REPO_DIR/runtime/bin/python3"
if [ -x "$PY" ]; then
  return 0 2>/dev/null || exit 0
fi

BOOT="$REPO_DIR/tools/bootstrap.py"
if [ ! -f "$BOOT" ]; then
  echo "缺少 tools/bootstrap.py —— 请重新克隆/解压一份完整的项目。"
  read -r -p "按回车关闭…" _
  return 1 2>/dev/null || exit 1
fi

# 第一次运行：用系统 python3 把自带运行时下下来、把依赖装进去。
# 系统 python3 只用来**下载与安装**；服务本身永远跑在自带运行时上。
BOOTSTRAP_PY="$(command -v python3 || true)"
if [ -z "$BOOTSTRAP_PY" ]; then
  echo
  echo "这个项目需要一份 Python 运行时，而这台电脑上还没有。两种办法："
  echo "  1) 推荐：把这个项目的 git 地址丢给 AI 助手（比如 WorkBuddy），"
  echo "     让它来跑这个项目 —— 它能把运行时准备好；"
  echo "  2) 或者装一次 python.org 上的 Python 3.11，再双击一次启动脚本"
  echo "     （项目会自己装一份到 runtime/，你系统里的 Python 不受影响）。"
  echo "你的电脑上没有被安装或改动任何东西。"
  echo
  read -r -p "按回车关闭…" _
  return 1 2>/dev/null || exit 1
fi

echo
echo "第一次运行：正在把自带的 Python 运行时装到 runtime/ ……"
echo "（不会往你自己的 Python 环境里装任何东西）"
echo
if ! "$BOOTSTRAP_PY" "$BOOT"; then
  read -r -p "按回车关闭…" _
  return 1 2>/dev/null || exit 1
fi

if [ -x "$PY" ]; then
  return 0 2>/dev/null || exit 0
fi
echo "自举跑完了，但 runtime/bin/python3 仍然不存在 —— 请把上面的输出发给技术同事。"
read -r -p "按回车关闭…" _
return 1 2>/dev/null || exit 1
