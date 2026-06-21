"""开源版默认引擎：faster-whisper（离线免费，clone 后自动下模型）。"""
from __future__ import annotations

from pathlib import Path

_MODEL_CACHE: dict = {}


def run(audio: Path, model_name: str = "small") -> list[tuple[float, str]]:
    from faster_whisper import WhisperModel

    model = _MODEL_CACHE.get(model_name)
    if model is None:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        _MODEL_CACHE[model_name] = model
    segments, _info = model.transcribe(
        str(audio), language="zh", vad_filter=True,
        initial_prompt="以下是简体中文的播客对话内容。")
    return [(s.start, s.text.strip()) for s in segments if s.text.strip()]
