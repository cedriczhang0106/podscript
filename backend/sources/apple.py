"""苹果播客源：先试 yt-dlp(ApplePodcasts)，失败 fallback iTunes Lookup → RSS enclosure。

苹果播客是开放 RSS、无 DRM，所以 fallback 一定能拿到 mp3 直链。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ._common import download_url, fmt_date, ytdlp_download


def _parse_ids(url: str) -> tuple[str | None, str | None]:
    """从 .../id<podcastId>?i=<episodeId> 提 (podcastId, episodeId)。"""
    pid = re.search(r"/id(\d+)", url)
    eid = re.search(r"[?&]i=(\d+)", url)
    return (pid.group(1) if pid else None, eid.group(1) if eid else None)


def _itunes_lookup(podcast_id: str) -> dict:
    import requests
    r = requests.get("https://itunes.apple.com/lookup",
                     params={"id": podcast_id, "entity": "podcastEpisode", "limit": 200},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    return r.json()


def _enclosure_from_feed(feed_url: str, episode_id: str | None, title_hint: str) -> dict:
    """拉 RSS，按 episode title 或 guid 命中单集，取 <enclosure url> mp3。"""
    import requests
    r = requests.get(feed_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = root.findall(".//item")
    chosen = None
    for it in items:
        title = (it.findtext("title") or "").strip()
        if title_hint and title_hint.strip() and title_hint.strip() in title:
            chosen = it
            break
    if chosen is None and items:
        chosen = items[0]   # 兜底取最新一集
    if chosen is None:
        raise RuntimeError("RSS 中无单集")
    enc = chosen.find("enclosure")
    audio_url = enc.get("url") if enc is not None else None
    if not audio_url:
        raise RuntimeError("RSS 单集无 enclosure 音频")
    show = (root.findtext(".//channel/title") or "").strip()
    title = (chosen.findtext("title") or "").strip()
    pub = (chosen.findtext("pubDate") or "").strip()
    # itunes:duration 命名空间
    dur = 0
    for tag in chosen.iter():
        if tag.tag.endswith("duration") and tag.text:
            t = tag.text.strip()
            if ":" in t:
                parts = [int(x) for x in t.split(":")]
                while len(parts) < 3:
                    parts.insert(0, 0)
                dur = parts[0] * 3600 + parts[1] * 60 + parts[2]
            elif t.isdigit():
                dur = int(t)
            break
    return {"audio_url": audio_url, "show": show, "title": title, "pub": pub, "duration": dur}


def _fmt_rss_date(pub: str) -> str:
    m = re.search(r"(\d{1,2})\s+(\w{3})\s+(\d{4})", pub)
    months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
              "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
    if m and m.group(2) in months:
        return f"{m.group(3)}-{months[m.group(2)]}-{int(m.group(1)):02d}"
    return pub


def _collection_name(podcast_id: str | None) -> str:
    """yt-dlp 常拿不到 uploader → 用 iTunes Lookup 的 collectionName 兜底节目名。"""
    if not podcast_id:
        return ""
    try:
        for x in _itunes_lookup(podcast_id).get("results", []):
            if x.get("collectionName"):
                return x["collectionName"]
    except Exception:
        pass
    return ""


def resolve(url: str, workdir: Path) -> dict:
    # ① 先试 yt-dlp 自带 ApplePodcasts 解析
    try:
        info = ytdlp_download(url, workdir)
        pid, _ = _parse_ids(url)
        show = info["uploader"] or _collection_name(pid) or "苹果播客"
        return {
            "audio_path": info["path"], "platform": "苹果播客",
            "show": show, "title": info["title"],
            "duration": info["duration"], "date": fmt_date(info["upload_date"]), "url": url,
        }
    except Exception as ytdlp_err:
        last = ytdlp_err

    # ② fallback：iTunes Lookup → 单集 episodeUrl，或频道 feedUrl 的 RSS enclosure
    pid, eid = _parse_ids(url)
    if not pid:
        raise RuntimeError(f"苹果播客解析失败且无法提取 podcastId: {last}")
    data = _itunes_lookup(pid)
    results = data.get("results", [])
    channel = next((x for x in results if x.get("wrapperType") == "track"
                    and x.get("kind") == "podcast"), results[0] if results else {})
    episodes = [x for x in results if x.get("wrapperType") == "podcastEpisode"]

    ep = None
    if eid:
        ep = next((x for x in episodes if str(x.get("trackId")) == eid), None)
    if ep and ep.get("episodeUrl"):
        meta = {"audio_url": ep["episodeUrl"], "show": channel.get("collectionName", "苹果播客"),
                "title": ep.get("trackName", ""), "pub": ep.get("releaseDate", ""),
                "duration": int((ep.get("trackTimeMillis") or 0) / 1000)}
    else:
        feed_url = channel.get("feedUrl")
        if not feed_url:
            raise RuntimeError(f"苹果播客无 episodeUrl 且无 feedUrl: {last}")
        title_hint = ep.get("trackName", "") if ep else ""
        meta = _enclosure_from_feed(feed_url, eid, title_hint)

    dest = workdir / f"apple_{eid or pid}.mp3"
    download_url(meta["audio_url"], dest)
    date = meta["pub"]
    date = date[:10] if re.match(r"\d{4}-\d{2}-\d{2}", date or "") else _fmt_rss_date(date)
    return {
        "audio_path": dest, "platform": "苹果播客",
        "show": meta["show"] or "苹果播客", "title": meta["title"],
        "duration": meta["duration"], "date": date, "url": url,
    }
