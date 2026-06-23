"""简单清洗 + 提炼 + 导出。

定义清楚"简单"，绝不过度（不做观点提取/爆款拆解/选题卡/多轮精修）：
  - 加标点 + 分段
  - 轻度去口水（嗯/那个/就是/这个… + 合并明显重复）
  - 一段摘要(2-3 句) + 3-5 个要点
长稿超长就分块清洗（防截断），但只跑一遍、不精修。
无 LLM key 时降级：正则去口水 + 原样分段、不出摘要。
"""
from __future__ import annotations

import json
import re
import urllib.request
import urllib.error

from . import config

# ── 时间戳工具 ──
def fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"[{m:02d}:{s:02d}]"


# ── LLM 调用（OpenAI 兼容；deepseek 也兼容此端点）──
def _llm_post(url: str, cfg: dict, prompt: str, max_tokens: int, temperature):
    body = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['key']}",
    })
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def _llm_call(prompt: str, cfg: dict, max_tokens: int = 4096) -> str:
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    try:
        resp = _llm_post(url, cfg, prompt, max_tokens, cfg.get("_temp", 0.3))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "ignore")[:400]
        except Exception:
            detail = ""
        # 某些模型（如 Kimi k2.x 思考型）只允许 temperature=1，命中就用 1 重试一次
        if e.code == 400 and "temperature" in detail.lower() and cfg.get("_temp", 0.3) != 1:
            cfg["_temp"] = 1  # 记住该模型只接受 temperature=1，后续调用直接用、不再每次白撞一次 400
            try:
                resp = _llm_post(url, cfg, prompt, max_tokens, 1)
            except urllib.error.HTTPError as e2:
                try:
                    d2 = e2.read().decode("utf-8", "ignore")[:400]
                except Exception:
                    d2 = ""
                raise RuntimeError(f"HTTP {e2.code}（{url}）: {d2}") from None
            except Exception as e2:
                raise RuntimeError(f"连接失败（{url}）: {e2}") from None
        else:
            raise RuntimeError(f"HTTP {e.code}（{url}）: {detail}") from None
    except Exception as e:
        raise RuntimeError(f"连接失败（{url}）: {e}") from None
    # 只取最终 message.content；思考模型（GLM/DeepSeek）的推理在独立 reasoning_content 字段，
    # 不会进 content。个别模型会把思考包在 <think>…</think> 里混进 content，这里剥掉。
    content = resp["choices"][0]["message"].get("content") or ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S | re.I)
    return content.strip()


# ── 正则去口水（无 LLM 时的兜底，也作为 LLM 前的预处理）──
FILLERS = ["嗯", "呃", "啊", "那个那个", "就是就是", "这个这个"]


def _regex_destutter(text: str) -> str:
    for f in FILLERS:
        text = text.replace(f, "")
    text = re.sub(r"([一-龥])\1{2,}", r"\1", text)  # 三连及以上叠字压成一个
    return text.strip()


# ── 清洗：逐行保留 [mm:ss]，加标点/去口水/分段 ──
CLEAN_PROMPT = """下面是一段播客的机器转录（按时间戳分行，可能无标点、有口水词和叠字）。请清洗：
① 给每行加标点；② 轻度去口水（删"嗯/呃/那个/就是/这个"等语气词、合并明显重复词）；③ 保持原话语义，不要改写、不要概括、不要删句子。
**严格要求**：保留每行行首的 [mm:ss] 时间戳原样不动，输出行数和顺序与输入一致，逐行对应。只输出清洗后的逐字稿，不要解释、不要代码块。

转录片段：
{chunk}"""

TS_LINE = re.compile(r"^\s*(\[\d{1,2}:\d{2}\])\s*(.*)$")


def _clean_chunked(lines: list[str], cfg: dict | None) -> list[str]:
    """lines: ['[00:03] 原文', ...]。返回清洗后的同结构行。"""
    if not cfg:
        # 兜底：仅正则去口水，时间戳保留
        out = []
        for ln in lines:
            m = TS_LINE.match(ln)
            if m:
                out.append(f"{m.group(1)} {_regex_destutter(m.group(2))}")
        return out

    # 按 ~3500 字分块（含时间戳行），防长稿截断；只跑一遍
    CHUNK = 3500
    chunks, cur, size = [], [], 0
    for ln in lines:
        if size + len(ln) > CHUNK and cur:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(ln)
        size += len(ln) + 1
    if cur:
        chunks.append(cur)

    cleaned: list[str] = []
    for ch in chunks:
        raw = "\n".join(ch)
        try:
            resp = _llm_call(CLEAN_PROMPT.format(chunk=raw), cfg, max_tokens=4096)
            resp = re.sub(r"^```.*$", "", resp, flags=re.M).strip()
            got = [m.group(0).strip() for m in
                   (TS_LINE.match(l) for l in resp.splitlines()) if m]
            if got:
                cleaned.extend(f"{TS_LINE.match(l).group(1)} {TS_LINE.match(l).group(2)}"
                               for l in got)
            else:
                # 模型把时间戳丢了 → 该块退回正则清洗，保住时间戳
                cleaned.extend(f"{TS_LINE.match(l).group(1)} {_regex_destutter(TS_LINE.match(l).group(2))}"
                               for l in ch if TS_LINE.match(l))
        except Exception:
            cleaned.extend(f"{TS_LINE.match(l).group(1)} {_regex_destutter(TS_LINE.match(l).group(2))}"
                           for l in ch if TS_LINE.match(l))
    return cleaned


