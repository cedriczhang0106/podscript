"""B站源：yt-dlp 自带解析器，匿名失败带 Chrome cookies 重试。"""
from __future__ import annotations

from pathlib import Path

from ._common import fmt_date, ytdlp_download


def resolve(url: str, workdir: Path) -> dict:
    info = ytdlp_download(url, workdir, cookies_from_browser="chrome")
    return {
        "audio_path": info["path"],
        "platform": "B站",
        "show": info["uploader"] or "B站",
        "title": info["title"],
        "duration": info["duration"],
        "date": fmt_date(info["upload_date"]),
        "url": url,
    }
