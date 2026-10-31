#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_bugs.py —— 缺陷回归测试（本地假服务器，不需要外网）

每个用例对应 docs/BUGS.md 里的一条，函数体内标注编号，
修复前必须是红的，修复后必须转绿。

运行：
    python -m unittest tests.test_bugs -v
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import diskutil  # noqa: E402
import downloader as dl  # noqa: E402
import taskqueue as tq  # noqa: E402
from dl import main as dl_main  # noqa: E402

MB = 1024 * 1024
DEFAULT = b"x" * (2 * MB)
Usage = namedtuple("usage_result", "total used free")


class Handler(BaseHTTPRequestHandler):
    """可控假服务器：range 正常分段；ignore 忽略 Range；zero 返回空文件。"""

    protocol_version = "HTTP/1.1"
    payload = DEFAULT
    mode = "range"
    etag = '"v1"'
    zero = False
    ranges: list[str] = []

    def log_message(self, *a):
        pass

    def _n(self):
        return 0 if self.zero else len(self.payload)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(self._n()))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", self.etag)
        self.end_headers()

    def do_GET(self):
        rng = self.headers.get("Range")
        if rng:
            Handler.ranges.append(rng)
        n = self._n()
        if self.mode == "range" and rng and n:
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            s = int(m.group(1))
            e = int(m.group(2)) if m.group(2) else n - 1
            e = min(e, n - 1)
            body = self.payload[s:e + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {s}-{e}/{n}")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", self.etag)
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(n))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", self.etag)
            self.end_headers()
            if n:
                self.wfile.write(self.payload)


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class BugTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = QuietServer(("127.0.0.1", 0), Handler)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/f.bin"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        Handler.payload = DEFAULT
        Handler.mode = "range"
        Handler.etag = '"v1"'
        Handler.zero = False
        Handler.ranges.clear()
        self.tmp = Path(tempfile.mkdtemp(prefix="bugtest_"))
        self.out = str(self.tmp / "f.bin")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        if os.name == "nt":   # 超长路径只能用 \\?\ 删
            shutil.rmtree("\\\\?\\" + str(self.tmp), ignore_errors=True)

    # ---------------- 工具 ----------------

    def _run(self, **kw):
        params = dict(threads=4, retries=0, slow_kb=0, timeout=20)
        params.update(kw)
        return dl.DownloadTask([self.url], self.out, **params).run()

    @staticmethod
    def _sha(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(MB), b""):
                h.update(b)
        return h.hexdigest()

    # ---------------- BUG-01 ----------------

    def test_bug01_zero_byte(self):
        """BUG-01 Content-Length: 0 的合法文件必须能下载，不能被当成探测失败。"""
        Handler.zero = True
        info = dl.probe(self.url)
        self.assertEqual(info["size"], 0)
        self.assertIsNone(info["error"], f"0 字节被误判为失败：{info['error']}")

        path = self._run()
        self.assertEqual(os.path.getsize(path), 0)

        os.remove(path)
        path = self._run(sha256=hashlib.sha256(b"").hexdigest())
        self.assertEqual(os.path.getsize(path), 0)

    # ---------------- BUG-02 ----------------

    def test_bug02_forget_resets_stats(self):
        """BUG-02 任务从列表移除后，队列统计必须跟着复位；运行中的不许移除。"""
        class Fake:
            gate = threading.Event()

            def __init__(self, urls, *a, **kw):
                self._cancel = threading.Event()
                self.slow = "slow" in urls[0]

            def run(self):
                if self.slow:
                    Fake.gate.wait(5)
                return "fake.bin"

            def cancel(self):
                self._cancel.set()

        old = tq.DownloadTask
        tq.DownloadTask = Fake
        try:
            q = tq.DownloadQueue(concurrent=3)
            for i in range(3):
                q.add([f"http://x/{i}"], "out")
            end = time.time() + 5
            while time.time() < end and q.stats()["done"] < 3:
                time.sleep(0.02)

            self.assertEqual(q.stats()["done"], 3)
            self.assertTrue(q.forget(1))
            self.assertEqual(q.stats()["total"], 2)
            self.assertEqual(q.stats()["done"], 2)

            slow = q.add(["http://x/slow"], "out")
            end = time.time() + 5
            while time.time() < end and q.state_of(slow) != "running":
                time.sleep(0.02)
            self.assertFalse(q.forget(slow), "运行中的任务不能被静默移除")
        finally:
            Fake.gate.set()
            tq.DownloadTask = old

    # ---------------- BUG-06 ----------------

    def test_bug06_space_precheck(self):
        """BUG-06 空间不够必须在下第一片之前报错，不能等下完再失败。"""
        Handler.payload = b"y" * (10 * MB)
        with mock.patch("shutil.disk_usage",
                        return_value=Usage(20 * MB, 19 * MB, 1 * MB)):
            with self.assertRaises(dl.DownloadError) as ctx:
                self._run()
        self.assertIn("空间不足", str(ctx.exception))
        self.assertFalse(os.path.exists(self.out + ".parts"))
        self.assertFalse(os.path.exists(self.out))

    def test_bug06_fat32_reject(self):
        """BUG-06 FAT32 上超过 4GB 的文件必须提前拒绝，而不是合并时炸。"""
        with mock.patch("shutil.disk_usage",
                        return_value=Usage(500 * 1024 ** 3, 0, 500 * 1024 ** 3)), \
                mock.patch("diskutil.fs_type", return_value="FAT32"):
            with self.assertRaises(diskutil.DiskError) as ctx:
                diskutil.check_target(self.out, 5 * 1024 ** 3)
            self.assertIn("FAT32", str(ctx.exception))
            # 3GB 仍然允许
            diskutil.check_target(self.out, 3 * 1024 ** 3)

    # ---------------- BUG-08 ----------------

    @unittest.skipUnless(os.name == "nt", "长路径限制只在 Windows 上")
    def test_bug08_long_path(self):
        """BUG-08 超过 MAX_PATH 的保存路径必须给出可行动的提示，不能报 Errno 2。"""
        deep = self.tmp
        for _ in range(3):
            deep = deep / ("d" * 60)
        os.makedirs("\\\\?\\" + str(deep), exist_ok=True)
        out = str(deep / ("b" * 110 + ".bin"))
        self.assertGreater(len(out), 260)

        Handler.payload = b"z" * (300 * 1024)
        with self.assertRaises(dl.DownloadError) as ctx:
            dl.DownloadTask([self.url], out, threads=4, retries=0,
                            slow_kb=0, timeout=10).run()
        msg = str(ctx.exception)
        self.assertIn("保存路径过长", msg)
        self.assertNotIn("Errno 2", msg)
        self.assertFalse(os.path.exists(out + ".parts"))

    # ---------------- BUG-10 ----------------

    def test_bug10_enospc_fast_fail(self):
        """BUG-10 写入遇到 ENOSPC 必须立刻中止，不能退避重试 7 次。"""
        Handler.payload = b"w" * (5 * MB)
        boom = OSError(errno.ENOSPC, "No space left on device")
        t0 = time.time()
        with mock.patch.object(dl, "_write", side_effect=boom):
            with self.assertRaises(dl.DownloadError) as ctx:
                self._run(retries=6)
        self.assertLess(time.time() - t0, 2.0, "还在按退避重试")
        self.assertIn("空间不足", str(ctx.exception))
        self.assertTrue(os.path.exists(self.out + ".parts"), "已下载的分片应保留")

    def test_bug10_enospc_single(self):
        """BUG-10 单线程路径同样要快速失败，并保留 .part。"""
        Handler.payload = b"v" * (300 * 1024)
        boom = OSError(errno.ENOSPC, "No space left on device")
        with mock.patch.object(dl, "_write", side_effect=boom):
            with self.assertRaises(dl.DownloadError) as ctx:
                self._run()
        self.assertIn("空间不足", str(ctx.exception))
        self.assertTrue(os.path.exists(self.out + ".part"))

    # ---------------- BUG-07 ----------------

    def test_bug07_mirror_warns_without_hash(self):
        """BUG-07 经镜像且未给哈希时必须吵一声；给了哈希就不该再吵。"""
        logs = []
        urls = [self.url, self.url + "?mirror=1"]

        dl.DownloadTask(urls, self.out, threads=4, retries=0, slow_kb=0,
                        log=lambda m, lv="info": logs.append((lv, m))).run()
        self.assertTrue(any("未提供哈希" in m for _, m in logs),
                        f"没有提示镜像内容无法验证：{logs}")

        logs.clear()
        sha = hashlib.sha256(DEFAULT).hexdigest()
        os.remove(self.out)
        dl.DownloadTask(urls, self.out, sha256=sha, threads=4, retries=0,
                        slow_kb=0, log=lambda m, lv="info": logs.append((lv, m))).run()
        self.assertFalse(any("未提供哈希" in m for _, m in logs))

    # ---------------- BUG-09 ----------------

    def test_bug09_hash_single_pass(self):
        """BUG-09 带 --sha256 时只能把文件读一遍，不能校验完再算一次。"""
        Handler.payload = b"h" * (3 * MB)
        digest = hashlib.sha256(Handler.payload).hexdigest()
        counted = {"n": 0}
        real_new, real_sha = hashlib.new, hashlib.sha256

        class Counting:
            def __init__(self, real):
                self.real = real

            def update(self, b):
                counted["n"] += len(b)
                self.real.update(b)

            def hexdigest(self):
                return self.real.hexdigest()

        with mock.patch("hashlib.new",
                        lambda a, *p, **k: Counting(real_new(a, *p, **k))), \
                mock.patch("hashlib.sha256",
                           lambda *p, **k: Counting(real_sha(*p, **k))), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = dl_main([self.url, "-o", self.out, "--sha256", digest, "--quiet"])

        self.assertEqual(rc, 0)
        self.assertEqual(counted["n"], 3 * MB, "同一份文件被哈希了两遍")

    def test_bug09_done_verified_for_md5(self):
        """BUG-09 顺带：期望值是 md5 时 done.verified 不得误报 false。"""
        Handler.payload = b"q" * (300 * 1024)
        md5 = hashlib.md5(Handler.payload).hexdigest()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = dl_main([self.url, "-o", self.out, "--sha256", md5, "--json"])
        self.assertEqual(rc, 0)

        events = [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]
        done = [e for e in events if e.get("event") == "done"][-1]
        self.assertTrue(done["verified"], "md5 校验通过却报了 verified=false")
        self.assertEqual(done["sha256"],
                         hashlib.sha256(Handler.payload).hexdigest())

    # ---------------- BUG-15 ----------------

    def test_bug15_single_resume_detects_change(self):
        """BUG-15 单线程续传必须核对指纹：远端换同长度内容后不得拼出坏文件。"""
        old = b"A" * (300 * 1024)
        new = b"B" * (300 * 1024)

        Handler.payload, Handler.etag = old, '"v1"'
        with open(self.out + ".part", "wb") as f:
            f.write(old[:100 * 1024])
        with open(self.out + ".part.json", "w", encoding="utf-8") as f:
            json.dump({"version": 1, "size": len(old),
                       "etag": '"v1"', "url": self.url}, f)

        Handler.payload, Handler.etag = new, '"v2"'
        path = self._run()

        self.assertEqual(self._sha(path), hashlib.sha256(new).hexdigest(),
                         "续传把新旧内容拼在了一起")
        self.assertEqual(os.path.getsize(path), len(new))

    def test_bug15_single_resume_when_unchanged(self):
        """BUG-15 指纹一致时必须真续传，不能退化成每次全量重下。"""
        data = b"C" * (300 * 1024)
        Handler.payload, Handler.etag = data, '"v3"'
        with open(self.out + ".part", "wb") as f:
            f.write(data[:100 * 1024])
        with open(self.out + ".part.json", "w", encoding="utf-8") as f:
            json.dump({"version": 1, "size": len(data),
                       "etag": '"v3"', "url": self.url}, f)

        path = self._run()
        self.assertEqual(self._sha(path), hashlib.sha256(data).hexdigest())
        self.assertIn("bytes=102400-", Handler.ranges, "没有从断点续传")

    # ---------------- BUG-16 ----------------

    def test_bug16_add_pump_race(self):
        """BUG-16 add() 与 _pump() 竞态：任务必须被登记后才能被取走执行。"""
        errors = []

        class RaceTask:
            gate = threading.Event()
            lock = threading.Lock()
            made = 0

            def __init__(self, urls, *a, **kw):
                self._cancel = threading.Event()
                with RaceTask.lock:
                    RaceTask.made += 1
                    self.n = RaceTask.made
                if self.n == 2:
                    # 卡住第二个任务的构造，让第一个任务在此期间结束
                    RaceTask.gate.wait(5)

            def run(self):
                if self.n == 1:
                    time.sleep(0.05)
                    return "one.bin"
                return "two.bin"

            def cancel(self):
                self._cancel.set()

        def hook(args):
            errors.append(f"{args.exc_type.__name__}: {args.exc_value}")

        old_task = tq.DownloadTask
        old_hook = threading.excepthook
        tq.DownloadTask = RaceTask
        threading.excepthook = hook
        try:
            q = tq.DownloadQueue(concurrent=1)
            q.add(["http://x/1"], "a")
            time.sleep(0.01)
            threading.Timer(0.25, RaceTask.gate.set).start()
            q.add(["http://x/2"], "b")   # 构造期间第一个任务结束

            end = time.time() + 3
            while time.time() < end and q.state_of(2) != "done":
                time.sleep(0.02)
        finally:
            tq.DownloadTask = old_task
            threading.excepthook = old_hook
            RaceTask.gate.set()

        self.assertEqual(errors, [], "工作线程抛异常，任务永远起不来")
        self.assertEqual(q.state_of(2), "done")
        self.assertEqual(list(q._running), [], "并发槽泄漏")

    # ---------------- BUG-17 ----------------

    def test_bug17_measure_bounded(self):
        """BUG-17 测速只允许读固定窗口，不能把整个响应读进内存。"""
        Handler.mode = "ignore"
        Handler.payload = b"m" * (32 * MB)

        tracemalloc.start()
        try:
            got = dl._measure_mirror(self.url)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

        self.assertFalse(got.get("failed"))
        self.assertGreater(got["speed"], 0)
        self.assertLess(peak, 8 * MB, f"测速读入 {peak / MB:.0f}MB，明显没有上限")


if __name__ == "__main__":
    unittest.main(verbosity=2)
