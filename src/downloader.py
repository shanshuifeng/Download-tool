#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
downloader.py —— 通用多线程分段下载引擎（纯标准库）

设计参考 PCL2 的实际下载行为（从 Plain Craft Launcher 2.exe 字符串表逆向得到）：
  1. 先探测是否支持分段下载（"无法确定是否支持分段下载" / "该下载源不支持分段下载"），
     不支持则退化为单线程。
  2. 多下载源并行容错（"第一下载源" / "下载源被禁用" / "但已从其他下载源获取" / "已无可用下载源"）。
  3. 速度过慢主动断链（"由于速度过慢断开链接" / "速度下限已提升到 {0}"）。
  4. 分片失败自动重试（"即将进行第 {0} 次重试"）。
  5. 下载完成后做哈希校验（"任务校验要求为 {0}" / "{0} 文件校验失败"）。
  6. 线程数不是越多越好（"设置过多的下载线程" / "否则不建议设置更多的线程数"）。

本模块是**纯引擎**，不含命令行入口：参数解析统一在 `dl.py`（契约 CLI-010）。

作为库使用：
    from downloader import DownloadTask
    t = DownloadTask(urls=[...], out_path=r"D:\\a.zip", threads=16,
                     sha256=None, log=print, progress=cb)
    t.run()

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import random
import shutil
import sys
import threading
import time

import diskutil
import naming
import resume
from httpinfo import (http_code, is_permanent_http_error, probe,  # noqa: F401  probe 再导出
                      range_rejected)
from mirrors import (build_mirror_urls,  # noqa: F401  公开符号再导出
                    expand_mirror_urls, is_github_release)
from netio import _opener, _request  # noqa: F401  _opener 供测试引用

BLOCK = 256 * 1024          # 单次读取块
MIN_CHUNK = 1 * 1024 * 1024  # 单片最小 1MB
MAX_CHUNK = 32 * 1024 * 1024  # 单片最大 32MB
SLOW_BYTES = 15 * 1024      # 低于 15KB/s
SLOW_WINDOW = 12            # 持续 12 秒判定为慢链
MAX_RETRY = 6

# 命令行退出码（CLI-002）。放在引擎层，异常才能自带退出码，
# 命令行入口不必再依据错误文案判定。
EXIT_FAIL = 1
EXIT_NO_MIRROR = 3

_HASH_BY_LEN = {32: "md5", 40: "sha1", 64: "sha256", 128: "sha512"}

# 挡谎报 Content-Length 的服务器：超过这个体积直接拒绝，不做预分配
MAX_FILE_SIZE = 200 * 1024 ** 3      # 200GB

_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: str) -> threading.Lock:  # @contract CORE-019
    """按规范化的绝对路径取进程内互斥锁，防止两个任务写同一个文件。"""
    key = os.path.normcase(os.path.abspath(path))
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.Lock())


class DownloadError(Exception):
    """对外唯一的异常类型。

    code 为命令行退出码（CLI-002），缺省为 1；命令行入口直接取用该字段，
    不再通过错误文案判断失败类型。
    """

    def __init__(self, message: str, code: int = EXIT_FAIL):
        super().__init__(message)
        self.code = code


class _RateLimiter:  # @contract CORE-014
    """令牌桶限速：跨线程共享，acquire(n) 阻塞到允许发送 n 字节。

    桶容量取 1 秒的量，既能吸收突发，又不会让限速严重滞后。
    单次请求不会超过 BLOCK（256KB），远小于容量，因此不会饿死。
    """

    def __init__(self, bytes_per_sec: int):
        self.rate = max(1, int(bytes_per_sec))
        self.cap = float(self.rate)
        self.tokens = float(self.rate)
        self.last = time.time()
        self._lock = threading.Lock()

    def acquire(self, n: int) -> None:
        if n <= 0:
            return
        # 单次请求不能超过一桶的量，否则 tokens >= n 永远不成立（会死等）
        n = min(n, int(self.cap))
        while True:
            with self._lock:
                now = time.time()
                self.tokens = min(self.cap, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= n:
                    self.tokens -= n
                    return
                wait = (n - self.tokens) / self.rate
            time.sleep(min(wait, 0.5))


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}GB"


