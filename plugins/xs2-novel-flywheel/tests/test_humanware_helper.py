"""Regression checks for the humanware_helper CLI contract.

Executes the command functions in-process (capturing stdout) against
temporary workspaces; no model calls. Long-content paths additionally run
the real CLI file through a subprocess (contract v3 “-” stdin convention).
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / "resources" / "script-library" / "xs2" / "humanware_helper"


def load_cli():
    spec = importlib.util.spec_from_file_location("humanware_helper", BASE / "humanware_helper.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = load_cli()


class _FakeStdin:
    """sys.stdin 替身：.buffer.read() 返回预设 UTF-8 字节（“-” 约定）。"""

    def __init__(self, text: str):
        self.buffer = io.BytesIO(text.encode("utf-8"))


def run(cmd, *args, stdin_text: str | None = None) -> dict:
    buf = io.StringIO()
    if stdin_text is not None:
        with patch("sys.stdin", _FakeStdin(stdin_text)), redirect_stdout(buf):
            cmd(*args)
    else:
        with redirect_stdout(buf):
            cmd(*args)
    return json.loads(buf.getvalue())


class GenerateVoiceTests(unittest.TestCase):
    def _workspace(self, tmp: Path, profiles: str) -> Path:
        meta = tmp / "meta"
        meta.mkdir(parents=True)
        (meta / "character_profiles.md").write_text(profiles, encoding="utf-8", newline="\n")
        return tmp

    def test_generate_creates_anchors_for_each_character(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            root = self._workspace(tmp, "## 林晚\n性格：冷静。\n\n## 阿柴\n性格：活泼。\n")
            result = run(cli.cmd_generate_voice, root)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["character_count"], 2)
            voice = (root / "meta" / "character_voice.md").read_text(encoding="utf-8")
            self.assertIn("## 林晚", voice)
            self.assertIn("## 阿柴", voice)
            self.assertIn("### 句法指纹", voice)

    def test_generate_requires_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run(cli.cmd_generate_voice, root)
            self.assertEqual(result["code"], 409)

    def test_generate_rejects_profiles_without_headings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory), "没有标题的档案内容")
            result = run(cli.cmd_generate_voice, root)
            self.assertEqual(result["code"], 409)


class AnalyzeVoiceTests(unittest.TestCase):
    def test_analyze_derives_fingerprints_from_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ref = root / "references"
            ref.mkdir(parents=True)
            (ref / "sample.md").write_text(
                '## 林晚\n\n"调查结果已经确认。"\n"先冷静一下。"\n',
                encoding="utf-8", newline="\n",
            )
            result = run(cli.cmd_analyze_voice, root)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["character_count"], 1)
            voice = (root / "meta" / "character_voice.md").read_text(encoding="utf-8")
            self.assertIn("## 林晚", voice)

    def test_analyze_requires_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run(cli.cmd_analyze_voice, root)
            self.assertEqual(result["code"], 409)


class ScoreTextTests(unittest.TestCase):
    def _voice(self, tmp: Path) -> Path:
        meta = tmp / "meta"
        meta.mkdir(parents=True)
        (meta / "character_voice.md").write_text(
            "# 角色声音锚点\n\n## 林晚\n\n"
            "### 核心声音定位\n- **表达方式**: 冷静克制\n\n"
            "### 句法指纹\n- **平均句长**: 14\n- **问句倾向**: 0.15\n- **叹句倾向**: 0.10\n\n"
            "### 口头禅\n- 用词: \n\n### 绝不使用\n- 用词: 傻瓜\n\n",
            encoding="utf-8", newline="\n",
        )
        return tmp

    def test_score_text_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            result = run(cli.cmd_score_text, root, "林晚", "结论已经给出，方案可以执行。")
            self.assertEqual(result["status"], "success")
            self.assertEqual(set(result["detailed_scores"]), {
                "声音一致性", "对话自然度", "情感真实度", "行为一致性"})
            self.assertIn(result["grade"], "ABCDF")
            self.assertIsInstance(result["issues"], list)
            self.assertIsInstance(result["recommendation"], str)

    def test_score_text_banned_word_reduces_score(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            result = run(cli.cmd_score_text, root, "林晚", "你这个傻瓜，别说了！")
            self.assertTrue(any(
                item.get("type") == "banned_word" for item in result["issues"]))

    def test_score_text_unknown_character_is_409(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            result = run(cli.cmd_score_text, root, "不存在的人", "你好。")
            self.assertEqual(result["code"], 409)

    def test_score_text_dash_arg_reads_content_from_stdin(self):
        # 契约 v3：content 为 "-" 时从 stdin 读真实内容（超长内容通道）
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            result = run(cli.cmd_score_text, root, "林晚", "-",
                         stdin_text="结论已经给出，方案可以执行。")
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["character"], "林晚")

    def test_calm_character_calm_line_keeps_high_emotion(self):
        # 回归：冷静角色平稳表达不应因"无语气起伏"被过度扣分（修复前 ≈55）。
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            result = run(cli.cmd_score_text, root, "林晚", "结论已经给出，方案可以执行。")
            self.assertGreaterEqual(result["detailed_scores"]["情感真实度"], 85)

    def test_calm_character_outburst_scores_much_lower(self):
        # 冷静角色情绪爆发应被明显扣分（向上发散重罚）。
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            calm = run(cli.cmd_score_text, root, "林晚", "结论已经给出，方案可以执行。")
            spike = run(cli.cmd_score_text, root, "林晚", "凭什么！我绝不允许！快收手！")
            self.assertGreater(
                calm["detailed_scores"]["情感真实度"],
                spike["detailed_scores"]["情感真实度"] + 40,
            )
            self.assertTrue(any(i.get("type") == "tone_spike" for i in spike["issues"]))


class ScoreChapterTests(unittest.TestCase):
    def _workspace(self, tmp: Path) -> Path:
        meta = tmp / "meta"
        meta.mkdir(parents=True)
        (meta / "character_voice.md").write_text(
            "# 角色声音锚点\n\n## 林晚\n\n### 句法指纹\n- **平均句长**: 14\n- **问句倾向**: 0.15\n- **叹句倾向**: 0.10\n\n",
            encoding="utf-8", newline="\n",
        )
        story = tmp / "story" / "0001"
        story.mkdir(parents=True)
        (story / "chapter.md").write_text(
            '林晚说："结论已经给出。"\n阿柴说："太棒了！"\n',
            encoding="utf-8", newline="\n",
        )
        return tmp

    def test_score_chapter_aggregates_dialogue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            result = run(cli.cmd_score_chapter, root, "story/0001/chapter.md")
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["dialogues_scored"], 2)
            self.assertIn("total_score", result)

    def test_score_chapter_rejects_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            result = run(cli.cmd_score_chapter, root, "../secret.md")
            self.assertEqual(result["code"], 400)

    def test_score_chapter_missing_file_is_404(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            result = run(cli.cmd_score_chapter, root, "story/0001/none.md")
            self.assertEqual(result["code"], 404)


class CheckDialogueTests(unittest.TestCase):
    def _voice(self, tmp: Path) -> Path:
        meta = tmp / "meta"
        meta.mkdir(parents=True)
        (meta / "character_voice.md").write_text(
            "# 角色声音锚点\n\n## 林晚\n\n"
            "### 句法指纹\n- **平均句长**: 14\n- **问句倾向**: 0.15\n- **叹句倾向**: 0.10\n\n"
            "### 口头禅\n- 用词: 罢了\n\n### 绝不使用\n- 用词: 傻瓜\n\n",
            encoding="utf-8", newline="\n",
        )
        return tmp

    def test_matching_dialogue_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            result = run(cli.cmd_check_dialogue, root, "林晚", "此事罢了，不必再提。")
            self.assertTrue(result["matches"])

    def test_no_tone_word_hit_does_not_claim_tone_hit(self):
        # 回归：无违规且未命中口头禅时，suggestion 不得谎称「已命中口头禅」
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            result = run(cli.cmd_check_dialogue, root, "林晚", "先确认现场，再下结论。")
            self.assertTrue(result["matches"])
            self.assertNotIn("已命中口头禅", result["suggestion"])
            self.assertEqual(result["suggestion"], "符合定义，保持。")

    def test_tone_word_hit_suggestion_mentions_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            result = run(cli.cmd_check_dialogue, root, "林晚", "此事罢了，不必再提。")
            self.assertTrue(result["matches"])
            self.assertEqual(result["suggestion"], "已命中口头禅，语气一致。")

    def test_banned_word_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            result = run(cli.cmd_check_dialogue, root, "林晚", "你这个傻瓜！")
            self.assertFalse(result["matches"])
            self.assertTrue(any(v["rule"] == "绝不使用" for v in result["violations"]))


class StdinConventionSubprocessTests(unittest.TestCase):
    """真实子进程验证契约 v3 的 “-” stdin 通道（Windows 命令行上限规避）。"""

    def _voice(self, tmp: Path) -> Path:
        meta = tmp / "meta"
        meta.mkdir(parents=True)
        (meta / "character_voice.md").write_text(
            "# 角色声音锚点\n\n## 林晚\n\n### 句法指纹\n"
            "- **平均句长**: 14\n- **问句倾向**: 0.15\n- **叹句倾向**: 0.10\n\n",
            encoding="utf-8", newline="\n",
        )
        return tmp

    def _run_cli(self, *args: str, stdin_text: str) -> dict:
        proc = subprocess.run(
            [sys.executable, str(BASE / "humanware_helper.py"), *args],
            input=stdin_text.encode("utf-8"),
            capture_output=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "ignore"))
        return json.loads(proc.stdout.decode("utf-8"))

    def test_score_text_long_content_over_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            long_content = "结论已经给出，方案可以执行。" * 3000  # 42,000 字符
            result = self._run_cli(
                "score-text", str(root), "林晚", "-", stdin_text=long_content)
            self.assertEqual(result["status"], "success")
            self.assertIn("total_score", result)

    def test_check_dialogue_stdin_over_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._voice(Path(directory))
            result = self._run_cli(
                "check-dialogue", str(root), "林晚", "-",
                stdin_text="此事罢了，不必再提。")
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["matches"])


if __name__ == "__main__":
    unittest.main()