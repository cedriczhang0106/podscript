"""说话人分离（可选 · pyannote.audio）。

默认不启用：只有前端勾选「区分说话人」且配置了 HuggingFace token 时才会用到，
因此 torch / pyannote 都是**懒加载**——不开启分离的用户完全不引入这些重依赖。

启用前提（一次性）：
  1. pip install -r requirements-diarize.txt   # 装 pyannote.audio（含 torch）
  2. 到 hf.co/settings/tokens 建一个 token
  3. 在 https://huggingface.co/pyannote/speaker-diarization-3.1 接受模型许可
  4. 设环境变量： export HF_TOKEN=hf_xxx
"""
from __future__ import annotations


def diarize(audio_path, token: str, progress=None) -> list[tuple[float, float, str]]:
    """对音频做说话人分离，返回 [(start, end, 'SPEAKER_xx'), ...]（按开始时间排序）。

    失败直接抛异常，由调用方捕获并降级 + 提示原因。
    """
    if not token:
        raise RuntimeError("缺少 HuggingFace token（设 HF_TOKEN 环境变量；并需接受 pyannote 模型许可）")
    from pyannote.audio import Pipeline   # 懒加载（重依赖，仅启用分离时引入）
    import torch

    # pyannote.audio 4.x 用 token=，3.x 用 use_auth_token=；两者都试一下
    try:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=token)
    except TypeError:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
    if pipe is None:
        raise RuntimeError("pyannote 模型加载失败：请确认 token 有效、且已在网页接受 "
                           "pyannote/speaker-diarization-3.1 的模型许可")
    # 设备：优先 CUDA，其次 Apple MPS，最后 CPU
    try:
        if torch.cuda.is_available():
            pipe.to(torch.device("cuda"))
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            pipe.to(torch.device("mps"))
    except Exception:
        pass  # 设备切换失败就用默认 CPU

    result = pipe(str(audio_path))
    # pyannote 4.x 把结果包成 DiarizeOutput（Annotation 在 .speaker_diarization 等字段里）；
    # 3.x 直接返回 Annotation。两种都兼容。
    annotation = result
    if not hasattr(annotation, "itertracks"):
        for attr in ("speaker_diarization", "diarization", "annotation"):
            cand = getattr(result, attr, None)
            if cand is not None and hasattr(cand, "itertracks"):
                annotation = cand
                break
    if not hasattr(annotation, "itertracks"):
        raise RuntimeError(f"无法解析分离输出（类型 {type(result).__name__}）；"
                           f"pyannote 版本接口可能又变了，把这条发给作者")
    turns = [(float(seg.start), float(seg.end), str(spk))
             for seg, _, spk in annotation.itertracks(yield_label=True)]
    turns.sort(key=lambda x: x[0])
    return turns


def assign(segments: list[tuple[float, str]],
           turns: list[tuple[float, float, str]]) -> list[str] | None:
    """给每个转录 segment 配一个说话人：取与该段时间区间重叠最多的说话人。

    返回与 segments 等长的标签列表，标签为「说话人1 / 说话人2 …」（按出现先后编号）；
    没有分离结果则返回 None。
    """
    if not turns:
        return None
    label_map: dict[str, str] = {}

    def disp(spk: str) -> str:
        if spk not in label_map:
            label_map[spk] = f"说话人{len(label_map) + 1}"
        return label_map[spk]

    n = len(segments)
    out: list[str] = []
    for i, (start, _text) in enumerate(segments):
        end = segments[i + 1][0] if i + 1 < n else start + 4.0
        best, best_ov = None, 0.0
        for ts, te, spk in turns:
            ov = min(end, te) - max(start, ts)
            if ov > best_ov:
                best_ov, best = ov, spk
        out.append(disp(best) if best is not None else "")
    return out