def _credited(size: int, want: int) -> int:  # @contract CORE-025
    """分片计入进度的字节数。超过期望的一分不算：这片无效，必须整片重下。

    进度与合并校验必须同源，否则会出现「进度满格然后失败」（BUG-32）。
    """
    return size if 0 <= size <= want else 0


def _write(f, buf: bytes) -> None:
    """唯一的写盘点。抽出来是为了让「磁盘满」这条路径能被测试注入。"""
    f.write(buf)


def _safe_name(name: str) -> str | None:
    """落盘安全文件名。实现见 naming.safe_name，此处只保留旧名以兼容既有引用。"""
    return naming.safe_name(name)


def _fallback_name(url: str) -> str:
    """按 URL 派生的稳定文件名。实现见 naming.fallback_name。"""
    return naming.fallback_name(url)


def _filename(headers, url) -> str | None:
    """从响应头与 URL 取文件名。实现见 naming.filename_from。"""
    return naming.filename_from(headers, url)


def _measure_mirror(u: str, proxy=None) -> dict:
    """单源测速：探测元信息 + 拉 256KB 量吞吐。"""
    info = probe(u, proxy=proxy)
    if info["size"] is None:
        return {"url": u, "info": info, "speed": 0.0, "failed": True}
    if info["size"] == 0:
        # 空文件没有吞吐可测，也省掉一次必然为空的请求（BUG-01）
        return {"url": u, "info": info, "speed": 0.0}
    speed = 0.0
    try:
        with _request(u, "GET", {"Range": "bytes=0-262143"},
                      timeout=12, proxy=proxy) as r:
            # 计时从响应头到达后开始：DNS/连接/TLS/探测耗时不计入分母，
            # 它们与源快慢无关（BUG-34）。首字节延迟仍计入。
            t0 = time.time()
            # 只读固定窗口：源忽略 Range 时 r.read() 会把整个文件读进内存（BUG-17）
            got, limit = 0, 256 * 1024
            while got < limit:
                buf = r.read(min(BLOCK, limit - got))
                if not buf:
                    break
                got += len(buf)
        dt = time.time() - t0
        speed = got / dt if dt > 0 else 0.0
    except Exception:
        pass
    return {"url": u, "info": info, "speed": speed}


