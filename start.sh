#!/usr/bin/env bash
# PodScript 一键启动：建环境 → 装依赖 → 起服务 → 开浏览器
# 用法：  bash start.sh      （或先 chmod +x start.sh 后 ./start.sh）
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
URL="http://127.0.0.1:${PORT}"

# 1) Python 3
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ 没找到 Python 3。请先安装 Python 3.10+（https://www.python.org/downloads/）"
  exit 1
fi

# 2) ffmpeg（转录必需，缺了给提示但不中断，方便先看界面）
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "⚠ 没检测到 ffmpeg —— 转录会用到它。"
  echo "    macOS:  brew install ffmpeg"
  echo "    Ubuntu: sudo apt install ffmpeg"
  echo "  （可以先继续，等装好 ffmpeg 再转录）"
fi

# 3) 虚拟环境
if [ ! -d .venv ]; then
  echo "→ 首次运行：创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 4) 依赖（用标记文件避免每次重装；requirements 变了会自动重装）
if [ ! -f .venv/.deps_ok ] || [ requirements.txt -nt .venv/.deps_ok ]; then
  echo "→ 安装依赖（首次会下载 faster-whisper 等，稍久，请耐心）..."
  python3 -m pip install -q --upgrade pip
  python3 -m pip install -q -r requirements.txt
  touch .venv/.deps_ok
fi

# 5) 启动服务 + 延迟自动开浏览器
echo ""
echo "→ 启动 PodScript：$URL"
echo "  浏览器会自动打开；停止服务在本终端按 Ctrl+C。"
(
  sleep 2
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  elif command -v start >/dev/null 2>&1; then start "$URL"
  fi
) >/dev/null 2>&1 &

exec python3 -m uvicorn backend.app:app --port "$PORT"
