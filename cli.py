#!/usr/bin/env python3
"""PodScript · 命令行入口。

    python cli.py <url> [--vault DIR] [--whisper-model small]
                  [--no-summary] [--no-punctuate] [--keep-audio]

默认：本地 faster-whisper 转录、首次问一次落点（之后复用）、
转录后删音频、原始稿留档。
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

from backend import config, core, pipeline


def _safe(name: str, maxlen: int = 40) -> str:
    return core._safe(name, maxlen)


def resolve_vault(cli_vault: str | None) -> Path:
    """落点解析：--vault 临时覆盖 > 已存配置 > 首次交互问一次并存盘。

    工具不替用户猜落点。非交互（无 tty）且无配置时退回默认 ./output 并提示，不卡住。
    """
    if cli_vault:                                   # 本次临时覆盖，不写配置
        return Path(os.path.expanduser(cli_vault))
    saved = config.configured_vault()
    if saved:                                       # 复用已存落点
        return saved
    default = config.DEFAULT_VAULT                  # 默认建议（./output）
    if not sys.stdin.isatty():                      # 非交互：用默认、不卡住
        print(f"[PodScript] 未配置落点且非交互环境 → 用默认 {default}\n"
              f"            （想固定到自己的 vault：python cli.py <url> --vault <dir>）",
              file=sys.stderr)
        return config.set_configured_vault(default)
    print("\n[PodScript] 首次运行——转录稿要落到哪个文件夹？", file=sys.stderr)
    ans = input(f"  文件夹路径（直接回车用默认 {default}）\n  > ").strip()
    chosen = config.set_configured_vault(ans or default)
    print(f"  已记住落点：{chosen}（以后不再问；改用 --vault 临时覆盖，"
          f"或编辑 {config.USER_CONFIG}）\n", file=sys.stderr)
    return chosen


def main() -> None:
    ap = argparse.ArgumentParser(description="PodScript · 播客转写")
    ap.add_argument("url", help="小宇宙 / 苹果播客 / B站 链接")
    ap.add_argument("--vault", default=None, help="落库目录（本次临时覆盖，不写入配置）")
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--no-summary", action="store_true")
    ap.add_argument("--no-punctuate", action="store_true")
    ap.add_argument("--keep-audio", action="store_true")
    args = ap.parse_args()

    vault = resolve_vault(args.vault)
    vault.mkdir(parents=True, exist_ok=True)

    today = datetime.date.today().isoformat()
    print(f"[PodScript] 处理 {args.url}", file=sys.stderr)

    out = core.run(
        args.url, engine="local", punctuate=not args.no_punctuate,
        summary=not args.no_summary, whisper_model=args.whisper_model,
        keep_audio=args.keep_audio,
        progress=lambda s: print(f"  · {s}…", file=sys.stderr, flush=True),
    )
    meta, result = out["meta"], out["result"]

    md = pipeline.to_markdown(meta, result, today)
    fname = f"{_safe(meta.get('show',''), 24)}-{_safe(meta.get('title',''), 40)}.md"
    dest = vault / fname
    dest.write_text(md, encoding="utf-8")

    print(f"\n落库: {dest}", file=sys.stderr)
    print("\n".join(md.splitlines()[:14]))


if __name__ == "__main__":
    main()
