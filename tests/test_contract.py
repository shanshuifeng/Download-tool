#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_contract.py —— 校验器自身的测试

安全网自己不能是纸糊的。这里只验三件事：
  1. 未知检查类型必须判失败（而不是静默 SKIP）
  2. 标了「已完成」但没挂测试的需求必须被点名
  3. 字典值是非字面量（如 os.path.join）时不能崩 —— 这里曾经崩过一次
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "docs"))

import verify_contract as vc  # noqa: E402


class ContractToolTest(unittest.TestCase):
    def setUp(self):
        vc._results.clear()

    def test_skip_counts_as_failure(self):
        """REQ-020 SKIP 不计入失败的话，写错一个 type 就等于没有检查。"""
        vc.record("x.md", "typo", "y", vc.C_SKIP, "未知类型")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = vc.report(False, False)
        self.assertEqual(rc, 1)

    def test_req_without_test_is_flagged(self):
        """REQ-020 已完成但没挂测试的需求必须报红。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "REQ.md").write_text(
            "| REQ-999 | 假需求 | 来源 | 验收 | 契约 | 已完成 2026-10-31 |\n",
            encoding="utf-8")
        old, vc.DOCS = vc.DOCS, tmp
        try:
            vc.chk_req_tests("t.md", {"req": "REQ.md",
                                      "tests": ["tests/test_engine.py"]})
        finally:
            vc.DOCS = old
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("REQ-999", vc._results[-1]["detail"])

    def test_req_test_without_marker_is_flagged(self):
        """REQ-020 映射表挂了测试，但测试体内没写 REQ 编号，也要报红。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "REQ.md").write_text(
            "| REQ-999 | 假需求 | 来源 | 验收 | 契约 | 已完成 |\n"
            "| REQ-999 | test_backoff |\n",
            encoding="utf-8")
        old, vc.DOCS = vc.DOCS, tmp
        try:
            vc.chk_req_tests("t.md", {"req": "REQ.md",
                                      "tests": ["tests/test_engine.py"]})
        finally:
            vc.DOCS = old
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("没有声明", vc._results[-1]["detail"])

    def test_dict_keys_tolerates_non_literal(self):
        """DEFAULTS 里有 os.path.join(...)，不能整体 literal_eval。"""
        keys = vc._dict_keys(ROOT / "src" / "gui.pyw", "DEFAULTS")
        self.assertIsInstance(keys, set)
        self.assertIn("last_dir", keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
