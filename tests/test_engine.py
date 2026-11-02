#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_engine.py —— 引擎行为测试（只用标准库）

覆盖批次 1 的关键改动：
  1. 正常分段下载
  2. 服务器声称支持分段却忽略 Range —— 必须兜底为单线程，不能写出坏文件
  3. 小文件走单线程
  4. ETag 变化必须作废旧分片
  5. 加权分配

运行：
    python -m unittest discover -s tests -v

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import select
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import downloader as dl  # noqa: E402
import taskqueue as tq  # noqa: E402

PAYLOAD = os.urandom(5 * 1024 * 1024)      # 5MB，恰好 5 个 1MB 分片
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


class Handler(BaseHTTPRequestHandler):
    """假服务器：mode=range 正常支持分段；mode=ignore 声称支持但忽略 Range。"""

    mode = "range"
    etag = '"v1"'
    payload = PAYLOAD
    delay = 0.0          # 每个 GET 前的延迟，用于制造「下载中」状态
    fake_size = None     # 谎报 Content-Length，用于测大小上限

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _size(self):
        return self.fake_size if self.fake_size else len(self.payload)

    def _common(self):
        self.send_header("Content-Length", str(self._size()))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", self.etag)
        self.send_header("Content-Type", "application/octet-stream")

    def do_HEAD(self):
        self.send_response(200)
        self._common()
        self.end_headers()

    def do_GET(self):
        if self.delay:
            time.sleep(self.delay)
        rng = self.headers.get("Range")
        if self.mode == "range" and rng:
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            s = int(m.group(1))
            e = int(m.group(2)) if m.group(2) else len(self.payload) - 1
            e = min(e, len(self.payload) - 1)
            body = self.payload[s:e + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {s}-{e}/{len(self.payload)}")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", self.etag)
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200)
            self._common()
            self.end_headers()
            self.wfile.write(self.payload)


