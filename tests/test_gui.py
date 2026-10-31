#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_gui.py —— 界面层行为测试

只测「不需要人眼」的逻辑：占位符判定、剪贴板填入、配置到队列的传递。
窗口全程 withdraw，不弹到桌面上；没有 tkinter 时整类跳过。

运行：
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import tkinter as tk
except Exception:  # noqa: BLE001
    tk = None


@unittest.skipIf(tk is None, "当前解释器没有 tkinter")
class GuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("gui_under_test",
                                                      ROOT / "gui.pyw")
        cls.gui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.gui)
        # 配置写到临时目录，别碰用户真实的 config.json
        cls.tmp = tempfile.mkdtemp(prefix="guitest_")
        cls.gui.CFG = os.path.join(cls.tmp, "config.json")

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = self.gui.App(self.root)

    def tearDown(self):
        self.root.destroy()

    def _type_url(self, text):
        self.app.txt_url.delete("1.0", "end")
        self.app.txt_url.insert("1.0", text)
        self.app.txt_url.tag_remove("ph", "1.0", "end")

    def test_placeholder_counts_as_empty(self):
        """带 ph 标记的占位符必须被判为空，否则剪贴板永远填不进来。"""
        app = self.app
        app.txt_url.delete("1.0", "end")
        app.txt_url.insert("1.0", "https://…")
        app.txt_url.tag_add("ph", "1.0", "end")
        self.assertTrue(app._url_box_empty())

        self._type_url("https://real.example/a.zip")
        self.assertFalse(app._url_box_empty())

    def test_clipboard_fills_when_placeholder(self):
        """输入框只有占位符时，剪贴板里的直链应被填入。"""
        app = self.app
        app.txt_url.delete("1.0", "end")
        app.txt_url.insert("1.0", "https://…")
        app.txt_url.tag_add("ph", "1.0", "end")

        self.root.clipboard_clear()
        self.root.clipboard_append("https://example.com/x.zip")
        app._watch_clip()

        self.assertIn("example.com/x.zip", app.txt_url.get("1.0", "end"))

    def test_clipboard_does_not_overwrite_typed(self):
        """用户已经手输了链接时，剪贴板不得覆盖。"""
        app = self.app
        self._type_url("https://typed.example/keep.bin")

        self.root.clipboard_clear()
        self.root.clipboard_append("https://example.com/other.zip")
        app._watch_clip()

        self.assertIn("keep.bin", app.txt_url.get("1.0", "end"))

    def test_concurrent_slider_applies(self):
        """改并发滑杆后，队列的并发上限要立刻跟着变。"""
        app = self.app
        app.sliders["concurrent"].set(3)
        self._type_url("https://e.com/a.bin")
        app.queue.add = lambda *a, **k: 1
        app._start()
        self.assertEqual(app.queue.concurrent, 3)

    def test_task_rows_created(self):
        """每点一次开始下载就多一行任务，列表从隐藏变为显示。"""
        app = self.app
        app.queue.add = lambda *a, **k: len(app.rows) + 1
        self.assertFalse(app._list_shown)

        self._type_url("https://e.com/1.bin")
        app._start()
        self._type_url("https://e.com/2.bin")
        app._start()

        self.assertEqual(len(app.rows), 2)
        self.assertTrue(app._list_shown)

        for tid in list(app.rows):
            app.rows[tid].destroy()
            app.rows.pop(tid)
        app.listwrap.pack_forget()
        app._list_shown = False


if __name__ == "__main__":
    unittest.main(verbosity=2)