SUMMARY_PROMPT = """下面是一期播客的逐字稿。请输出 JSON（不要 markdown 代码块），字段：
- "summary": 2-3 句话的整体摘要
- "points": 3-5 条要点，每条一句话（数组）
只输出 JSON。

逐字稿（节选）：
{text}"""


def _summarize(clean_text: str, cfg: dict | None) -> dict:
    if not cfg:
        return {"summary": "", "points": []}
    # 摘要用前 ~8000 字判断已足够（简单版，不做全文多轮）
    snippet = clean_text[:8000]
    try:
        resp = _llm_call(SUMMARY_PROMPT.format(text=snippet), cfg, max_tokens=1024)
        resp = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.strip(), flags=re.M)
        m = re.search(r"\{.*\}", resp, re.S)
        data = json.loads(m.group(0) if m else resp)
        pts = data.get("points") or []
        if isinstance(pts, str):
            pts = [pts]
        return {"summary": (data.get("summary") or "").strip(), "points": [str(p).strip() for p in pts][:5]}
    except Exception:
        return {"summary": "", "points": []}


# ── 按要点/话题分段（让逐字稿不再一句一行）──
def _ts_to_sec(ts: str) -> int:
    m = re.search(r"(\d{1,2}):(\d{2})", ts or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else 0


SEGMENT_PROMPT = """下面是一期播客带时间戳的逐字稿。请按话题把它切成 4-8 个连续段落（覆盖全程）。
每段输出：一个简短小标题（≤20字，概括这段在讲什么）+ 该段开始的时间戳（必须是文中真实出现过的 [mm:ss]）。
输出 JSON（不要 markdown 代码块）：{{"sections":[{{"title":"...","start":"mm:ss"}}, ...]}}
要求：按时间先后排列；第一段 start 用最早的时间戳；标题用中文、像小标题不像整句。只输出 JSON。

逐字稿：
{text}"""


def _segment_by_topic(clean_lines: list[str], cfg: dict) -> list[dict]:
    """LLM 按话题切段，返回 [{'title':str,'start':秒}]；失败返回 []。"""
    joined = "\n".join(clean_lines)
    if len(joined) > 14000:
        step = (len(joined) // 14000) + 1
        joined = "\n".join(clean_lines[::step])
    try:
        resp = _llm_call(SEGMENT_PROMPT.format(text=joined), cfg, max_tokens=1024)
        resp = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.strip(), flags=re.M)
        m = re.search(r"\{.*\}", resp, re.S)
        data = json.loads(m.group(0) if m else resp)
        secs = []
        for s in (data.get("sections") or []):
            title = str(s.get("title", "")).strip()
            if title:
                secs.append({"title": title, "start": _ts_to_sec(str(s.get("start", "")))})
        secs.sort(key=lambda x: x["start"])
        return secs
    except Exception:
        return []


def _time_block_sections(clean_lines: list[str], block_sec: int = 600) -> list[dict]:
    """无 LLM 兜底：每 ~block_sec 秒（默认10分钟）一段。"""
    secs, last = [], -1
    for ln in clean_lines:
        m = TS_LINE.match(ln)
        if not m:
            continue
        blk = (_ts_to_sec(m.group(1)) // block_sec) * block_sec
        if blk != last:
            secs.append({"title": "", "start": blk})
            last = blk
    return secs


def _split_paragraphs(text: str, target: int = 160) -> list[str]:
    """把一段长文按句末标点切成 ~target 字的自然段落（清洗后才有标点，故有效）。"""
    parts = re.split(r"(?<=[。！？!?…])", text)
    paras, cur = [], ""
    for p in parts:
        if not p:
            continue
        cur += p
        if len(cur) >= target:
            paras.append(cur.strip())
            cur = ""
    if cur.strip():
        paras.append(cur.strip())
    return paras or ([text] if text else [])


def _build_sections(clean_lines: list[str], boundaries: list[dict]) -> list[dict]:
    """把每行归入最近一个起点<=该行时间的段；合并为段落文本。"""
    rows = []
    for ln in clean_lines:
        m = TS_LINE.match(ln)
        if m:
            rows.append((_ts_to_sec(m.group(1)), m.group(1), m.group(2)))
    if not boundaries:
        boundaries = [{"title": "", "start": 0}]
    boundaries = sorted(boundaries, key=lambda x: x["start"])
    boundaries[0]["start"] = 0
    out = []
    for i, b in enumerate(boundaries):
        start = b["start"]
        end = boundaries[i + 1]["start"] if i + 1 < len(boundaries) else 10 ** 9
        chunk = [r for r in rows if start <= r[0] < end]
        if not chunk:
            continue
        text = "".join(r[2] for r in chunk).strip()
        out.append({
            "title": b.get("title", ""),
            "ts": chunk[0][1].strip("[]"),
            "text": text,
            "paras": _split_paragraphs(text),
            "lines": [{"ts": r[1].strip("[]"), "text": r[2]} for r in chunk],
        })
    return [s for s in out if s["text"]]


# ── 主流程 ──
def process(segments: list[tuple[float, str]], *, punctuate: bool = True,
            summary: bool = True, llm_key: str | None = None,
            llm_base: str | None = None, llm_model: str | None = None,
            allow_llm: bool = True) -> dict:
    """segments → {raw_lines, clean_lines, summary, points, cleaned}。"""
    raw_lines = [f"{fmt_ts(t)} {text}" for t, text in segments]
    cfg = config.llm_config(llm_key, llm_base, llm_model) if (allow_llm and (punctuate or summary)) else None

    clean_lines = _clean_chunked(raw_lines, cfg) if punctuate else raw_lines[:]
    cleaned_text = "\n".join(re.sub(r"^\[\d{1,2}:\d{2}\]\s*", "", l) for l in clean_lines)

    llm_error = None
    if cfg:
        try:
            _llm_call("回复两个字：ok", cfg, max_tokens=8)
        except Exception as e:
            llm_error = f"{type(e).__name__}: {str(e)[:300]}"
            cfg = None
    elif allow_llm and (punctuate or summary):
        llm_error = "未接通在线模型：服务端没收到 API key（请在『接大模型』里粘贴 key 并点保存，再确认页面已刷新）"

    sm = _summarize(cleaned_text, cfg) if summary else {"summary": "", "points": []}

    # 分段：有 LLM 按话题/要点切，否则按时长（10 分钟）合并
    bounds = _segment_by_topic(clean_lines, cfg) if (cfg and summary) else []
    if not bounds:
        bounds = _time_block_sections(clean_lines, 600)
    sections = _build_sections(clean_lines, bounds)
    seg_points = [s["title"] for s in sections if s.get("title")]

    return {
        "raw_lines": raw_lines,
        "clean_lines": clean_lines,
        "summary": sm["summary"],
        "points": seg_points or sm["points"],
        "sections": sections,
        "llm_used": bool(cfg),
        "llm_model": (cfg.get("model") if cfg else None),
        "llm_error": llm_error,
    }


# ── 导出 ──
def to_markdown(meta: dict, result: dict, today: str) -> str:
    from .sources._common import fmt_duration
    fm = [
        "---",
        f"来源链接: {meta.get('url','')}",
        f"平台: {meta.get('platform','')}",
        f"节目: {meta.get('show','')}",
        f"单集: {meta.get('title','')}",
        f"时长: {fmt_duration(meta.get('duration',0))}",
        f"发布日期: {meta.get('date','')}",
        f"转录时间: {today}",
        "---", "",
    ]
    body = []
    if result.get("summary"):
        body += ["## 摘要", "", result["summary"], ""]
    if result.get("points"):
        body += ["## 要点", ""] + [f"- {p}" for p in result["points"]] + [""]
    body += ["## 逐字稿", ""]
    secs = result.get("sections") or []
    if secs:
        for sct in secs:
            head = f"### [{sct['ts']}]" + (f" {sct['title']}" if sct.get("title") else "")
            body += [head, ""]
            for para in (sct.get("paras") or [sct["text"]]):
                body += [para, ""]
    else:
        for ln in result["clean_lines"]:
            m = TS_LINE.match(ln)
            body.append(f"{m.group(1)} {m.group(2)}" if m else ln)
    return "\n".join(fm + body) + "\n"


def to_txt(result: dict) -> str:
    lines = []
    if result.get("summary"):
        lines += [result["summary"], ""]
    secs = result.get("sections") or []
    if secs:
        for sct in secs:
            if sct.get("title"):
                lines += [f"[{sct['ts']}] {sct['title']}"]
            for para in (sct.get("paras") or [sct["text"]]):
                lines += [para]
            lines += [""]
    else:
        for ln in result["clean_lines"]:
            m = TS_LINE.match(ln)
            lines.append(m.group(2) if m else ln)
    return "\n".join(lines) + "\n"


def _srt_ts(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: list[tuple[float, str]], clean_lines: list[str]) -> str:
    # 用清洗后的文字 + 原 segment 时间区间
    texts = []
    for ln in clean_lines:
        m = TS_LINE.match(ln)
        texts.append(m.group(2) if m else ln)
    if len(texts) != len(segments):
        texts = [t for _, t in segments]
    out = []
    for i, (start, _) in enumerate(segments):
        end = segments[i + 1][0] if i + 1 < len(segments) else start + 4
        out += [str(i + 1), f"{_srt_ts(start)} --> {_srt_ts(end)}", texts[i], ""]
    return "\n".join(out)
