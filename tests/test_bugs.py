#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_bugs.py —— 缺陷回归测试（本地假服务器，不需要外网）

每个用例对应 docs/BUGS.md 里的一条，函数体内标注编号，
修复前必须是红的，修复后必须转绿。

运行：
    python -m unittest tests.test_bugs -v

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
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
    """可控假服务器：range 正常分段；ignore 忽略 Range；zero 返回空文件。

    另外三种专治「服务器嘴上说支持分段」：
      416     一律按 RFC 7233 拒绝 Range（HEAD 仍声称 Accept-Ranges: bytes）
      late416 只有非首字节的 Range 被拒（探测用的 bytes=0-0 放行）
      403     带 Range 的请求一律 403（防盗链），不带 Range 正常返回整文件
    """

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

    def _mode(self):
        # 以 /ignore 开头的路径固定忽略 Range，用于验证「部分源不支持分段」
        return "ignore" if self.path.startswith("/ignore") else self.mode

    def _reject_range(self, rng, n):
        """按模式决定是否拒绝这个 Range 请求；返回 True 表示已回过 416/403。"""
        mode = self._mode()
        if mode == "403":
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        if mode == "416":
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{n}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        if mode == "late416":
            # 只拒绝非首字节的 Range：探测用的 bytes=0-0 仍放行，
            # 于是「探测时正常、下载途中才 416」的场景能被复现
            start = int(re.match(r"bytes=(\d+)", rng).group(1))
            if start > 0:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{n}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return True
        return False

    def do_GET(self):
        rng = self.headers.get("Range")
        if rng:
            Handler.ranges.append(rng)
        n = self._n()
        if rng and self._reject_range(rng, n):
            return
        if rng and n and self._mode() in ("range", "late416"):
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
        elif rng and n and self._mode() == "overlong":
            # 起点正确、忽略结束位置：返回 [s, EOF)。
            # 客户端若照单全收，本片就会超长（BUG-32 的成因）
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            s = int(m.group(1))
            body = self.payload[s:]
            # 拉长传输时间，保证 reporter 至少发出一次进度事件
            time.sleep(0.3)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {s}-{n - 1}/{n}")
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


    # ---------------- BUG-19 · 加速源补全接入全部入口 ----------------

    def test_bug19_mirrors_expanded_for_every_entry(self):
        """BUG-19 GitHub 加速源必须在所有入口生效，不能只存在于遗留的源码 CLI。"""
        captured = {}

        def fake_rank(urls, log=None, proxy=None):
            captured["urls"] = list(urls)
            return []

        old = dl.rank_mirrors
        dl.rank_mirrors = fake_rank
        try:
            with self.assertRaises(dl.DownloadError):
                dl.DownloadTask(["https://github.com/o/r/releases/download/v1/x.zip"],
                                self.out, threads=2).run()
        finally:
            dl.rank_mirrors = old

        urls = captured.get("urls", [])
        self.assertEqual(len(urls), 4, f"未补齐加速源：{urls}")
        self.assertTrue(any("gh-proxy.com" in u for u in urls))

    def test_bug19_github_host_matched_exactly(self):
        """BUG-19 主机名按 URL 解析判定，查询串里出现 github.com 不算数。"""
        self.assertFalse(dl.is_github_release("https://example.com/?ref=github.com"))
        self.assertTrue(dl.is_github_release(
            "https://github.com/o/r/releases/download/v1/x.zip"))

    # ---------------- BUG-20 · 退出码由异常自带 ----------------

    def test_bug20_exit_code_not_from_message(self):
        """BUG-20 退出码不得由错误文案判定：「保存位置不可用」应返回 1 而非 3。"""
        bad = os.path.join("Z:\\no_such_drive", "x.bin")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = dl_main([self.url, "-o", bad, "--quiet"])
        self.assertEqual(rc, 1, "保存位置问题不应返回退出码 3")

        with contextlib.redirect_stdout(io.StringIO()):
            rc = dl_main(["http://127.0.0.1:1/x", "-o", self.out, "--quiet"])
        self.assertEqual(rc, 3, "所有镜像不可用应返回退出码 3")

    # ---------------- BUG-21 · 部分源不支持分段 ----------------

    def test_bug21_partial_no_range_keeps_chunks(self):
        """BUG-21 只有一个源忽略 Range 时不得整体退化，已下载的分片不能作废。"""
        Handler.payload = b"p" * (3 * MB)
        base = self.url.rsplit("/", 1)[0]
        urls = [f"{base}/ignore/f.bin", f"{base}/range/f.bin"]
        logs = []
        path = dl.DownloadTask(urls, self.out, threads=4, retries=1, slow_kb=0,
                               log=lambda m, lv="info": logs.append(m)).run()
        self.assertEqual(self._sha(path), hashlib.sha256(Handler.payload).hexdigest())
        self.assertFalse(any("退化单线程重下" in m for m in logs),
                         "部分源不支持 Range 不应触发整体退化")

    # ---------------- BUG-22 · 文件名截断保留扩展名 ----------------

    def test_bug22_safe_name_keeps_extension(self):
        """BUG-22 超过 120 字符的文件名截断后必须保留扩展名。"""
        got = dl._safe_name("a" * 200 + ".zip")
        self.assertTrue(got.endswith(".zip"), got[-10:])
        self.assertLessEqual(len(got), 120)

    # ---------------- BUG-23 · 队列不触碰引擎私有属性 ----------------

    def test_bug23_queue_uses_public_cancel(self):
        """BUG-23 队列不得访问引擎私有属性，只能读公开的 cancelled。"""
        src = (ROOT / "src" / "taskqueue.py").read_text(encoding="utf-8")
        self.assertNotIn("task._cancel", src)
        t = dl.DownloadTask([self.url], self.out, threads=1)
        self.assertFalse(t.cancelled)
        t.cancel()
        self.assertTrue(t.cancelled)

    # ---------------- BUG-24 · 指纹版本参与判定 ----------------

    def test_bug24_resume_checks_version(self):
        """BUG-24 指纹格式版本必须参与判定，旧版本指纹不得继续被采信。"""
        old = {"version": 0, "size": 10, "etag": '"v1"', "url": "u"}
        self.assertFalse(dl.resume.matches(old, 10, '"v1"'))
        new = {"version": 1, "size": 10, "etag": '"v1"', "url": "u"}
        self.assertTrue(dl.resume.matches(new, 10, '"v1"'))


    # ---------------- BUG-29 · job 文件参数优先级 ----------------

    def _job_cli(self, job: dict, argv: list[str]) -> tuple[int, dict]:
        """用假任务跑一次命令行入口，只看参数是怎么解析出来的。

        `sys.modules["dl"]` 是命令行模块（本文件里的 `dl` 是 downloader 的别名）。
        """
        job_path = self.tmp / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        captured = {}

        class FakeTask:
            actual_hash = None
            hash_algo = None

            def __init__(self, urls, out, threads, sha, **kw):
                captured["threads"] = threads
                captured.update(kw)
                self.out = out

            def run(self):
                with open(self.out, "wb") as f:
                    f.write(b"x")
                return self.out

            def cancel(self):
                pass

        cli = sys.modules["dl"]
        old = cli.DownloadTask
        cli.DownloadTask = FakeTask
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = dl_main(["--job", str(job_path)] + argv)
        finally:
            cli.DownloadTask = old
        return rc, captured

    def test_bug29_cli_beats_job_file(self):
        """BUG-29 显式传入与默认值相同的参数时，命令行必须优先于 job 文件。"""
        job = {"urls": [self.url], "out": self.out, "threads": 4,
               "slow": 30, "slow_sec": 20, "retries": 2, "timeout": 45,
               "chunk_mb": 4}
        rc, got = self._job_cli(job, ["--threads", "16", "--slow", "15",
                                      "--timeout", "30", "--quiet"])

        self.assertEqual(rc, 0)
        self.assertEqual(got["threads"], 16, "显式传的 --threads 16 被 job 文件顶掉了")
        self.assertEqual(got["slow_kb"], 15, "显式传的 --slow 15 被 job 文件顶掉了")
        self.assertEqual(got["timeout"], 30, "显式传的 --timeout 30 被 job 文件顶掉了")

    def test_bug29_job_used_when_cli_silent(self):
        """BUG-29 反向核对：命令行没给的参数仍然取 job 文件的值。"""
        job = {"urls": [self.url], "out": self.out, "threads": 4,
               "slow": 30, "slow_sec": 20, "retries": 2, "timeout": 45,
               "chunk_mb": 4}
        rc, got = self._job_cli(job, ["--quiet"])

        self.assertEqual(rc, 0)
        self.assertEqual(got["threads"], 4)
        self.assertEqual(got["slow_kb"], 30)
        self.assertEqual(got["slow_sec"], 20)
        self.assertEqual(got["retries"], 2)
        self.assertEqual(got["timeout"], 45)
        self.assertEqual(got["chunk_mb"], 4)

    # ---------------- BUG-42 · 416 不被识别 ----------------

    def test_bug42_probe_reports_no_ranges_on_416(self):
        """BUG-42 HEAD 声称支持 Range 却回 416 时，probe 必须判定不支持分段。"""
        Handler.mode = "416"
        info = dl.probe(self.url)
        self.assertFalse(info["ranges"], "416 仍被当成支持分段")
        self.assertEqual(info["size"], len(DEFAULT))
        self.assertIsNone(info["error"])

    def test_bug42_download_succeeds_when_416(self):
        """BUG-42 服务器声称支持分段却回 416 时，文件必须能下完且内容一致。"""
        Handler.mode = "416"
        Handler.payload = b"4" * (3 * MB)
        path = self._run()
        self.assertEqual(self._sha(path), hashlib.sha256(Handler.payload).hexdigest())
        self.assertEqual(os.path.getsize(path), len(Handler.payload))
        self.assertFalse(os.path.exists(self.out + ".parts"))

    def test_bug42_worker_416_falls_back_to_single(self):
        """BUG-42 下载途中才 416（探测时正常）时必须退化单线程下完，不能报分片失败。"""
        Handler.mode = "late416"
        Handler.payload = b"L" * (3 * MB)
        path = self._run()
        self.assertEqual(self._sha(path), hashlib.sha256(Handler.payload).hexdigest())
        self.assertFalse(os.path.exists(self.out + ".parts"))

    def test_bug42_permanent_error_no_full_retry(self):
        """BUG-42 403 这类永久错误不得耗尽全部重试轮次（不该白等退避）。"""
        Handler.mode = "403"
        Handler.payload = b"F" * (3 * MB)
        logs = []
        t0 = time.time()
        with self.assertRaises(dl.DownloadError):
            dl.DownloadTask([self.url], self.out, threads=1, retries=6, slow_kb=0,
                            timeout=20,
                            log=lambda m, lv="info": logs.append(m)).run()
        elapsed = time.time() - t0

        self.assertLess(elapsed, 5.0, f"永久错误仍在按退避反复重试（{elapsed:.1f}s）")
        self.assertTrue(any("403" in m for m in logs), f"没有认出 403：{logs}")
        # 探测确认 1 次 + 测速 1 次 + 每片 1 次；旧实现每片要退避重试 7 次
        self.assertLessEqual(len(Handler.ranges), 6, f"重试轮次过多：{Handler.ranges}")

    # ---------------- BUG-25 · 构建日志不得出现口令 ----------------

    def test_bug25_password_not_logged(self):
        """BUG-25 签名口令等敏感参数不得写入构建日志。"""
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import build_and_sign  # noqa: PLC0415

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            build_and_sign.run([sys.executable, "-c", "pass",
                               "--pw", "MySecretPfxPwd123"], redact="--pw")
        out = buf.getvalue()
        self.assertNotIn("MySecretPfxPwd123", out, "口令出现在日志中")
        self.assertIn("***", out, "口令未被遮蔽")

    # ---------------- 版本号：唯一来源是 git tag ----------------

    def test_version_info_template_has_no_literal_version(self):
        """版本号只能来自 git tag：模板里出现字面版本即视为回退。

        同一个事实（当前是哪个版本）若同时写在 tag、版本资源、README、Release
        名里，就一定会有一处忘记改，而且没有机制能发现。模板因此只放占位符。
        """
        tpl = (ROOT / "build" / "version_info.txt.in").read_text(encoding="utf-8")
        self.assertIn("{VERSION_TUPLE}", tpl, "模板缺少 {VERSION_TUPLE} 占位符")
        self.assertIn("{VERSION}", tpl, "模板缺少 {VERSION} 占位符")
        literal_checks = [
            (r"filevers\s*=\s*\(\s*\d", "filevers 被写成了字面量"),
            (r"prodvers\s*=\s*\(\s*\d", "prodvers 被写成了字面量"),
            (r"'FileVersion'\s*,\s*'\d", "FileVersion 被写成了字面量"),
            (r"'ProductVersion'\s*,\s*'\d", "ProductVersion 被写成了字面量"),
        ]
        for pattern, msg in literal_checks:
            self.assertIsNone(re.search(pattern, tpl), msg + "；应改回占位符")

    def test_version_resource_renders_from_tag(self):
        """按 tag 渲染：v1.4.2 → filevers=(1, 4, 2, 0) 与 '1.4.2.0'。"""
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import build_and_sign  # noqa: PLC0415

        self.assertEqual(build_and_sign._norm_version("v1.4.2"), "1.4.2")
        self.assertEqual(build_and_sign._norm_version("1.4.2"), "1.4.2")
        with self.assertRaises(SystemExit):
            build_and_sign._norm_version("abc")

        tmp = tempfile.mkdtemp(prefix="vinfo_")
        old = build_and_sign.VERSION_INFO_GENERATED
        build_and_sign.VERSION_INFO_GENERATED = os.path.join(tmp, "vi.txt")
        try:
            path = build_and_sign.render_version_info("1.4.2")
            text = Path(path).read_text(encoding="utf-8")
        finally:
            build_and_sign.VERSION_INFO_GENERATED = old
            shutil.rmtree(tmp, ignore_errors=True)

        self.assertIn("filevers=(1, 4, 2, 0)", text)
        self.assertIn("prodvers=(1, 4, 2, 0)", text)
        self.assertIn("'FileVersion', '1.4.2.0'", text)
        self.assertIn("'ProductVersion', '1.4.2.0'", text)
        self.assertNotIn("{VERSION", text, "占位符没有被替换")

    # ---------------- BUG-26 · 共享状态须在锁内写入 ----------------

    def test_bug26_shared_state_under_lock(self):
        """BUG-26 跨线程共享状态的写入必须在锁内（CODE-006）。"""
        src = (ROOT / "src" / "downloader.py").read_text(encoding="utf-8")
        # 只检查运行期的写入点；__init__ 中的初始化是构造期行为，不涉及并发
        for pat in ("self._fatal = DownloadError(",
                    "self._errors.append(idx)",
                    "self._no_range_mirrors.add(url_idx)",
                    "self._all_no_range = True"):
            i = src.index(pat)
            self.assertIn("with self._lock:", src[max(0, i - 500):i],
                          f"{pat} 不在锁内写入")

    # ---------------- BUG-27 · 常量须为默认值来源 ----------------

    def test_bug27_constants_are_defaults(self):
        """BUG-27 契约守护的常量必须真正参与行为判定，即作为默认参数来源。"""
        import inspect

        params = inspect.signature(dl.DownloadTask.__init__).parameters
        self.assertEqual(params["slow_kb"].default, dl.SLOW_BYTES // 1024)
        self.assertEqual(params["slow_sec"].default, dl.SLOW_WINDOW)
        self.assertEqual(params["retries"].default, dl.MAX_RETRY)

    # ---------------- BUG-30 · 收敛唯一命令行入口 ----------------

    def test_bug30_downloader_has_no_cli_entry(self):
        """BUG-30 引擎层不得自带命令行入口：main 只存在于 dl.py。REQ-022 命令行入口唯一。"""
        self.assertFalse(hasattr(dl, "main"), "downloader 仍导出 main()")
        self.assertTrue(hasattr(sys.modules["dl"], "main"), "dl.py 缺 main()")
        src = (ROOT / "src" / "downloader.py").read_text(encoding="utf-8")
        self.assertNotIn("argparse", src, "引擎层出现了 argparse")
        gui = (ROOT / "src" / "gui.pyw").read_text(encoding="utf-8")
        self.assertNotIn("from downloader import main", gui,
                         "界面层仍从引擎取 main()")

    def test_bug30_readme_points_to_dl(self):
        """BUG-30 README 宣传的命令行方式必须是唯一入口 dl.py。"""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("python src/downloader.py", readme,
                         "README 仍在宣传已删除的源码命令行入口")
        self.assertIn("python src/dl.py", readme, "README 缺唯一入口的用法")

    # ---------------- BUG-32 · 进度口径与合并校验同源 ----------------

    def test_bug32_progress_never_exceeds_total(self):
        """BUG-32 服务器多发字节时，进度不得越过 100%。REQ-021 进度口径与合并校验同源。"""
        Handler.mode = "overlong"
        Handler.payload = b"o" * (3 * MB)
        events = []
        with self.assertRaises(dl.DownloadError) as ctx:
            dl.DownloadTask([self.url], self.out, threads=4, retries=0,
                            slow_kb=0, timeout=20,
                            progress=lambda d: events.append(d)).run()
        # 失败原因不得是合并阶段的「长度异常」——那说明拦截发生在写入前
        self.assertNotIn("长度异常", str(ctx.exception))
        for d in events:
            self.assertLessEqual(d["percent"], 100.0, f"进度越界：{d}")
            self.assertLessEqual(d["done"], d["total"], f"进度越界：{d}")

    # ---------------- BUG-33 · 删除超长分片时进度回退 ----------------

    def test_bug33_oversized_part_rolls_back_progress(self):
        """BUG-33 预置超长分片时，进度不得虚高，且产物必须与服务器一致。"""
        Handler.payload = b"g" * (3 * MB)
        Handler.etag = '"v-over"'
        try:
            size = len(Handler.payload)
            chunk = dl.MIN_CHUNK
            chunks = [[i * chunk, min(i * chunk + chunk - 1, size - 1)]
                      for i in range((size + chunk - 1) // chunk)]
            parts = Path(self.out + ".parts")
            parts.mkdir(parents=True)
            (parts / "meta.json").write_text(json.dumps(
                {"size": size, "chunks": chunks, "mirrors": [],
                 "etag": Handler.etag}), encoding="utf-8")
            # 超长：比期望长度多 5000 字节，必须整片重下而不是截断
            (parts / "part0000").write_bytes(b"\xff" * (chunk + 5000))

            events = []
            path = dl.DownloadTask([self.url], self.out, threads=4, retries=0,
                                   slow_kb=0, timeout=20,
                                   progress=lambda d: events.append(d)).run()
            for d in events:
                self.assertLessEqual(d["done"], d["total"], f"进度越界：{d}")
                self.assertLessEqual(d["percent"], 100.0, f"进度越界：{d}")
            self.assertEqual(self._sha(path),
                             hashlib.sha256(Handler.payload).hexdigest())
        finally:
            Handler.payload = DEFAULT
            Handler.etag = '"v1"'

    # ---------------- BUG-34 · 测速不把探测耗时计入分母 ----------------

    def test_bug34_measure_excludes_probe_time(self):
        """BUG-34 探测耗时不计入测速分母，否则慢探测源会被误判为慢源。"""
        real_probe = dl.probe

        def slow_probe(url, *a, **kw):
            time.sleep(0.4)
            return real_probe(url, *a, **kw)

        with mock.patch("downloader.probe", side_effect=slow_probe):
            got = dl._measure_mirror(self.url)
        # 分母若含 0.4s 探测耗时，速度必然低于 256KB/0.25
        self.assertGreater(got["speed"], 256 * 1024 / 0.25,
                           f"探测耗时被计入分母：speed={got['speed']}")

    # ---------------- BUG-35 · 限速先取配额再落盘 ----------------

    def test_bug35_limiter_acquires_before_write(self):
        """BUG-35 限速必须作用于真正写下去的字节：先 acquire 后 write。"""
        events = []
        real_write = dl._write

        class FakeLimiter:
            def __init__(self, rate):
                self.rate = rate

            def acquire(self, n):
                events.append("acquire")

        def spy_write(f, buf):
            events.append("write")
            real_write(f, buf)

        with mock.patch("downloader._RateLimiter", FakeLimiter), \
                mock.patch("downloader._write", spy_write):
            dl.DownloadTask([self.url], self.out, threads=2, retries=0,
                            slow_kb=0, timeout=20, max_speed_kb=1024).run()

        self.assertIn("acquire", events, "限速器没被调用")
        self.assertIn("write", events, "写盘点没被调用")
        self.assertLess(events.index("acquire"), events.index("write"),
                        "先写了盘才取配额：限速没有作用于写下去的字节")

    # ---------------- BUG-36 · SCHEMA.version 随接口变化递增 ----------------

    def test_bug36_schema_version_increments(self):
        """BUG-36 接口版本号必须随接口变化递增，且是整数。"""
        schema = sys.modules["dl"].SCHEMA
        self.assertIsInstance(schema["version"], int)
        self.assertGreaterEqual(schema["version"], 2,
                                "SCHEMA.version 没有随接口变化递增")

    # ---------------- BUG-28 · BaseException 须归还并发槽 ----------------

    def test_bug28_base_exception_releases_slot(self):
        """BUG-28 任务线程遇到 BaseException 也必须落终态并归还并发槽。"""
        class Boom:
            def __init__(self, *a, **kw):
                self._cancel = threading.Event()

            def run(self):
                raise KeyboardInterrupt("外部中断")

            def cancel(self):
                self._cancel.set()

        old = tq.DownloadTask
        tq.DownloadTask = Boom
        try:
            q = tq.DownloadQueue(concurrent=1)
            q.add(["http://x/1"], "out")
            end = time.time() + 3
            while time.time() < end and q.state_of(1) != "failed":
                time.sleep(0.02)
            self.assertEqual(q.state_of(1), "failed")
            self.assertEqual(list(q._running), [], "并发槽未归还")
        finally:
            tq.DownloadTask = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
