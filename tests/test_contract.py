#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_contract.py —— 校验器自身的测试

安全网自己不能是纸糊的。这里只验三件事：
  1. 未知检查类型必须判失败（而不是静默 SKIP）
  2. 标了「已完成」但没挂测试的需求必须被点名
  3. 字典值是非字面量（如 os.path.join）时不能崩 —— 这里曾经崩过一次

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import re
import subprocess
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

    def test_markdown_fences_balanced(self):
        """文档的代码围栏必须成对：多一个 ``` 会让后面整段在 GitHub 上渲染成代码块。"""
        fence = chr(96) * 3
        paths = [ROOT / "README.md", ROOT / "使用说明.txt"]
        paths += sorted((ROOT / "docs").glob("*.md"))
        bad = []
        for path in paths:
            if not path.exists():
                continue
            n = sum(1 for line in path.read_text(encoding="utf-8").splitlines()
                    if line.startswith(fence))
            if n % 2:
                bad.append(f"{path.name}（{n} 个围栏）")
        self.assertEqual(bad, [], f"围栏不配对：{bad}")

    # ---------------- 契约块本身的完整性 ----------------

    def test_contract_blocks_have_no_duplicate_keys(self):
        """CODE-010 契约块不得有重复键：json.loads 对同名键后者静默覆盖前者，意图会被掩盖。"""
        blocks = re.compile(r"```contract\s*\n(.*?)\n```", re.S)
        dups = []

        def hook(pairs):
            seen = set()
            for k, _ in pairs:
                if k in seen:
                    dups.append(f"{path.name} 的第 {i} 个 contract 块有重复键 {k!r}")
                seen.add(k)
            return dict(pairs)

        for path in sorted((ROOT / "docs").glob("CONTRACT-*.md")):
            for i, raw in enumerate(blocks.findall(path.read_text(encoding="utf-8")), 1):
                json.loads(raw, object_pairs_hook=hook)
        self.assertEqual(dups, [], f"契约块有重复键：{dups}")

    def test_contract_call_site_entries_declared_once(self):
        """CODE-013 这几条调用点声明只能各出现一次（重复条目会被 JSON 静默覆盖）。"""
        text = "\n".join(p.read_text(encoding="utf-8")
                         for p in sorted((ROOT / "docs").glob("CONTRACT-*.md")))
        for needle in (r'"in"\s*:\s*"_measure_mirror"', r'"in"\s*:\s*"probe"',
                       r'"in"\s*:\s*"DownloadTask\._worker",\s*"call"\s*:\s*"_credited"',
                       r'"in"\s*:\s*"DownloadTask\._download_chunked",\s*"call"\s*:\s*"_credited"'):
            n = len(re.findall(needle, text))
            self.assertEqual(n, 1, f"{needle} 出现 {n} 次，应只出现 1 次")

    # ---------------- BUG-31 · 校验器自身的盲区 ----------------

    def test_bug31_const_used_detects_dead_constant(self):
        """BUG-31 只定义不读取的常量必须被判出来（否则契约在撒谎）。REQ-024 校验器盲区。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "deadmod.py").write_text(
            "USED = 1\n"
            "DEAD = 2\n"
            "def f():\n"
            "    return USED\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        try:
            vc.chk_const_used("t.md", {"module": "deadmod",
                                       "constants": ["USED", "DEAD"],
                                       "aliases": {},
                                       "files": ["deadmod.py"]})
        finally:
            vc.SRC = old_src
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("DEAD", vc._results[-1]["detail"])

    def test_bug31_const_used_accepts_used_constant(self):
        """BUG-31 真被读取的常量不得误报（零误报是这条检查的前提）。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "livemod.py").write_text(
            "USED = 1\n"
            "def f():\n"
            "    return USED\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        try:
            vc.chk_const_used("t.md", {"module": "livemod",
                                       "constants": ["USED"],
                                       "aliases": {},
                                       "files": ["livemod.py"]})
        finally:
            vc.SRC = old_src
        self.assertEqual(vc._results[-1]["state"], vc.C_OK)

    def test_bug31_private_access_detected(self):
        """BUG-31 越界访问别模块的私有符号必须报红，同模块自用要放行。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "mod_a.py").write_text("class A:\n    def _secret(self):\n        return 1\n",
                                      encoding="utf-8")
        (tmp / "mod_b.py").write_text(
            "import mod_a\n"
            "def f():\n"
            "    return mod_a.A()._secret()\n",
            encoding="utf-8")
        (tmp / "mod_c.py").write_text(
            "class C:\n"
            "    def _mine(self):\n"
            "        return 1\n"
            "    def f(self):\n"
            "        return self._mine()\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        try:
            vc.chk_no_private_access("t.md", {
                "files": ["mod_b.py", "mod_c.py"],
                "modules": ["mod_a", "mod_b", "mod_c"],
                "allow": []})
        finally:
            vc.SRC = old_src
        detail = vc._results[-1]["detail"]
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("mod_b.py", detail)
        self.assertNotIn("mod_c.py", detail, "同模块自用被误报了")

    def test_bug31_call_site_detects_missing_call(self):
        """BUG-31 契约声明的调用点不存在时必须报红，而不是静默跳过。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "site.py").write_text(
            "def helper():\n"
            "    return 1\n"
            "def target():\n"
            "    return 2\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        try:
            vc.chk_call_site("t.md", {
                "module": "site",
                "calls": [{"in": "target", "call": "helper"}]})
            self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
            self.assertIn("helper", vc._results[-1]["detail"])

            vc.chk_call_site("t.md", {
                "module": "site",
                "calls": [{"in": "nosuch", "call": "helper"}]})
        finally:
            vc.SRC = old_src
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("调用点不存在", vc._results[-1]["detail"])

    def test_bug31_max_lines_flags_undeclared_module(self):
        """BUG-31 src/ 下漏登记上限的新模块必须报红（否则完全不受约束）。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "registered.py").write_text("x = 1\n", encoding="utf-8")
        (tmp / "undeclared.py").write_text("y = 2\n", encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        try:
            vc.chk_max_lines("t.md", {"limits": {"registered.py": 100}})
        finally:
            vc.SRC = old_src
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("未定义规模上限", vc._results[-1]["detail"])

    def test_bug31_req_test_requires_docstring_marker(self):
        """BUG-31 REQ 编号必须写在 docstring 里，写在注释里不算。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "REQ.md").write_text(
            "| REQ-999 | 假需求 | 来源 | 验收 | 契约 | 已完成 |\n"
            "| REQ-999 | test_marker_in_comment |\n",
            encoding="utf-8")
        (tmp / "test_fake.py").write_text(
            "class FakeTest:\n"
            "    def test_marker_in_comment(self):\n"
            "        # REQ-999 只写在注释里\n"
            "        assert True\n",
            encoding="utf-8")
        old_docs, old_src = vc.DOCS, vc.SRC
        vc.DOCS, vc.SRC = tmp, tmp
        try:
            vc.chk_req_tests("t.md", {"req": "REQ.md", "tests": ["test_fake.py"]})
        finally:
            vc.DOCS, vc.SRC = old_docs, old_src
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("docstring", vc._results[-1]["detail"])

    # ---------------- BUG-36 · schema_version 漂移检测 ----------------

    def test_bug36_schema_version_check_detects_drift(self):
        """BUG-36 SCHEMA 的结构变了却没升版本，校验器必须报红。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "schmod.py").write_text(
            "SCHEMA = {\n"
            "    'version': 1,\n"
            "    'args': {'--x': '说明'},\n"
            "    'events': {},\n"
            "    'exit_codes': {},\n"
            "}\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        sys.path.insert(0, str(tmp))
        try:
            # 声明了错的指纹 —— 内容漂移必须报红
            vc.chk_schema_version("t.md", {
                "module": "schmod",
                "version": 2,
                "fingerprint": "d" * 64,
                "previous": {"version": 1, "fingerprint": "d" * 64}})
        finally:
            vc.SRC = old_src
            sys.path.remove(str(tmp))
            sys.modules.pop("schmod", None)
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("指纹", vc._results[-1]["detail"])

        # 形态不合法必须硬失败，不得因字段缺失就跳过判定
        vc.chk_schema_version("t.md", {
            "module": "schmod", "version": 2, "fingerprint": "d" * 64})
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("缺必需字段", vc._results[-1]["detail"])

    # ---------------- BUG-37 · progress 节流是 OR 语义 ----------------

    # ---------------- BUG-39 · 限速措辞统一 ----------------

    def test_bug39_rate_limit_wording_consistent(self):
        """BUG-39 限速语义只写一处：全部面向用户的地方都称「每任务限速」。"""
        import dl as cli

        self.assertIn("每任务限速", cli.SCHEMA["args"]["--max-speed"])
        self.assertNotIn("全局限速", cli.SCHEMA["args"]["--max-speed"])
        # argparse 的 help 文案与 SCHEMA 描述必须一致（同一事实只写一处）
        help_text = ""
        for action in cli.build_parser()._actions:
            if "--max-speed" in action.option_strings:
                help_text = action.help or ""
        self.assertIn("每任务限速", help_text)
        self.assertNotIn("全局限速", help_text)

        # 面向用户的文档不得残留旧措辞
        for rel in ("README.md", "docs/CONTRACT-cli.md", "docs/CONTRACT-data.md",
                    "docs/REQ.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("全局限速", text, f"{rel} 仍写「全局限速」")

    # ---------------- CLI-013 · 默认值只写一处 ----------------

    def test_schema_defaults_detects_duplicate_default_text(self):
        """CLI-013 args 文案里的「默认 N」是默认值重复，必须报红。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "sdmod.py").write_text(
            "SCHEMA = {\n"
            "    'version': 1,\n"
            "    'args': {'--x': '说明，默认 16', '--y': '别的，0=自动'},\n"
            "    'defaults': {'x': 16},\n"
            "}\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        sys.path.insert(0, str(tmp))
        try:
            vc.chk_schema_defaults("t.md", {
                "module": "sdmod",
                "map": {"x": "--x"},
                "pattern": r"默认\s*(\d+)",
                "must_contain": {}})
        finally:
            vc.SRC = old_src
            sys.path.remove(str(tmp))
            sys.modules.pop("sdmod", None)
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("复述", vc._results[-1]["detail"])

    def test_schema_defaults_sentinel_text_is_exempt(self):
        """CLI-013 「0=自动」是哨兵语义不是默认值重复，不得误报。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "sdmod2.py").write_text(
            "SCHEMA = {\n"
            "    'version': 1,\n"
            "    'args': {'--x': '说明，0=自动'},\n"
            "    'defaults': {'x': 0},\n"
            "}\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        sys.path.insert(0, str(tmp))
        try:
            vc.chk_schema_defaults("t.md", {
                "module": "sdmod2",
                "map": {"x": "--x"},
                "pattern": r"默认\s*(\d+)",
                "must_contain": {"x": "0=自动"}})
        finally:
            vc.SRC = old_src
            sys.path.remove(str(tmp))
            sys.modules.pop("sdmod2", None)
        self.assertEqual(vc._results[-1]["state"], vc.C_OK)

    def test_schema_version_error_reports_derived_payload_keys(self):
        """CLI-011 报红信息里的 payload 键集必须由实际 payload 派生，不得硬编码。

        诊断信息本身也是契约的一部分：键集若与实现不符，它会在说谎，
        把排查方向直接带偏（以为内容变了，实际是口径变了）。
        """
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "keymod.py").write_text(
            "SCHEMA = {'version': 1, 'args': {'--x': 'a'}, 'zzz': {}, 'aaa': 1}\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        sys.path.insert(0, str(tmp))
        try:
            vc.chk_schema_version("t.md", {
                "module": "keymod", "version": 1, "fingerprint": "a" * 64,
                "previous": {"version": 1, "fingerprint": "a" * 64}})
        finally:
            vc.SRC = old_src
            sys.path.remove(str(tmp))
            sys.modules.pop("keymod", None)
        detail = vc._results[-1]["detail"]
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("['aaa', 'args', 'zzz']", detail,
                      "payload 键集不是由实际 payload 派生的")
        self.assertNotIn("['args', 'events', 'exit_codes']", detail,
                         "报红信息里残留硬编码的旧三键")

    def test_bug37_progress_throttle_is_or_of_interval_and_delta(self):
        """BUG-37 节流判据是「间隔够长 **或** 百分比变化够大」，不是 AND。"""
        import dl as cli

        # 间隔够长 → 输出
        self.assertTrue(cli._throttle_ok(100.0, 98.5, 50.0, 50.2))
        # 百分比变化够大 → 输出
        self.assertTrue(cli._throttle_ok(100.0, 99.5, 50.0, 51.5))
        # 两者都不够 → 不输出
        self.assertFalse(cli._throttle_ok(100.0, 99.5, 50.0, 50.2))
        # 边界：恰好等于阈值 → 输出
        self.assertTrue(cli._throttle_ok(100.0, 99.5, 50.0, 51.0))

        # 文案也必须同步：契约里写的是 AND 就与实现矛盾
        doc = (ROOT / "docs" / "CONTRACT-cli.md").read_text(encoding="utf-8")
        row = [ln for ln in doc.splitlines() if ln.startswith("| `progress` |")]
        self.assertTrue(row, "契约里找不到 progress 事件行")
        self.assertIn("或", row[0], "契约的节流文案仍写成 AND")

    def test_anchor_check_scans_src(self):
        """BUG-18 锚点检查必须扫到 src/，否则目录重组后整项空转。"""
        vc._results.clear()
        vc.check_anchors()
        detail = vc._results[-1]["detail"]
        self.assertNotIn("0 处锚点", detail, "锚点检查没扫到 src/")

    # ---------------- BUG-43 · schema_defaults 的 map 是手工白名单 ----------------

    def test_bug43_schema_defaults_detects_unmapped_default_key(self):
        """BUG-43 defaults 里有键却不在契约 map 里时必须报红，不得静默逃逸。

        契约 CLI-013 明写「defaults 的每个键都要在 args 里有对应参数（归一化后），
        缺失即错」——判据应当以 `SCHEMA["defaults"]` 为准。但实现遍历的是契约块里
        手写的 map 清单：清单没跟上 defaults 时，那个键从头到尾没人看，
        「默认值只写一处」这条规则也就有了绕过口。
        """
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "mapmod.py").write_text(
            "SCHEMA = {\n"
            "    'version': 1,\n"
            "    'args': {'--x': '说明', '--newopt': '新选项，默认 7'},\n"
            "    'defaults': {'x': 16, 'newopt': 7},\n"
            "}\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        sys.path.insert(0, str(tmp))
        try:
            vc.chk_schema_defaults("t.md", {
                "module": "mapmod",
                "map": {"x": "--x"},
                "pattern": r"默认\s*(\d+)",
                "must_contain": {}})
        finally:
            vc.SRC = old_src
            sys.path.remove(str(tmp))
            sys.modules.pop("mapmod", None)
        detail = vc._results[-1]["detail"]
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD,
                         f"未登记进 map 的 defaults 键逃过了检查：{detail}")
        self.assertIn("newopt", detail, "报红信息没点名出问题的键")

    def test_bug43_schema_defaults_detects_map_key_absent_from_defaults(self):
        """BUG-43 反向：map 登记了 defaults 里不存在的键必须报红。

        与上一条构成完整的一对：上一条管「defaults 多了键、map 漏登记」，
        这条管「map 多了键、defaults 里没有」。只有两条都在，两个方向的漂移
        才都逃不掉——少一条就等于留了个绕过口。

        同时确认反向核对**不会被正向核对误伤**：两个方向同时失配时，
        两条判据都要报出来，不能因为先命中一条就把另一条吞掉。
        """
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "ghostmod.py").write_text(
            "SCHEMA = {\n"
            "    'version': 1,\n"
            "    'args': {'--x': '说明', '--y': '别的', '--z': '再一个'},\n"
            "    'defaults': {'x': 16, 'y': 12},\n"
            "}\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        sys.path.insert(0, str(tmp))
        try:
            # z 没登记进 map（正向失配），ghost 在 defaults 里不存在（反向失配）
            vc.chk_schema_defaults("t.md", {
                "module": "ghostmod",
                "map": {"x": "--x", "ghost": "--z"},
                "pattern": r"默认\s*(\d+)",
                "must_contain": {}})
        finally:
            vc.SRC = old_src
            sys.path.remove(str(tmp))
            sys.modules.pop("ghostmod", None)
        detail = vc._results[-1]["detail"]
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD,
                         f"map 登记了 defaults 里没有的键却没报红：{detail}")
        self.assertIn("ghost", detail, "报红信息没点名出 map 里多出来的键")

    # ---------------- BUG-45 · schema_defaults 采信 map 的参数名 ----------------

    def test_bug45_schema_defaults_reverse_lookup_from_args(self):
        """BUG-45 参数名必须从 args 反查，不能直接采信契约 map 里的声明。

        `defaults` 的键在 `args` 里没有对应参数时，必须报红——采信 map 的话，
        map 写错就能让这条默认值整体逃逸检查。

        这里守的是**实现路径**而非行为差异：反查（`norm.get(dkey)`）与采信
        map（`chk["map"].get(dkey)`）在多数场景下报红信息相同——`map` 的错接
        会被「map → 反查结果」那条判据独立抓出，掩盖掉两者差异。所以行为断言
        区分不出这两条路径，只有断言实现里用的是反查才守得住。

        断言方式：AST 里主循环取 akey 的表达式必须是对 `norm` 的调用，
        不能是对契约 map 的调用。
        """
        src = (ROOT / "docs" / "verify_contract.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "chk_schema_defaults":
                fn = node
                break
        self.assertIsNotNone(fn, "找不到 chk_schema_defaults")

        # 主循环里给 akey 赋值的那一句：必须是反查，不是采信契约 map
        assigns = []
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "akey":
                        assigns.append(node.value)
        self.assertTrue(assigns, "chk_schema_defaults 里找不到给 akey 赋值的语句")

        def called_names(call):
            f = call.func
            if isinstance(f, ast.Attribute):
                return f.attr, ast.unparse(f.value)
            if isinstance(f, ast.Name):
                return f.id, ""
            return "", ""

        ok = False
        for call in assigns:
            name, base = called_names(call)
            # 反查：norm.get(dkey)；采信 map：chk["map"].get(dkey)
            if name == "get" and base == "norm":
                ok = True
            self.assertNotEqual(
                (name, base), ("get", "chk"),
                "akey 取自契约 map 而非从 args 反查——BUG-45 的修复没有落地")
        self.assertTrue(ok, "akey 不是从 args 反查得到的（norm.get）")

        # 反查路径的行为：defaults 的键在 args 里无对应参数时必须报红并点名该键
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "rlmod.py").write_text(
            "SCHEMA = {\n"
            "    'version': 1,\n"
            "    'args': {'--z': '另一个参数'},\n"
            "    'defaults': {'x': 16},\n"
            "}\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        sys.path.insert(0, str(tmp))
        try:
            vc.chk_schema_defaults("t.md", {
                "module": "rlmod",
                "map": {"x": "--y"},          # --y 在 args 里不存在
                "pattern": r"默认\s*(\d+)",
                "must_contain": {}})
        finally:
            vc.SRC = old_src
            sys.path.remove(str(tmp))
            sys.modules.pop("rlmod", None)
        detail = vc._results[-1]["detail"]
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD,
                         f"defaults 的键在 args 里无对应参数却没报红：{detail}")
        self.assertIn("x", detail, "报红信息没点名出逃逸的默认值键")

    def test_bug45_schema_defaults_detects_map_mispointing(self):
        """BUG-45 契约 map 把默认值声明到不对应的参数上时必须报红。

        map 是显式声明而非事实源：声明与「从 args 反查」的结果对不上即报红。
        """
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "mismod.py").write_text(
            "SCHEMA = {\n"
            "    'version': 1,\n"
            "    'args': {'--x': '说明', '--y': '别的'},\n"
            "    'defaults': {'x': 16, 'y': 12},\n"
            "}\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        sys.path.insert(0, str(tmp))
        try:
            vc.chk_schema_defaults("t.md", {
                "module": "mismod",
                "map": {"x": "--y", "y": "--y"},   # x 被错接到 --y
                "pattern": r"默认\s*(\d+)",
                "must_contain": {}})
        finally:
            vc.SRC = old_src
            sys.path.remove(str(tmp))
            sys.modules.pop("mismod", None)
        detail = vc._results[-1]["detail"]
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD,
                         f"map 错接却没报红：{detail}")
        self.assertIn("x", detail, "报红信息没点名出被错接的键")

    def test_bug45_schema_defaults_catches_text_under_wrong_map(self):
        """BUG-45 回归护栏：map 错接时，该默认值文案复述默认值仍须报红。

        这正是修复前漏掉的那条路径——`map` 把 `slow_sec` 错接到 `--slow`，
        而 `--slow-sec` 的文案复述了「默认 12」，旧实现因采信 map 而完全没查
        `--slow-sec`，全套校验照旧报绿。
        """
        import dl as cli

        saved = cli.SCHEMA["args"]
        wrong = {"threads": "-t/--threads", "chunk": "--chunk", "slow": "--slow",
                 "slow_sec": "--slow",        # 错接：slow_sec → --slow
                 "retries": "--retries", "timeout": "--timeout",
                 "max_speed": "--max-speed"}
        try:
            cli.SCHEMA["args"] = dict(saved)
            cli.SCHEMA["args"]["--slow-sec"] = "慢速持续秒数，默认 12"
            vc.chk_schema_defaults("t.md", {
                "module": "dl", "map": wrong,
                "pattern": r"默认\s*(\d+)", "must_contain": {}})
        finally:
            cli.SCHEMA["args"] = saved
        detail = vc._results[-1]["detail"]
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD,
                         f"map 错接时文案复述默认值却没报红：{detail}")
        self.assertIn("--slow-sec", detail,
                      "报红信息没点名出真正复述了默认值的参数")

        # 两个方向同时失配时，两条都要报出来：map 错接（x→--y）与
        # defaults 的 y 漏登记。少一条就等于留了个绕过口。
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "bothmod.py").write_text(
            "SCHEMA = {\n"
            "    'version': 1,\n"
            "    'args': {'--x': '说明', '--y': '别的'},\n"
            "    'defaults': {'x': 16, 'y': 12},\n"
            "}\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        sys.path.insert(0, str(tmp))
        try:
            vc.chk_schema_defaults("t.md", {
                "module": "bothmod",
                "map": {"x": "--y"},      # x 错接；y 压根没登记
                "pattern": r"默认\s*(\d+)",
                "must_contain": {}})
        finally:
            vc.SRC = old_src
            sys.path.remove(str(tmp))
            sys.modules.pop("bothmod", None)
        detail = vc._results[-1]["detail"]
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD,
                         f"两个方向都失配却没报红：{detail}")
        self.assertIn("y", detail, "正向失配（defaults 的 y 漏登记）被反向核对吞掉了")

    # ---------------- BUG-44 · literal_dict 缺自测覆盖 ----------------

    def test_bug44_literal_dict_detects_non_literal(self):
        """BUG-44 literal_dict 必须能判出非字面量的 SCHEMA，否则 CLI-014 形同虚设。

        这条检查此前没有任何自测用例：它坏掉时整套校验会悄悄失去这道防线。
        """
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "litmod.py").write_text(
            "SCHEMA = {\n"
            "    'name': f'd{1}l',\n"
            "    'args': {'--x': '说明'},\n"
            "}\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        try:
            vc.chk_literal_dict("t.md", {"file": "litmod.py", "name": "SCHEMA"})
        finally:
            vc.SRC = old_src
        detail = vc._results[-1]["detail"]
        self.assertEqual(vc._results[-1]["state"], vc.C_BAD)
        self.assertIn("JoinedStr", detail)

    def test_bug44_literal_dict_accepts_literal(self):
        """BUG-44 纯字面量 SCHEMA 不得误报（零误报是这条检查的前提）。"""
        tmp = Path(tempfile.mkdtemp(prefix="vc_"))
        (tmp / "litok.py").write_text(
            "SCHEMA = {\n"
            "    'name': 'dl',\n"
            "    'args': {'--x': '说明'},\n"
            "    'defaults': {'x': 16},\n"
            "}\n",
            encoding="utf-8")
        old_src = vc.SRC
        vc.SRC = tmp
        try:
            vc.chk_literal_dict("t.md", {"file": "litok.py", "name": "SCHEMA"})
        finally:
            vc.SRC = old_src
        self.assertEqual(vc._results[-1]["state"], vc.C_OK)

    @staticmethod
    def _sources():
        return sorted((ROOT / "src").glob("*.py")) + sorted((ROOT / "src").glob("*.pyw"))

    def test_source_line_width(self):
        """BUG-14 CODE-009 的行宽必须可执行，不能只写在文档里。"""
        bad = []
        for path in self._sources():
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if len(line) > 100:
                    bad.append(f"{path.name}:{i}（{len(line)} 列）")
        self.assertEqual(bad, [], f"超出 100 列：{bad}")

    def test_source_no_dead_imports(self):
        """BUG-12 源码里不许留死导入；_opener 是给测试的再导出，进白名单。"""
        # 再导出的公开符号按 CORE-001 保留在引擎模块上，不算死导入
        allow = {"_opener", "annotations", "GITHUB_MIRRORS",
                 "build_mirror_urls", "is_github_release", "EXIT_NO_MIRROR"}
        dead = {}
        for path in self._sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        imported[a.asname or a.name.split(".")[0]] = node.lineno
                elif isinstance(node, ast.ImportFrom):
                    for a in node.names:
                        if a.name != "*":
                            imported[a.asname or a.name] = node.lineno
            used = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    used.add(node.id)
                elif isinstance(node, ast.Attribute):
                    cur = node
                    while isinstance(cur, ast.Attribute):
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        used.add(cur.id)
            left = sorted(k for k in imported if k not in used and k not in allow)
            if left:
                dead[path.name] = left
        self.assertEqual(dead, {}, f"死导入：{dead}")

    def _tracked_text_files(self):
        """仓库里会被公开的文本文件。用 git 的清单，而不是遍历目录——
        只有纳入版本库的文件才会出现在 GitHub 上，这才是要检查的范围。"""
        try:
            out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                                 capture_output=True, check=True).stdout
            names = [n for n in out.decode("utf-8").split("\0") if n]
        except (OSError, subprocess.CalledProcessError):
            names = [p.relative_to(ROOT).as_posix()
                     for p in ROOT.rglob("*")
                     if p.is_file() and ".git" not in p.parts
                     and not any(x in p.parts for x in ("build", ".workbuddy"))]
        for name in names:
            path = ROOT / name
            if path.suffix.lower() in (".ico", ".png", ".zip", ".exe"):
                continue
            yield path

    def test_repo_publishes_no_private_or_internal_content(self):
        """公开仓库里不得出现本机路径、账户名与内部流程痕迹。

        仓库是公开的：写进去的每个字读者都能看到，也可能被搜索引擎收录。
        本机绝对路径会带出账户名；「本轮」「裁决」这类流程用语对读者是噪声。
        两者都不会报错、不会被运行时发现，只能靠这条用例守住。
        """
        rules = [
            (r"[A-Za-z]:[\\/]+Users[\\/]", "本机用户目录绝对路径"),
            (r"/c/Users/", "Git Bash 风格的用户目录路径"),
            (r"\bAdministrator\b", "本机账户名"),
            (r"主理人|裁决|复评|复验|第[一二三四五]轮|本轮|这轮", "内部流程用语"),
            (r"WorkBuddy|CodeBuddy|子代理|智能体", "内部工具痕迹"),
        ]
        # 用例自身要写出这些正则才能检查它们，因此跳过自己
        skip = {Path(__file__).name}
        problems = []
        for path in self._tracked_text_files():
            if path.name in skip:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for pattern, why in rules:
                    if re.search(pattern, line):
                        problems.append(
                            f"{path.relative_to(ROOT).as_posix()}:{lineno} "
                            f"{why} → {line.strip()[:60]}")
        self.assertEqual(problems, [],
                         "公开仓库里出现了不该公开的内容：\n" + "\n".join(problems[:10]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
