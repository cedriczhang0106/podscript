"""编排：URL → 下载 → 转录 → 清洗 → 结果。CLI 与 Web 共用。

各步独立 try（健壮性）：一步失败保住已下音频和 raw 稿。
原始带时间戳稿存 <workdir>/_raw_podcast/，重清洗不用重下。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config, pipeline
from .engines import transcribe as run_engine
from .sources import resolve_source


def _safe(name: str, maxlen: int = 40) -> str:
    name = re.sub(r'[/\\:*?"<>|#\[\]\n\r\t]', "", name or "").strip()
    return name[:maxlen] or "未命名"


def run(url: str, *, engine: str = "auto", punctuate: bool = True, summary: bool = True,
        whisper_model: str = "small", llm_key: str | None = None,
        llm_base: str | None = None, llm_model: str | None = None,
        workdir: Path | None = None, keep_audio: bool = False,
        progress=None) -> dict:
    """返回 {meta, result, segments, raw_path}。"""
    def emit(step):
        if progress:
            progress(step)

    workdir = Path(workdir or (config.PROJECT_ROOT / ".work"))
    workdir.mkdir(parents=True, exist_ok=True)
    raw_dir = workdir / config.RAW_DIRNAME
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 1. 下载
    emit("下载音频")
    meta = resolve_source(url, workdir)
    audio = meta["audio_path"]

    try:
        # 2. 转录
        emit("语音转录")
        segments = run_engine(audio, engine, whisper_model=whisper_model)
        if not segments:
            raise RuntimeError("转录结果为空（未识别到语音）")

        # 原始稿留档（去清洗前）
        stem = _safe(f"{meta.get('show','')}-{meta.get('title','')}")
        raw_path = raw_dir / f"{stem}.raw.json"
        raw_path.write_text(json.dumps({
            "meta": {k: (str(v) if isinstance(v, Path) else v) for k, v in meta.items()},
            "segments": [{"start": round(t, 2), "text": x} for t, x in segments],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        # 3. 清洗 + 提炼
        emit("清洗与摘要")
        result = pipeline.process(segments, punctuate=punctuate, summary=summary,
                                  llm_key=llm_key, llm_base=llm_base, llm_model=llm_model)
        return {"meta": meta, "result": result, "segments": segments, "raw_path": raw_path}
    finally:
        # 4. 文本优先：删音频（除非显式保留）
        if not keep_audio:
            try:
                audio.unlink(missing_ok=True)
            except Exception:
                pass