def rank_mirrors(urls: list[str], log=print, proxy=None) -> list[dict]:  # @contract CORE-007
    """并发测速后按可用性与速度排序。

    并发是必须的：每个源最坏要等一个 15s 超时，串行测 4 个源就是白等 60s。
    日志在全部返回后按原始顺序补打，保证输出稳定可读。
    """
    if not urls:
        return []
    box: dict[int, dict] = {}

    def work(i, u):
        box[i] = _measure_mirror(u, proxy=proxy)

    threads = [threading.Thread(target=work, args=(i, u), daemon=True)
               for i, u in enumerate(urls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    results = []
    for i, u in enumerate(urls):
        results.append(box.get(i) or {
            "url": u, "info": {"size": 0, "error": "探测未返回"},
            "speed": 0.0, "failed": True})
    for r in results:
        if r.get("failed"):
            reason = r["info"].get("error") or "无法获取文件大小"
            log(f"  镜像不可用，跳过：{r['url']}\n    原因：{reason}")
        else:
            log(f"  镜像 {r['url']}  →  {human(r['speed'])}/s，"
                f"大小 {human(r['info']['size'])}")
    results.sort(key=lambda x: (x.get("failed", False), -x["speed"]))
    return results


def _distribute(weights: list[float], n: int) -> list[int]:  # @contract CORE-008
    """按权重把 n 个分片分配给各镜像，返回长度 n 的镜像下标序列。

    最大余数法保证配额总和精确等于 n，再按轮转交错输出，
    避免连续分片挤在同一个源上。等权重时退化为轮转。
    """
    if n <= 0:
        return []
    if not weights:
        return [0] * n
    total = sum(w for w in weights if w > 0)
    if total <= 0:
        return [i % len(weights) for i in range(n)]

    share = [max(0.0, w) / total * n for w in weights]
    quota = [int(x) for x in share]
    rest = n - sum(quota)
    order = sorted(range(len(share)), key=lambda i: share[i] - quota[i], reverse=True)
    for i in order[:max(0, rest)]:
        quota[i] += 1

    out = []
    while len(out) < n:
        for i, q in enumerate(quota):
            if q > 0:
                out.append(i)
                quota[i] -= 1
                if len(out) >= n:
                    break
    return out


def _next_floor(slow_kb: int, speed_bytes: float) -> int:  # @contract CORE-009
    """全局速度够快时把慢速下限抬到 20%；未达 4 倍门限不动。"""
    if not slow_kb:
        return 0
    g = int(speed_bytes / 1024)
    if g < slow_kb * 4:
        return slow_kb
    return max(slow_kb, int(g * 0.2))


def _backoff(attempt: int) -> float:  # @contract CORE-006
    """指数退避 + 抖动：1/2/4/8/8 秒。"""
    return min(8.0, 2.0 ** attempt) + random.uniform(0, 0.4)


class DownloadTask:
    def __init__(self, urls, out_path=None, threads=16, sha256=None,
                 log=None, progress=None, verify_hash=None,
                 chunk_mb=None, slow_kb=SLOW_BYTES // 1024,
                 slow_sec=SLOW_WINDOW, retries=MAX_RETRY, timeout=30,
                 proxy=None, max_speed_kb=0):
        self.urls = list(urls)
        self.out_path = out_path
        self.threads = max(1, min(int(threads), 64))  # @contract CORE-004
        self.sha256 = (sha256 or "").strip().lower() or None
        self.verify_hash = (verify_hash or "").strip().lower() or None
        self.chunk_mb = chunk_mb            # None/0 = 自动按文件大小均分
        self.slow_kb = max(0, int(slow_kb))  # 0 = 关闭慢速断链
        self.slow_sec = max(3, int(slow_sec))
        self.retries = max(0, min(int(retries), 20))
        self.timeout = max(5, min(int(timeout), 300))
        self.proxy = (proxy or "").strip() or None
        self.max_speed_kb = max(0, int(max_speed_kb))
        self._limiter = (_RateLimiter(self.max_speed_kb * 1024)
                         if self.max_speed_kb else None)
        self._log = log or (lambda m, *a: None)
        self._progress = progress or (lambda d: None)
        self._cancel = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._done = 0
        self._total = 0
        self._errors = []
        self.mirrors = []
        self.mirror_speeds = []        # 与 mirrors 同序，用于加权分配
        self.etag = None               # 续传指纹（ETag / Last-Modified）
        self.size = 0
        self.actual_hash = None        # 校验时算出的值，供 dl.py 复用（BUG-09）
        self.hash_algo = None
        self._floor_kb = self.slow_kb  # 动态慢速下限，由 reporter 抬升
        self._no_range_mirrors = set()   # 观测到「忽略 Range」的镜像下标
        self._all_no_range = False       # 全部镜像都忽略 Range 时才退化为单线程
        self._fatal = None             # 磁盘满这类不可重试错误，由 worker 抛出

    # ---------- 公共 ----------
    def cancel(self):
        self._cancel.set()
        self._stop.set()

    @property
    def cancelled(self) -> bool:
        """是否已请求取消。队列等外部代码只读此公开属性，不触碰 `_cancel`。"""
        return self._cancel.is_set()

    def log(self, msg, level="info"):
        try:
            self._log(msg, level)
        except TypeError:
            self._log(msg)

    def _emit(self, phase="downloading", speed=0.0):  # @contract CORE-005b
        total = self._total or 0
        self._progress({
            "phase": phase,
            "done": self._done,
            "total": total,
            "percent": (self._done / total * 100) if total else 0,
            "speed": speed,
        })

    # ---------- 主流程 ----------
    def run(self):
        self.log("解析链接…")
        # 所有入口统一在这里补加速源，界面与命令行的行为因此一致（CORE-007）
        ranked = rank_mirrors(expand_mirror_urls(self.urls),
                              log=lambda m: self.log(m), proxy=self.proxy)
        ok = [r for r in ranked if not r.get("failed")]
        if not ok:
            # 汇总所有源的真实原因，给出可操作的提示
            reasons = []
            for r in ranked:
                e = r["info"].get("error")
                if e and e not in reasons:
                    reasons.append(e)
            detail = "；".join(reasons) if reasons else "未能获取文件大小"
            raise DownloadError(
                f"所有下载源都不可用\n  原因：{detail}\n  建议：检查链接是否有效、是否需要登录，或换一个下载源",
                code=EXIT_NO_MIRROR)

        best = ok[0]
        self.mirrors = [r["info"]["url"] for r in ok]
        self.mirror_speeds = [r["speed"] for r in ok]
        self.etag = best["info"].get("etag")
        self.size = best["info"]["size"] or 0
        self._total = self.size

        name = best["info"]["name"] or _fallback_name(best["info"]["url"])
        out = self.out_path or name
        if os.path.isdir(out) or not os.path.splitext(out)[1]:
            home = out
            out = os.path.join(out, name)
        else:
            home = os.path.dirname(os.path.abspath(out)) or "."
        self.out_path = out

        if self.size > MAX_FILE_SIZE:
            raise DownloadError(
                f"文件大小 {human(self.size)} 超过上限 {human(MAX_FILE_SIZE)}，已拒绝\n"
                f"  如果确实要下这么大的文件，请用 curl/aria2 这类不限量的工具")

        # 预检必须在建目录之前：路径太长、盘装不下，不该等下载完才说（BUG-06/08）
        try:
            tight = diskutil.check_target(out, self.size)  # @contract CORE-023
        except diskutil.DiskError as e:
            raise DownloadError(str(e)) from None
        try:
            os.makedirs(home, exist_ok=True)
            os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        except OSError as e:
            # 盘符不存在、目录只读：别把 FileNotFoundError 直接甩给用户
            raise DownloadError(f"保存位置不可用：{home}\n  原因：{e}") from None
        if tight:
            self.log(tight, "warn")

        ranges = best["info"]["ranges"]
        self.log(f"文件大小 {human(self.size)}，分段下载：{'支持' if ranges else '不支持（退化为单线程）'}")
        if len(self.mirrors) > 1 and not (self.sha256 or self.verify_hash):
            # 镜像只保证连通，不保证内容；没法强制，至少要吵一声（BUG-07）
            self.log("正在经镜像下载且未提供哈希，文件内容无法验证", "warn")

        # 同一路径只允许一个任务：并发写同一个 .parts 会互相覆盖分片
        lock = _path_lock(out)
        if not lock.acquire(blocking=False):
            raise DownloadError(
                f"同一文件已有任务在下载：{out}\n  等它结束，或换个保存位置/文件名")
        try:
            return self._fetch(best["info"]["url"], ranges)
        finally:
            lock.release()

    def _fetch(self, best_url, ranges):
        """路径锁已持有后的实际下载与校验。"""
        if ranges and self.size > MIN_CHUNK * 2:
            try:
                self._download_chunked()
            except DownloadError:
                # 探测说支持分段，实际所有源都不给分段（忽略或拒绝 Range）：
                # 退化单线程，别留坏文件。
                # 只有一个源如此时不能退化——部分源不支持分段不应作废已下载的分片
                if not self._all_no_range or self._cancel.is_set():
                    raise
                self.log("所有源都不支持分段（忽略或拒绝 Range），退化单线程重下", "warn")
                shutil.rmtree(self.out_path + ".parts", ignore_errors=True)
                self._errors.clear()
                with self._lock:
                    self._done = 0
                self._download_single(self.mirrors[0])
        else:
            self._download_single(best_url)

        if self._cancel.is_set():
            raise DownloadError("已取消（已下载的分片保留，下次可续传）")

        self._emit("verifying", 0)
        self._verify()
        self.log(f"完成：{self.out_path}", "ok")
        self._emit("done", 0)
        return self.out_path

    # ---------- 单线程 ----------
    def _download_single(self, url):  # @contract CORE-012
        tmp = self.out_path + ".part"
        have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        if have:
            # @contract CORE-021
            if not resume.matches(resume.load(self.out_path), self.size, self.etag):
                # 分片路径靠 meta.json 判定能否复用；单线程只有 .part 的大小，
                # 远端换同长度内容时会拼出既非旧也非新的文件（BUG-15）
                self.log("续传指纹不符（文件已变化或缺少指纹），从头下载", "warn")
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                have = 0
            elif not self.etag:
                self.log("服务器未提供 ETag，续传无法检测同长度变更", "warn")
        with self._lock:
            # 夹到总长以内：percent 不得越过 100%（CORE-025）
            self._done = min(have, self.size) if self.size else have
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with _request(url, "GET", headers, timeout=self.timeout,
                          proxy=self.proxy) as r:
                if r.status not in (200, 206):
                    raise DownloadError(f"HTTP {r.status}")
                mode = "ab"
                if have and r.status == 200:
                    # 服务器忽略了 Range，响应是完整文件：丢掉已下部分，从头覆盖写
                    self.log("服务器忽略了 Range 请求，从头重下", "warn")
                    with self._lock:
                        self._done = 0
                    have, mode = 0, "wb"
                if not have:
                    # 落盘前先写指纹：写一半断电，下次也能判断这份 .part 属于谁
                    resume.save(self.out_path, size=self.size,
                                etag=self.etag, url=url)
                with open(tmp, mode) as f:
                    t_last, n_last = time.time(), self._done
                    while True:
                        if self._cancel.is_set():
                            return
                        buf = r.read(BLOCK)
                        if not buf:
                            break
                        if self._limiter:
                            # 先取配额再落盘：限速作用于真正写下去的字节（CORE-014）
                            self._limiter.acquire(len(buf))
                        _write(f, buf)
                        with self._lock:
                            # 夹到总长以内：percent 不得越过 100%（CORE-025）
                            self._done = min(self._done + len(buf), self.size) \
                                if self.size else self._done + len(buf)
                        now = time.time()
                        if now - t_last >= 0.5:
                            sp = (self._done - n_last) / (now - t_last)
                            self._emit("downloading", sp)
                            t_last, n_last = now, self._done
        except DownloadError:
            raise
        except OSError as e:
            if diskutil.is_disk_full(e):
                raise DownloadError(
                    "磁盘空间不足，下载已中止（已下载的 .part 保留）") from None
            raise DownloadError(f"下载失败：{e}")
        except Exception as e:
            raise DownloadError(f"下载失败：{e}")
        if os.path.exists(self.out_path):
            os.remove(self.out_path)
        os.replace(tmp, self.out_path)
        resume.clear(self.out_path)

    # ---------- 多线程分片 ----------
    def _download_chunked(self):
        n = self.threads
        if self.chunk_mb:
            chunk = int(min(MAX_CHUNK, max(MIN_CHUNK, self.chunk_mb * 1024 * 1024)))
        else:
            # 主动切细：目标分片数取线程数的 4 倍（受最小分片约束）。
            # 固定线程池靠队列取片，粒度够细才能让快线程接走慢线程剩下的活
            want = max(n, min(n * 4, max(1, self.size // MIN_CHUNK)))
            chunk = (self.size + want - 1) // want
            chunk = min(MAX_CHUNK, max(MIN_CHUNK, chunk))

        # 分片数由文件大小决定，线程数只限制并发。两者混为一谈会让尾部丢数据
        n_chunks = max(1, (self.size + chunk - 1) // chunk)
        chunks = [[i * chunk, min(i * chunk + chunk - 1, self.size - 1)]
                  for i in range(n_chunks)]
        workers = min(n, len(chunks))

        parts_dir = self.out_path + ".parts"
        os.makedirs(parts_dir, exist_ok=True)
        meta_path = os.path.join(parts_dir, "meta.json")

        # 断点续传：边界与指纹都一致才复用
        old = None
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    old = json.load(f)
            except Exception:
                old = None
        if (not old or old.get("size") != self.size
                or old.get("chunks") != chunks or old.get("etag") != self.etag):
            for f in os.listdir(parts_dir):
                if f.startswith("part"):
                    os.remove(os.path.join(parts_dir, f))

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"size": self.size, "chunks": chunks,
                       "mirrors": self.mirrors, "etag": self.etag}, f)

        # 统计已有进度。超长片计 0：它无效，必须整片重下（BUG-32/33）
        for i, (s, e) in enumerate(chunks):
            p = os.path.join(parts_dir, f"part{i:04d}")
            if os.path.exists(p):
                self._done += _credited(os.path.getsize(p), e - s + 1)

        assign = _distribute(self.mirror_speeds, len(chunks))
        self.log(f"分 {len(chunks)} 片，每片约 {human(chunk)}，并发 {workers} 线程")
        if len(self.mirrors) > 1:
            lead = assign.count(0)
            self.log(f"  最快源承担 {lead}/{len(chunks)} 片，其余按测速分摊")
        t0 = time.time()
        last = [self._done, time.time()]

        def reporter():
            ema = 0.0
            while not self._stop.is_set():
                time.sleep(0.5)
                now = time.time()
                with self._lock:
                    cur = self._done
                sp = (cur - last[0]) / (now - last[1]) if now > last[1] else 0
                last[0], last[1] = cur, now
                ema = sp if ema == 0 else ema * 0.6 + sp * 0.4
                # 动态慢速下限：全局够快时才抬高，且只升不降，避免来回抖。
                # 开了每任务限速时不判定慢链，否则正常分片会被限速本身误杀。
                if self.slow_kb and not self._limiter:
                    floor = _next_floor(self.slow_kb, ema)
                    if floor > self._floor_kb:
                        self._floor_kb = floor
                if self._total and cur >= self._total:
                    break
                self._emit("downloading", ema)

        rt = threading.Thread(target=reporter, daemon=True)
        rt.start()

        # 固定线程池从队列领片：分片数可以远多于线程数
        pending: queue.Queue[int] = queue.Queue()
        for i in range(len(chunks)):
            pending.put(i)

        def pump():
            while not self._cancel.is_set() and self._fatal is None:
                try:
                    i = pending.get_nowait()
                except queue.Empty:
                    return
                s, e = chunks[i]
                self._worker(i, s, e, parts_dir, assign[i])

        threads = [threading.Thread(target=pump, daemon=True) for _ in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self._stop.set()  # 停掉 reporter

        if self._fatal:
            raise self._fatal
        if self._errors and not self._cancel.is_set():
            raise DownloadError(f"{len(self._errors)} 个分片失败，已保留进度可重试")

        self.log("合并分片…")
        # 预分配输出再按偏移写入：写一片删一片，峰值磁盘 ≈ 总量 + 一片
        mode = "r+b" if os.path.exists(self.out_path) else "w+b"
        try:
            self._merge(chunks, parts_dir, mode)
        except OSError as e:
            if not diskutil.is_disk_full(e):
                raise
            # 保留分片，删掉半成品：留一个长度正确的空壳比没有更危险
            try:
                os.remove(self.out_path)
            except OSError:
                pass
            raise DownloadError(
                "磁盘空间不足，合并分片失败；已下载的分片保留，腾出空间后可重试") from None
        shutil.rmtree(parts_dir, ignore_errors=True)
        self.log(f"耗时 {time.time()-t0:.1f}s")

    def _merge(self, chunks, parts_dir, mode):
        with open(self.out_path, mode) as out:
            out.truncate(self.size)
            for i, (start, end) in enumerate(chunks):
                if self._cancel.is_set():
                    raise DownloadError("已取消（分片保留，下次可续传）")
                p = os.path.join(parts_dir, f"part{i:04d}")
                want = end - start + 1
                got = os.path.getsize(p)
                if got != want:
                    # 按固定偏移写，短片会变成中间一段零字节且总长仍然正确，
                    # 尺寸校验查不出来，所以必须在这里拦住
                    raise DownloadError(
                        f"分片{i}长度异常（{got}≠{want}），已保留进度可重试")
                out.seek(start)
                with open(p, "rb") as f:
                    shutil.copyfileobj(f, out, 4 * 1024 * 1024)
                os.remove(p)

    def _worker(self, idx, start, end, parts_dir, mirror_idx=0):  # @contract CORE-011
        path = os.path.join(parts_dir, f"part{idx:04d}")
        want = end - start + 1
        permanent = set()   # 本片已确认「永久失败」的源下标：换源也没救
        # 本片当前计入进度的字节数：与 self._done 同口径，且等于
        # _credited(本片当前长度, want)（CORE-025）。续传扫描时已按同一
        # 口径计过，这里接着算，不重复计入。
        credited = _credited(os.path.getsize(path) if os.path.exists(path) else 0, want)
        for attempt in range(self.retries + 1):
            if self._cancel.is_set():
                return
            have = os.path.getsize(path) if os.path.exists(path) else 0
            if have > want:
                # 超长说明这个分片不属于当前区间（被别人写过/上次异常）。
                # 截断只会保住前面的垃圾字节，静默产出坏文件；必须整片重下
                with self._lock:
                    # 计入与扣减走同一个函数：口径不会分叉（BUG-33）
                    self._done -= _credited(have, want)
                credited = 0
                try:
                    os.remove(path)
                except OSError:
                    pass
                have = 0
            if have >= want:
                return
            url_idx = (mirror_idx + attempt) % len(self.mirrors)
            url = self.mirrors[url_idx]
            headers = {"Range": f"bytes={start + have}-{end}"}
            try:
                with _request(url, "GET", headers, timeout=self.timeout,
                              proxy=self.proxy) as r:
                    if r.status not in (200, 206):
                        raise DownloadError(f"HTTP {r.status}")
                    if r.status == 200 and (have > 0 or want != self.size):
                        # 声称支持分段却回了整文件：继续 append 会写出超长分片。
                        # 记录该源忽略 Range 后换源重试；全部源都如此才整体退化
                        with self._lock:
                            self._no_range_mirrors.add(url_idx)
                        raise DownloadError("服务器忽略了 Range 请求")
                    size = have       # 本片当前在磁盘上的字节数
                    overflow = False
                    with open(path, "ab") as f:
                        got, t0 = 0, time.time()
                        while True:
                            if self._cancel.is_set():
                                return
                            buf = r.read(BLOCK)
                            if not buf:
                                break
                            if size + len(buf) > want:
                                # 该源返回的数据超出本片区间：多出的部分属于
                                # 别的分片，落盘即污染本片。先判后写，整片重下
                                overflow = True
                                break
                            if self._limiter:
                                # 先取配额再落盘：限速作用于真正写下去的字节（CORE-014）
                                self._limiter.acquire(len(buf))
                            _write(f, buf)
                            got += len(buf)
                            size += len(buf)
                            new_credit = _credited(size, want)
                            with self._lock:
                                self._done += new_credit - credited
                            credited = new_credit
                            el = time.time() - t0
                            if (self.slow_kb and not self._limiter and el > self.slow_sec
                                    and got / el < self._floor_kb * 1024):
                                raise DownloadError("速度过慢，切换下载源")
                    if overflow:
                        # 整片作废并回退进度：与计入同源，口径不分叉（CORE-025）
                        with self._lock:
                            self._done -= _credited(size, want)
                        credited = 0
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                        raise DownloadError("服务器返回的数据超出分片范围")
                    if os.path.getsize(path) >= want:
                        return
            except Exception as e:
                if diskutil.is_disk_full(e):   # @contract CORE-022
                    # 磁盘满不是网络问题，重试只会让用户多等 30 秒（BUG-10）
                    with self._lock:
                        self._fatal = DownloadError(
                            "磁盘空间不足，下载已中止（已下载的分片保留）")
                    return
                if range_rejected(e):   # @contract CORE-024
                    # 416：服务器按 RFC 7233 拒绝了 Range，等同于「该源不支持分段」
                    with self._lock:
                        self._no_range_mirrors.add(url_idx)
                        all_bad = len(self._no_range_mirrors) >= len(self.mirrors)
                        if all_bad:
                            self._all_no_range = True
                            # 与磁盘满同一条通路：分片阶段到此为止，交给 _fetch 退化
                            self._fatal = DownloadError("所有下载源都拒绝了 Range 请求")
                    if all_bad:
                        return
                    self.log(f"  分片{idx} 第{attempt+1}次失败（该源不支持分段），换源重试", "warn")
                    continue
                if is_permanent_http_error(e):   # @contract CORE-024
                    # 401/403/404 这类错误重试也没用，但换源可能有效：不退避，直接换
                    permanent.add(url_idx)
                    if len(permanent) >= len(self.mirrors):
                        self.log(f"  分片{idx} 失败（HTTP {http_code(e)}，换源也无法解决）", "warn")
                        with self._lock:
                            self._errors.append(idx)
                        return
                    self.log(f"  分片{idx} 第{attempt+1}次失败（HTTP {http_code(e)}），换源重试", "warn")
                    continue
                self.log(f"  分片{idx} 第{attempt+1}次失败（{e}），换源重试", "warn")
                # 指数退避 + 抖动：避免多分片同时重连打爆服务端
                time.sleep(_backoff(attempt))
        with self._lock:
            if len(self._no_range_mirrors) >= len(self.mirrors):
                self._all_no_range = True
            self._errors.append(idx)

    # ---------- 校验 ----------
    def _quarantine(self, reason: str) -> str:
        """把校验失败的文件改名隔离，避免用户误以为下载成功。"""
        bad = self.out_path + ".corrupt"
        try:
            if os.path.exists(bad):
                os.remove(bad)
            os.replace(self.out_path, bad)
            return bad
        except Exception:
            # 改名失败就退而删除，宁可没有也不能留下坏文件
            try:
                os.remove(self.out_path)
                return "（已删除）"
            except Exception:
                return "（无法处理，请手动删除）"

    def _verify(self):
        want = self.sha256 or self.verify_hash
        size = os.path.getsize(self.out_path)
        if self.size and size != self.size:
            bad = self._quarantine("大小不符")
            raise DownloadError(
                f"文件大小不一致：期望 {self.size}，实际 {size}\n"
                f"  已隔离到：{bad}")
        if not want:
            self.log("未提供哈希，跳过校验（大小已核对）")
            return
        if len(want) not in _HASH_BY_LEN:
            raise DownloadError(
                f"哈希长度 {len(want)} 不匹配任何支持的算法"
                f"（md5=32 / sha1=40 / sha256=64 / sha512=128）")
        algo = _HASH_BY_LEN[len(want)]
        h = hashlib.new(algo)
        with open(self.out_path, "rb") as f:
            while True:
                if self._cancel.is_set():
                    raise DownloadError("已取消（文件已下载，未完成校验）")
                block = f.read(4 * 1024 * 1024)
                if not block:
                    break
                h.update(block)
        got = h.hexdigest()
        self.actual_hash, self.hash_algo = got, algo
        if got != want:
            bad = self._quarantine("哈希不符")
            raise DownloadError(
                f"{algo.upper()} 校验失败\n  期望 {want}\n  实际 {got}\n"
                f"  已隔离到：{bad}")
        self.log(f"{algo.upper()} 校验通过", "ok")


# ---------------- 引擎不是入口 ----------------
# 命令行能力统一收敛到 dl.py（CLI-010）。这里保留守卫只是为了让直接运行
# 本文件的人看到明确指引，而不是「静默成功」（BUG-30）。
if __name__ == "__main__":      # @contract CLI-010
    sys.exit("命令行入口已收敛到 dl.py，请改用：python src/dl.py --help")
