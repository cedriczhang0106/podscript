"""源适配器：URL → 本地音频文件 + 元数据（三源）。

resolve_source(url, workdir) 自动分流到 bilibili / apple / xiaoyuzhou，
返回统一结构：
    {
      "audio_path": Path,
      "platform": "小宇宙" | "苹果播客" | "B站",
      "show": str, "title": str, "duration": int(秒), "date": "YYYY-MM-DD",
      "url": str,
    }
任何源失败抛 RuntimeError（调用方负责保住已下内容并写排障记录）。
"""
from __future__ import annotations

import re
from pathlib import Path

from . import apple, bilibili, xiaoyuzhou


def detect_platform(url: str) -> str | None:
    if re.search(r"xiaoyuzhoufm\.com", url):
        return "小宇宙"
    if re.search(r"podcasts\.apple\.com", url):
        return "苹果播客"
    if re.search(r"bilibili\.com|b23\.tv", url):
        return "B站"
    return None


def resolve_source(url: str, workdir: Path) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    plat = detect_platform(url)
    if plat == "小宇宙":
        return xiaoyuzhou.resolve(url, workdir)
    if plat == "苹果播客":
        return apple.resolve(url, workdir)
    if plat == "B站":
        return bilibili.resolve(url, workdir)
    raise RuntimeError(f"不支持的链接（仅小宇宙/苹果播客/B站）: {url}")