class QuietServer(ThreadingHTTPServer):
    """客户端提前断开时不要往 stderr 刷 traceback。"""

    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class Socks5Server(threading.Thread):
    """最小 SOCKS5 服务：只支持无认证 CONNECT，用于验证握手实现。"""

    daemon = True

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]

    def run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    @staticmethod
    def _serve(conn):
        up = None
        try:
            _, nmethods = conn.recv(2)
            conn.recv(nmethods)
            conn.sendall(b"\x05\x00")           # 无需认证
            head = conn.recv(4)
            atyp = head[3]
            if atyp == 1:
                host = socket.inet_ntoa(conn.recv(4))
            elif atyp == 3:
                host = conn.recv(conn.recv(1)[0]).decode()
            else:
                return
            port = struct.unpack("!H", conn.recv(2))[0]
            up = socket.create_connection((host, port), 5)
            conn.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
            while True:
                r, _, _ = select.select([conn, up], [], [], 10)
                if not r:
                    break
                for s in r:
                    data = s.recv(65536)
                    if not data:
                        return
                    (up if s is conn else conn).sendall(data)
        except Exception:  # noqa: BLE001
            pass
        finally:
            for s in (conn, up):
                if s is None:
                    continue
                try:
                    s.close()
                except OSError:
                    pass


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = QuietServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        cls.url = f"http://127.0.0.1:{cls.port}/file.bin"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        Handler.mode = "range"
        Handler.etag = '"v1"'
        self.tmp = tempfile.mkdtemp(prefix="dltest_")
        self.out = os.path.join(self.tmp, "file.bin")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, **kw):
        params = dict(threads=4, retries=0, slow_kb=0, timeout=20)
        params.update(kw)
        t = dl.DownloadTask([self.url], self.out, **params)
        return t.run(), t

    def _sha(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()

    # ---------------- 用例 ----------------

    def test_chunked_normal(self):
        """正常分段：内容一致、不留临时目录、进度到 100%。"""
        seen = []
        path, t = self._run(progress=lambda d: seen.append(d.copy()))
        self.assertEqual(self._sha(path), PAYLOAD_SHA)
        self.assertFalse(os.path.exists(path + ".parts"))
        self.assertEqual(t._done, t.size)
        self.assertTrue(any(d["phase"] == "done" for d in seen))

    def test_server_ignores_range_falls_back(self):
        """REQ-001 声称支持分段却回 200：必须兜底单线程，产物正确且不留 .corrupt。"""
        Handler.mode = "ignore"
        logs = []
        path, _ = self._run(log=lambda m, lv="info": logs.append(m))
        self.assertEqual(self._sha(path), PAYLOAD_SHA)
        self.assertFalse(os.path.exists(path + ".corrupt"))
        self.assertFalse(os.path.exists(path + ".parts"))
        self.assertTrue(any("Range" in m for m in logs), "应记录忽略 Range 的说明")

    def test_small_file_single_thread(self):
        """小于 2MB 走单线程，不产生分片目录。"""
        Handler.payload = os.urandom(300 * 1024)
        try:
            path, _ = self._run()
            self.assertEqual(self._sha(path), hashlib.sha256(Handler.payload).hexdigest())
            self.assertFalse(os.path.exists(path + ".parts"))
        finally:
            Handler.payload = PAYLOAD

    def test_etag_change_discards_parts(self):
        """REQ-007 指纹变了就作废旧分片，不能把旧内容拼进新文件。"""
        chunks = [[i * 1048576, (i + 1) * 1048576 - 1] for i in range(5)]
        parts = Path(self.out + ".parts")
        parts.mkdir()
        (parts / "meta.json").write_text(json.dumps(
            {"size": len(PAYLOAD), "chunks": chunks, "mirrors": [], "etag": '"old"'}),
            encoding="utf-8")
        (parts / "part0000").write_bytes(b"\xff" * 1048576)   # 脏分片

        Handler.etag = '"v2"'
        path, _ = self._run(chunk_mb=1)
        self.assertEqual(self._sha(path), PAYLOAD_SHA, "旧分片必须被丢弃，不能被复用")
        meta = json.loads((Path(self.out + ".parts") / "meta.json").read_text(encoding="utf-8")) \
            if os.path.exists(self.out + ".parts") else {"etag": '"v2"'}
        self.assertEqual(meta.get("etag"), '"v2"')

    def test_socks5_proxy(self):
        """REQ-015 走 SOCKS5 代理完成下载，验证握手与 CONNECT 而不只是构造 opener。"""
        srv = Socks5Server()
        srv.start()
        Handler.payload = os.urandom(300 * 1024)
        try:
            path, _ = self._run(proxy=f"socks5://127.0.0.1:{srv.port}")
            self.assertEqual(self._sha(path),
                             hashlib.sha256(Handler.payload).hexdigest())
        finally:
            srv.close()
            Handler.payload = PAYLOAD

    # ---------------- 修复批次回归 ----------------

    def test_rate_limiter_small_rate(self):
        """REQ-010 限速低于块大小时不得死等（请求量必须被夹到一桶以内）。"""
        lim = dl._RateLimiter(100 * 1024)
        t0 = time.time()
        lim.acquire(dl.BLOCK)          # 256KB > 桶容量 100KB
        self.assertLess(time.time() - t0, 2.0)

    def test_filename_sanitize(self):
        """服务器给的文件名必须挡掉目录穿越、非法字符与保留设备名。"""
        def cd(v):
            return {"Content-Disposition": f'attachment; filename="{v}"'}

        self.assertEqual(dl._filename(cd("..\\..\\evil.dll"), "http://x/a"), "evil.dll")
        # "a:" 会被 ntpath 当成盘符剥掉，这正是想要的保护（不能写到别的盘）
        self.assertEqual(dl._filename(cd("a:b|c?.exe"), "http://x/a"), "b_c_.exe")
        self.assertEqual(dl._filename(cd("C:\\Windows\\x.dll"), "http://x/a"), "x.dll")
        self.assertEqual(dl._filename(cd("CON.txt"), "http://x/a"), "_CON.txt")
        self.assertIsNone(dl._filename({}, "http://x/"))

    def test_fallback_name_stable_and_unique(self):
        """没文件名时按 URL 派生：同一 URL 稳定、不同 URL 不撞名。"""
        a = dl._fallback_name("http://x/1")
        b = dl._fallback_name("http://x/2")
        self.assertNotEqual(a, b)
        self.assertEqual(a, dl._fallback_name("http://x/1"))
        self.assertTrue(a.startswith("download_") and a.endswith(".bin"))

    def test_mirror_probe_is_concurrent(self):
        """REQ-003 四个源各睡 0.3s，总耗时必须明显短于串行的 1.2s。"""
        orig = dl._measure_mirror

        def slow(u, proxy=None):
            time.sleep(0.3)
            return {"url": u, "info": {"size": 100, "ranges": True,
                                       "name": "a", "etag": None},
                    "speed": 1.0}

        dl._measure_mirror = slow
        try:
            t0 = time.time()
            ranked = dl.rank_mirrors([f"http://x/{i}" for i in range(4)],
                                     log=lambda *a, **k: None)
            elapsed = time.time() - t0
        finally:
            dl._measure_mirror = orig
        self.assertEqual(len(ranked), 4)
        self.assertLess(elapsed, 0.9, "探测没有并发")

    def test_chunk_count_independent_of_threads(self):
        """REQ-008 / REQ-016 chunk_mb=1 + threads=2 下 5MB 仍必须切成 5 片全部下完。"""
        path, _ = self._run(threads=2, chunk_mb=1)
        self.assertEqual(self._sha(path), PAYLOAD_SHA)

    def test_single_thread_ignores_range(self):
        """REQ-002 单线程路径：已有 .part 且服务器忽略 Range 时必须从头覆盖，不得续写。"""
        Handler.mode = "ignore"
        with open(self.out + ".part", "wb") as f:
            f.write(b"\xff" * 100000)
        path, _ = self._run()
        self.assertEqual(self._sha(path), PAYLOAD_SHA)
        self.assertFalse(os.path.exists(path + ".corrupt"))
        self.assertFalse(os.path.exists(path + ".part"))

    def test_next_floor(self):
        """REQ-005 动态慢速下限：未达 4 倍门限不动，达到后抬到全局的 20%。"""
        self.assertEqual(dl._next_floor(0, 1e9), 0)
        self.assertEqual(dl._next_floor(15, 50 * 1024), 15)
        self.assertEqual(dl._next_floor(15, 20 * 1024 * 1024), 4096)

    def test_backoff(self):
        """REQ-006 退避序列 1/2/4/8/8 秒，抖动不超过 0.4s。"""
        for i, base in enumerate((1, 2, 4, 8, 8, 8)):
            v = dl._backoff(i)
            self.assertGreaterEqual(v, base)
            self.assertLessEqual(v, base + 0.4)

    def test_oversized_part_self_heals(self):
        """REQ-017 超长分片必须整片重下，不能截断（截断会保住垃圾字节）。"""
        Handler.payload = os.urandom(3 * 1024 * 1024 + 100)
        Handler.etag = '"v-oversize"'
        try:
            size = len(Handler.payload)
            chunk = dl.MIN_CHUNK
            chunks = [[i * chunk, min(i * chunk + chunk - 1, size - 1)]
                      for i in range((size + chunk - 1) // chunk)]
            parts = Path(self.out + ".parts")
            parts.mkdir()
            # meta 必须与服务器指纹一致，否则分片会被整体丢弃，测不到超长分支
            (parts / "meta.json").write_text(json.dumps(
                {"size": size, "chunks": chunks, "mirrors": [],
                 "etag": Handler.etag}), encoding="utf-8")
            (parts / "part0000").write_bytes(b"\xff" * (chunk + 5000))

            path, _ = self._run(threads=4)
            self.assertEqual(self._sha(path),
                             hashlib.sha256(Handler.payload).hexdigest())
        finally:
            Handler.payload = PAYLOAD
            Handler.etag = '"v1"'

    def test_same_path_conflict(self):
        """REQ-018 同一输出路径只允许一个任务，第二个必须立刻报错而不是并行写。"""
        lock = dl._path_lock(self.out)
        self.assertTrue(lock.acquire(blocking=False))
        try:
            with self.assertRaises(dl.DownloadError) as ctx:
                self._run()
            self.assertIn("已有任务", str(ctx.exception))
        finally:
            lock.release()

        # 锁释放后同一个路径必须能正常下载
        path, _ = self._run()
        self.assertEqual(self._sha(path), PAYLOAD_SHA)

    def test_file_too_large(self):
        """REQ-019 谎报的 Content-Length 超过上限时必须直接拒绝，不预分配巨型文件。"""
        Handler.fake_size = dl.MAX_FILE_SIZE + 1024
        try:
            with self.assertRaises(dl.DownloadError) as ctx:
                self._run()
            self.assertIn("超过上限", str(ctx.exception))
            self.assertFalse(os.path.exists(self.out))
            self.assertFalse(os.path.exists(self.out + ".parts"))
        finally:
            Handler.fake_size = None


    def test_distribute_weights(self):
        """REQ-004 加权分配：片数总和精确、最快的源拿最多、退化为轮转。"""
        a = dl._distribute([100, 10, 5, 1], 32)
        self.assertEqual(len(a), 32)
        self.assertEqual(a.count(0), 28)
        self.assertEqual(dl._distribute([1, 1, 1, 1], 8), [0, 1, 2, 3, 0, 1, 2, 3])
        self.assertEqual(dl._distribute([7], 5), [0] * 5)
        self.assertEqual(dl._distribute([], 3), [0, 0, 0])
        self.assertEqual(dl._distribute([0, 0], 4), [0, 1, 0, 1])

    def test_sha512_verify(self):
        """REQ-012 128 位哈希按 SHA512 识别并通过校验（校验失败会直接抛错）。"""
        path, _ = self._run(sha256=hashlib.sha512(PAYLOAD).hexdigest())
        self.assertEqual(os.path.getsize(path), len(PAYLOAD))

    def test_hash_length_invalid(self):
        """长度不匹配任何算法时，报错要说清是长度问题而不是校验失败。"""
        with self.assertRaises(dl.DownloadError) as ctx:
            self._run(sha256="a" * 50)
        self.assertIn("不匹配任何支持的算法", str(ctx.exception))

    def test_rate_limiter(self):
        """令牌桶：桶满时首块立即放行，后续按速率阻塞。"""
        lim = dl._RateLimiter(2 * 1024 * 1024)      # 2MB/s
        lim.acquire(2 * 1024 * 1024)                # 用掉满桶
        t0 = time.time()
        lim.acquire(1024 * 1024)                    # 需等约 0.5s
        self.assertGreater(time.time() - t0, 0.25)
        self.assertLess(time.time() - t0, 2.0)

    def test_opener_cache_and_direct(self):
        """REQ-009 代理 opener 按 key 缓存，direct 与环境变量模式互不复用。"""
        self.assertIs(dl._opener("direct"), dl._opener("direct"))
        self.assertIsNot(dl._opener("direct"), dl._opener(None))
        self.assertIsNot(dl._opener("http://127.0.0.1:7890"),
                         dl._opener("http://127.0.0.1:7891"))


class QueueTest(unittest.TestCase):
    """用假任务替换 DownloadTask，只验证队列调度语义，不碰网络。"""

    class FakeTask:
        lock = threading.Lock()
        active = 0
        peak = 0

        def __init__(self, urls, out=None, log=None, progress=None, **kw):
            self._cancel = threading.Event()

        def run(self):
            cls = QueueTest.FakeTask
            with cls.lock:
                cls.active += 1
                cls.peak = max(cls.peak, cls.active)
            try:
                time.sleep(0.12)
            finally:
                with cls.lock:
                    cls.active -= 1
            return "fake.bin"

        def cancel(self):
            self._cancel.set()

    def setUp(self):
        self.orig = tq.DownloadTask
        QueueTest.FakeTask.active = 0
        QueueTest.FakeTask.peak = 0
        tq.DownloadTask = QueueTest.FakeTask

    def tearDown(self):
        tq.DownloadTask = self.orig

    @staticmethod
    def _wait(q, n, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            s = q.stats()
            if s["done"] + s["failed"] + s["cancelled"] >= n:
                return s
            time.sleep(0.02)
        return q.stats()

    def test_concurrency_cap(self):
        """REQ-013 并发上限生效：4 个任务、并发 2，峰值同时运行数不得超过 2。"""
        events = []
        q = tq.DownloadQueue(concurrent=2,
                             on_event=lambda k, tid, **kw: events.append((k, tid, kw)))
        for i in range(4):
            q.add([f"http://x/{i}"], "out")
        s = self._wait(q, 4)
        self.assertEqual(s["done"], 4)
        self.assertEqual(QueueTest.FakeTask.peak, 2)
        self.assertTrue(any(k == "state" and kw.get("state") == "running"
                            for k, _, kw in events))

    def test_cancel_queued(self):
        """排在队里的任务取消后不得再启动，其余任务照常完成。"""
        q = tq.DownloadQueue(concurrent=1)
        q.add(["http://x/1"], "a")
        t2 = q.add(["http://x/2"], "b")
        q.add(["http://x/3"], "c")
        self.assertTrue(q.cancel(t2))
        s = self._wait(q, 3)
        self.assertEqual(q.state_of(t2), "cancelled")
        self.assertEqual(s["done"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
