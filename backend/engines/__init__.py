"""转录引擎：音频 → [(start_seconds, text), ...]（无标点原始稿）。

转录恒本地、离线免费、不上传，无云端 ASR：
  - "local"/"whisper"/"auto"  faster-whisper（离线免费，clone 后自动下模型）
"""
from __future__ import annotations

from pathlib import Path


def transcribe(audio: Path, engine: str = "auto", *,
               whisper_model: str = "small") -> list[tuple[float, str]]:
    if engine in ("auto", "local", "whisper"):
        from . import whisper_local
        return whisper_local.run(audio, whisper_model)
    raise RuntimeError(f"未知转录引擎: {engine}（仅本地 faster-whisper，无云端 ASR）")
