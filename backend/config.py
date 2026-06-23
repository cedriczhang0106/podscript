"""集中配置：路径、引擎、LLM key 的解析。

设计原则：零配置可跑（faster-whisper 离线转录 + 不强制 LLM key）。
所有可调项都能被环境变量覆盖，便于 clone 后改成自己的路径。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HOME = Path.home()

# 项目自身目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "output"   # 没设落点时默认写这
RAW_DIRNAME = "_raw_podcast"               # 原始带时间戳稿留档子目录（重清洗不用重下）

# 默认落库目录建议（首次提问时回车的默认值；用 --vault 或 PODSCRIPT_VAULT 覆盖）
DEFAULT_VAULT = Path(os.environ.get("PODSCRIPT_VAULT", str(DEFAULT_OUTPUT)))

# ── 用户落点配置（工具不替你猜落点，首次问一次、存盘复用、可改）──
USER_CONFIG = Path(os.environ.get("PODSCRIPT_CONFIG", str(HOME / ".podscript" / "config.json")))


def load_user_config() -> dict:
    try:
        return json.loads(USER_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_user_config(data: dict) -> None:
    USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def configured_vault() -> Path | None:
    """已存盘的落点（没存过返回 None，由调用方决定问/默认）。"""
    v = load_user_config().get("vault")
    return Path(os.path.expanduser(v)) if v else None


def set_configured_vault(path: str | Path) -> Path:
    p = Path(os.path.expanduser(str(path)))
    cfg = load_user_config()
    cfg["vault"] = str(p)
    save_user_config(cfg)
    return p


def llm_config(explicit_key: str | None = None,
               explicit_base: str | None = None,
               explicit_model: str | None = None) -> dict | None:
    """解析 LLM（清洗/摘要）配置，按优先级：

    1. 显式传入的 key（前端「自带 KEY」）→ 当 OpenAI 兼容端点用。
       前端同时可传 base_url + model（DeepSeek / Kimi / GLM 等国产模型也兼容），
       三家都是标准 OpenAI /chat/completions 协议，只换 base/model/key，无需厂商分支。
    2. 环境 OPENAI_API_KEY (+OPENAI_BASE_URL/OPENAI_MODEL)
    3. 环境 DEEPSEEK_API_KEY

    返回 {base_url, key, model}；都没有则 None（调用方降级到正则清洗、不出摘要）。
    """
    if explicit_key:
        return {
            "base_url": explicit_base or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "key": explicit_key,
            "model": explicit_model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        }
    if os.environ.get("OPENAI_API_KEY"):
        return {
            "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "key": os.environ["OPENAI_API_KEY"],
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        }
    if os.environ.get("DEEPSEEK_API_KEY"):
        return {
            "base_url": "https://api.deepseek.com",
            "key": os.environ["DEEPSEEK_API_KEY"],
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        }
    return None


def hf_token() -> str | None:
    """HuggingFace token（说话人分离用）：按 HF_TOKEN / HUGGINGFACE_TOKEN / PYANNOTE_TOKEN 取。"""
    import os
    return (os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
            or os.environ.get("PYANNOTE_TOKEN") or None)
