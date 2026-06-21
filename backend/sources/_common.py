"""源适配器共用：yt-dlp 下载音频 + 日期/时长归一。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def fmt_date(raw: str) -> str:
    """yt-dlp 的 upload_date 多为 YYYYMMDD → YYYY-MM-DD；已是日期则原样。"""
    raw = (raw or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def ytdlp_download(url: str, outdir: Path, cookies_from_browser: str | None = None,
                   timeout: int = 900) -> dict:
    """yt-dlp 只下音频(mp3) → 返回 {path,title,uploader,upload_date,duration}。

    匿名失败时若给了 cookies_from_browser（如 "chrome"）则带 cookies 重试。
    """
    outdir.mkdir(parents=True, exist_ok=True)
    base = [sys.executable, "-m", "yt_dlp", "-x", "--audio-format", "mp3",
            "--no-playlist", "--print-json", "--no-progress",
            "-o", str(outdir / "%(id)s.%(ext)s")]
    proc = subprocess.run(base + [url], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0 and cookies_from_browser:
        proc = subprocess.run(
            base + ["--cookies-from-browser", cookies_from_browser, url],
            capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        err = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "yt-dlp 失败"
        raise RuntimeError(f"yt-dlp 下载失败: {err}")
    info = json.loads(proc.stdout.strip().splitlines()[-1])
    mp3 = outdir / f"{info['id']}.mp3"
    if not mp3.exists():
        cands = list(outdir.glob(f"{info['id']}.*"))
        if not cands:
            raise RuntimeError("音频文件未找到")
        mp3 = cands[0]
    return {
        "path": mp3,
        "title": info.get("title") or "",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "upload_date": info.get("upload_date") or "",
        "duration": int(info.get("duration") or 0),
    }


def download_url(audio_url: str, dest: Path, timeout: int = 900) -> Path:
    """直链下载（小宇宙/RSS enclosure）。用 requests 流式写盘。"""
    import requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
    with requests.get(audio_url, headers=headers, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
    if dest.stat().st_size < 1024:
        raise RuntimeError("下载的音频文件过小，可能解析到错误链接")
    return dest


def fmt_duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
