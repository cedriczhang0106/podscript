"""小宇宙源（唯一需自定义解析）：抓页面 HTML → 提音频直链 + 元数据。

音频直链优先级：
  ① <meta property="og:audio"> 的 content
  ② __NEXT_DATA__ JSON 里 episode.enclosure.url（小宇宙是 Next.js 站）
  ③ 正则兜底 https?://...(m4a|mp3)
元数据（节目/单集/时长/发布日）从 __NEXT_DATA__ / og 取。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ._common import download_url

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _fetch_html(url: str) -> str:
    import requests
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


def _og(html: str, prop: str) -> str | None:
    m = re.search(
        r'<meta[^>]+property=["\']og:%s["\'][^>]+content=["\']([^"\']+)["\']' % prop, html)
    if not m:
        m = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:%s["\']' % prop, html)
    return m.group(1) if m else None


def _next_data(html: str) -> dict | None:
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _find_episode(obj):
    """在 __NEXT_DATA__ 里递归找含 enclosure.url 的 episode 节点。"""
    if isinstance(obj, dict):
        enc = obj.get("enclosure")
        if isinstance(enc, dict) and enc.get("url"):
            return obj
        for v in obj.values():
            found = _find_episode(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_episode(v)
            if found:
                return found
    return None


def resolve(url: str, workdir: Path) -> dict:
    html = _fetch_html(url)
    audio_url = None
    show = title = date = ""
    duration = 0

    nd = _next_data(html)
    if nd:
        ep = _find_episode(nd)
        if ep:
            audio_url = (ep.get("enclosure") or {}).get("url")
            title = ep.get("title") or ""
            duration = int(ep.get("duration") or 0)
            pod = ep.get("podcast") or {}
            show = pod.get("title") or ""
            pub = ep.get("pubDate") or ep.get("publishDate") or ""
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", pub)
            if m:
                date = m.group(0)

    # ① og:audio 优先（最稳的直链）
    og_audio = _og(html, "audio")
    if og_audio:
        audio_url = og_audio
    # ③ 正则兜底
    if not audio_url:
        m = re.search(r'https?://[^"\'\s]+\.(?:m4a|mp3)', html)
        if m:
            audio_url = m.group(0)

    if not audio_url:
        raise RuntimeError("小宇宙页面未解析出音频直链（og:audio / __NEXT_DATA__ / 正则均未命中）")

    if not title:
        title = (_og(html, "title") or "").replace(" | 小宇宙", "").strip()
    if not show:
        show = "小宇宙"

    ep_id = re.search(r"/episode/([0-9a-zA-Z]+)", url)
    dest = workdir / f"xyz_{ep_id.group(1) if ep_id else 'episode'}.m4a"
    if audio_url.split("?")[0].endswith(".mp3"):
        dest = dest.with_suffix(".mp3")
    download_url(audio_url, dest)

    return {
        "audio_path": dest, "platform": "小宇宙",
        "show": show, "title": title, "duration": duration, "date": date, "url": url,
    }
