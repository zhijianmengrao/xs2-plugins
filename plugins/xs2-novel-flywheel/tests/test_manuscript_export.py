"""R37 B25：空书导出必须失败，不得产出 0 字节稿件。

修复前（R33 C2 / R37 活体 8021 复现）：0 章时导出任务 completed，
export/manuscript.md 为 0 字节、manifest 记 chapter_count: 0；下游
can_download 只看 manuscript.md 是否存在，用户会下载到空文件。
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'resources/script-library/xs2/manuscript_export/manuscript_export.py'
spec = importlib.util.spec_from_file_location('test_manuscript_export', MODULE)
manuscript_export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manuscript_export)


def write_chapter(root: Path, chapter: str, content: str) -> None:
    path = root / 'story' / chapter / 'chapter.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def test_empty_book_refuses_to_write_artifacts(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(manuscript_export.EmptyManuscriptError, match='没有可导出的章节'):
        manuscript_export.build_manuscript('export/manuscript.md', 'export/manifest.json')
    assert not (tmp_path / 'export').exists()


def test_empty_book_cli_exits_nonzero_with_reason(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.argv', ['manuscript_export.py', 'build'])
    rc = manuscript_export.main()
    # CLI 形态（引擎按 stderr 首行透出任务错误）：非零退出 + 中文拒因
    assert rc == 2
    assert '没有可导出的章节' in capsys.readouterr().err


def test_blank_chapters_count_as_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_chapter(tmp_path, '0001', '   \n\t')
    with pytest.raises(manuscript_export.EmptyManuscriptError):
        manuscript_export.build_manuscript('export/manuscript.md', 'export/manifest.json')
    assert not (tmp_path / 'export').exists()


def test_non_empty_book_still_exports_and_skips_blank_chapters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_chapter(tmp_path, '0001', '第一章正文')
    write_chapter(tmp_path, '0002', '')
    write_chapter(tmp_path, '0003', '第三章正文')
    report = manuscript_export.build_manuscript('export/manuscript.md', 'export/manifest.json')
    assert report['chapter_count'] == 2
    assert [item['chapter'] for item in report['chapters']] == ['0001', '0003']
    manuscript = (tmp_path / 'export/manuscript.md').read_text(encoding='utf-8')
    assert '# 第0001章' in manuscript and '# 第0003章' in manuscript
    manifest = json.loads((tmp_path / 'export/manifest.json').read_text(encoding='utf-8'))
    assert manifest['chapter_count'] == 2
