"""PodScript 版本 B · FastAPI。

POST /transcribe {url, punctuate, summary, vault?, api_key?, api_base?, api_model?}
  转录恒本地（faster-whisper）；api_* 仅接清洗+摘要的 OpenAI 兼容 LLM。
  → {meta, summary, points, lines:[{ts,text}], saved_path, exports:{md,txt,srt}}
GET /            → web/index.html（定稿前端）
GET /health      → {ok:true}
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import config, core, pipeline

app = FastAPI(title="PodScript", version="0.1")
WEB_DIR = config.PROJECT_ROOT / "web"


class TranscribeReq(BaseModel):
    url: str
    engine: str = "auto"           # 转录恒本地（faster-whisper）；不再有云端 ASR
    punctuate: bool = True
    summary: bool = True
    llm: bool = True               # 前端模式：接大模型=True，本地=False（False 时连环境变量里的 key 也不使用）
    api_key: str | None = None     # 「自带 KEY」：仅用于清洗+摘要 LLM（OpenAI 兼容），不碰转录
    api_base: str | None = None    # OpenAI 兼容 base_url（DeepSeek/Kimi/GLM）
    api_model: str | None = None   # 模型名
    whisper_model: str = "small"
    vault: str | None = None       # 落点：前端存 localStorage 传来；空则用默认 ./output


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    f = WEB_DIR / "index.html"
    if not f.exists():
        raise HTTPException(404, "前端文件缺失")
    return FileResponse(f)


@app.post("/transcribe")
def transcribe(req: TranscribeReq):
    try:
        out = core.run(
            req.url,
            engine="local",                      # 转录恒本地 faster-whisper
            punctuate=req.punctuate, summary=req.summary, allow_llm=req.llm,
            whisper_model=req.whisper_model,
            llm_key=req.api_key, llm_base=req.api_base, llm_model=req.api_model,
        )
    except Exception as e:
        raise HTTPException(422, f"转写失败: {e}")

    meta, result, segments = out["meta"], out["result"], out["segments"]
    today = datetime.date.today().isoformat()
    from .sources._common import fmt_duration

    lines = []
    for ln in result["clean_lines"]:
        m = pipeline.TS_LINE.match(ln)
        if m:
            lines.append({"ts": m.group(1).strip("[]"), "text": m.group(2)})

    md = pipeline.to_markdown(meta, result, today)

    # 落点：用户填的目录写盘并回报绝对路径；没填用项目默认 ./output。
    vault = Path(os.path.expanduser(req.vault)) if req.vault else config.DEFAULT_OUTPUT
    saved_path, save_error = None, None
    try:
        vault.mkdir(parents=True, exist_ok=True)
        fname = f"{core._safe(meta.get('show',''), 24)}-{core._safe(meta.get('title',''), 40)}.md"
        dest = vault / fname
        dest.write_text(md, encoding="utf-8")
        saved_path = str(dest.resolve())
    except Exception as e:
        save_error = str(e)

    return JSONResponse({
        "meta": {
            "platform": meta.get("platform", ""), "show": meta.get("show", ""),
            "title": meta.get("title", ""), "duration": fmt_duration(meta.get("duration", 0)),
            "date": meta.get("date", ""), "url": meta.get("url", ""),
        },
        "summary": result.get("summary", ""),
        "points": result.get("points", []),
        "sections": result.get("sections", []),
        "llm_used": result.get("llm_used", False),
        "llm_model": result.get("llm_model"),
        "llm_error": result.get("llm_error"),
        "lines": lines,
        "saved_path": saved_path,
        "save_error": save_error,
        "exports": {
            "md": md,
            "txt": pipeline.to_txt(result),
            "srt": pipeline.to_srt(segments, result["clean_lines"]),
        },
    })
