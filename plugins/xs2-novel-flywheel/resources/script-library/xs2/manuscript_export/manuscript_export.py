"""Assemble chapter markdown files into a portable manuscript artifact."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


class EmptyManuscriptError(RuntimeError):
    """本书没有任何非空章节可导出（R37 B25）。"""


def chapter_key(path: Path) -> tuple[int, str]:
    stem = path.parent.name
    try:
        return int(stem), stem
    except ValueError:
        return 10**9, stem


def build_manuscript(output: str, manifest: str) -> dict[str, object]:
    root = Path.cwd()
    chapters = sorted((root / "story").glob("*/chapter.md"), key=chapter_key)
    sections: list[str] = []
    exported: list[dict[str, object]] = []
    for path in chapters:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        chapter = path.parent.name
        sections.append(f"# 第{chapter}章\n\n{content}")
        exported.append({"chapter": chapter, "path": path.relative_to(root).as_posix(), "characters": len(content)})
    if not exported:
        # R37 B25：0 章时必须失败而不是写出 0 字节稿件 + 「chapter_count: 0」
        # 的诚实谎报——下游 can_download 只看 manuscript.md 是否存在，空稿件
        # 会让用户下载到一份空文件。
        raise EmptyManuscriptError(
            "没有可导出的章节：story/*/chapter.md 不存在或全部为空，已拒绝生成空稿件")
    target = root / output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n\n---\n\n".join(sections) + "\n", encoding="utf-8")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output": target.relative_to(root).as_posix(),
        "chapter_count": len(exported),
        "chapters": exported,
    }
    manifest_path = root / manifest
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--output", default="export/manuscript.md")
    build.add_argument("--manifest", default="export/manifest.json")
    args = parser.parse_args()
    if args.command == "build":
        try:
            report = build_manuscript(args.output, args.manifest)
        except EmptyManuscriptError as exc:
            print(f"导出终止：{exc}", file=sys.stderr)
            return 2
        print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
