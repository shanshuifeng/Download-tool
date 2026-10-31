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

命令行用法：
    python downloader.py <URL> [-o 保存目录或文件] [-t 线程数] [--sha256 值] [--mirror 额外镜像...]

作为库使用：
    from downloader import DownloadTask
    t = DownloadTask(urls=[...], out_path=r"D:\\a.zip", threads=16,
                     sha256=None, log=print, progress=cb)
    t.run()
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import random
import re
import shutil
import socket
import sys
import threading
import time
import urllib.parse
from collections import deque

from netio import UA, _opener, _request  # noqa: F401

# GitHub release 直连在国内基本不可用，按实测速度排序的可用镜像
GITHUB_MIRRORS = [
    "https://gh-proxy.com/",
    "https://ghfast.top/",
    "https://ghproxy.net/",
]

BLOCK = 256 * 1024          # 单次读取块
MIN_CHUNK = 1 * 1024 * 1024  # 单片最小 1MB
MAX_CHUNK = 32 * 1024 * 1024  # 单片最大 32MB
SLOW_BYTES = 15 * 1024      # 低于 15KB/s
SLOW_WINDOW = 12            # 持续 12 秒判定为慢链
MAX_RETRY = 6

_HASH_BY_LEN = {32: "md5", 40: "sha1", 64: "sha256", 128: "sha512"}


class DownloadError(Exception):
    pass


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


def _probe_error_hint(url: str, exc: Exception) -> str:  # @contract CORE-006b
    """把底层异常翻译成用户能据此行动的原因说明。"""
    u = (url or "").lower()
    if not u.startswith(("http://", "https://")):
        return "链接格式不对，需要以 http:// 或 https:// 开头"

    msg = str(exc)
    low = msg.lower()

    # HTTP 状态码
    m = re.search(r"HTTP Error (\d{3})", msg)
    if m:
        code = int(m.group(1))
        table = {
            400: "服务器认为请求有误（400）",
            401: "需要登录或授权（401），请改用带凭证的直链",
            403: "被拒绝访问（403），多半是防盗链，请从浏览器复制真实下载链接",
            404: "文件不存在（404），链接可能已失效",
            405: "服务器不允许该请求方式（405）",
            410: "文件已被删除（410）",
            416: "服务器不支持当前分段请求（416）",
            429: "请求过于频繁被限流（429），稍后再试或减少线程数",
            500: "服务器内部错误（500）",
            502: "网关错误（502）",
            503: "服务暂不可用（503）",
            504: "网关超时（504）",
        }
        return table.get(code, f"服务器返回错误 {code}")

    # 网络层
    if isinstance(exc, socket.gaierror) or "getaddrinfo" in low or "name or service not known" in low:
        return "域名解析失败，请检查域名拼写或本机 DNS"
    if "certificate" in low or "ssl" in low:
        return "TLS 证书校验失败，可能是证书过期或中间人代理"
    if "timed out" in low or isinstance(exc, (socket.timeout, TimeoutError)):
        return "连接超时，请检查网络，或把超时时间调大"
    if ("connection refused" in low or "actively refused" in low
            or "积极拒绝" in msg):
        return "连接被拒绝，目标端口未开放"
    if "reset by peer" in low or "connection reset" in low:
        return "连接被重置，可能被中间设备阻断"
    if "no route to host" in low or "unreachable" in low:
        return "网络不可达，请检查网络连接"
    if "too many redirects" in low:
        return "重定向次数过多，链接可能有问题"

    return msg or exc.__class__.__name__


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}GB"


def is_github_release(url: str) -> bool:
    return "github.com" in url and ("/releases/download/" in url or "/raw/" in url)


def build_mirror_urls(url: str) -> list[str]:  # @contract CORE-007
    """给 GitHub 链接自动补上加速镜像候选；普通链接原样返回。"""
    urls = [url]
    if is_github_release(url) and not any(m in url for m in GITHUB_MIRRORS):
        for m in GITHUB_MIRRORS:
            urls.append(m + url)
    return urls



def probe(url: str, timeout=15, proxy=None):  # @contract CORE-006
    """探测：最终 URL、文件大小、是否支持 Range、建议文件名、续传指纹。

    失败时在返回值的 error 字段里带上原因，供上层给出可操作的提示。
    """
    size, ranges, final, name, etag = None, False, url, None, None
    errors = []

    # 先试 HEAD
    try:
        with _request(url, "HEAD", timeout=timeout, proxy=proxy) as r:
            final = r.geturl()
            cl = r.headers.get("Content-Length")
            ar = (r.headers.get("Accept-Ranges") or "").lower()
            size = int(cl) if cl and cl.isdigit() else None
            ranges = ar == "bytes"
            name = _filename(r.headers, final)
            etag = _etag_of(r.headers)
    except Exception as e:
        errors.append(e)

    # HEAD 不被支持或被拒绝时，用 1 字节 Range 探测
    if size is None or not ranges:
        try:
            with _request(url, "GET", {"Range": "bytes=0-0"},
                          timeout=timeout, proxy=proxy) as r:
                final = r.geturl()
                cr = r.headers.get("Content-Range") or ""
                m = re.search(r"/(\d+)", cr)
                if m:
                    size = int(m.group(1))
                    ranges = True
                elif size is None:
                    cl = r.headers.get("Content-Length")
                    size = int(cl) if cl and cl.isdigit() else None
                name = _filename(r.headers, final) or name
                etag = etag or _etag_of(r.headers)
        except Exception as e:
            errors.append(e)

    err = None
    if not size:
        # 优先报 HTTP 状态类错误（信息量最大），否则报第一个
        http_errs = [e for e in errors if re.search(r"HTTP Error \d{3}", str(e))]
        pick = (http_errs or errors or [None])[0]
        err = _probe_error_hint(url, pick) if pick else "无法获取文件大小，服务器可能不支持该请求"

    return {"url": final, "size": size, "ranges": ranges, "name": name,
            "etag": etag, "error": err}


def _etag_of(headers) -> str | None:
    """续传指纹：优先 ETag，退回 Last-Modified。"""
    return headers.get("ETag") or headers.get("Last-Modified")


_WIN_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WIN_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{p}{i}" for p in ("com", "lpt") for i in range(1, 10)}


def _safe_name(name: str) -> str | None:
    """把服务器给的文件名变成能安全落盘的名字。

    只取最后一段（挡 ../ 穿越）、替换 Windows 非法字符、避开保留设备名。
    返回 None 表示这个名字不可用，调用方应退回默认名。
    """
    if not name:
        return None
    base = os.path.basename(name.replace("\\", "/")).strip().strip(".")
    base = _WIN_BAD.sub("_", base).strip()
    if not base or base in (".", ".."):
        return None
    if base.split(".")[0].lower() in _WIN_RESERVED:
        base = "_" + base
    return base[:120]


def _fallback_name(url: str) -> str:
    """服务器没给文件名时，用 URL 派生稳定名，避免多个任务都叫 download.bin。"""
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"download_{h}.bin"


def _filename(headers, url) -> str | None:
    cd = headers.get("Content-Disposition") or ""
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", cd, re.I)
    if m:
        got = _safe_name(urllib.parse.unquote(m.group(1).strip()))
        if got:
            return got
    path = urllib.parse.urlparse(url).path
    base = _safe_name(urllib.parse.unquote(os.path.basename(path)))
    if base:
        if "." in base:
            return base
        # 无扩展名但看起来像正常文件名（如 SHA256SUMS）也照用
        if re.fullmatch(r"[\w\-.]+", base) and len(base) > 3:
            return base
    return None


def _measure_mirror(u: str, proxy=None) -> dict:
    """单源测速：探测元信息 + 拉 256KB 量吞吐。"""
    t0 = time.time()
    info = probe(u, proxy=proxy)
    if not info["size"]:
        return {"url": u, "info": info, "speed": 0.0, "failed": True}
    speed = 0.0
    try:
        with _request(u, "GET", {"Range": "bytes=0-262143"},
                      timeout=12, proxy=proxy) as r:
            got = len(r.read())
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
                 chunk_mb=None, slow_kb=15, slow_sec=12, retries=6, timeout=30,
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
        self._floor_kb = self.slow_kb  # 动态慢速下限，由 reporter 抬升
        self._no_range = False         # 有源声称支持分段却回 200

    # ---------- 公共 ----------
    def cancel(self):
        self._cancel.set()
        self._stop.set()

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
        ranked = rank_mirrors(self.urls, log=lambda m: self.log(m),
                              proxy=self.proxy)
        ok = [r for r in ranked if not r.get("failed")]
        if not ok:
            # 汇总所有源的真实原因，给出可操作的提示
            reasons = []
            for r in ranked:
                e = r["info"].get("error")
                if e and e not in reasons:
                    reasons.append(e)
            detail = "；".join(reasons) if reasons else "未能获取文件大小"
            raise DownloadError(f"所有下载源都不可用\n  原因：{detail}\n  建议：检查链接是否有效、是否需要登录，或换一个下载源")

        best = ok[0]
        self.mirrors = [r["info"]["url"] for r in ok]
        self.mirror_speeds = [r["speed"] for r in ok]
        self.etag = best["info"].get("etag")
        self.size = best["info"]["size"] or 0
        self._total = self.size

        name = best["info"]["name"] or _fallback_name(best["info"]["url"])
        out = self.out_path or name
        if os.path.isdir(out) or not os.path.splitext(out)[1]:
            os.makedirs(out, exist_ok=True)
            out = os.path.join(out, name)
        self.out_path = out
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)

        ranges = best["info"]["ranges"]
        self.log(f"文件大小 {human(self.size)}，分段下载：{'支持' if ranges else '不支持（退化为单线程）'}")

        if ranges and self.size > MIN_CHUNK * 2:
            try:
                self._download_chunked()
            except DownloadError:
                # 探测说支持分段，实际所有源都忽略 Range：退化单线程，别留坏文件
                if not self._no_range or self._cancel.is_set():
                    raise
                self.log("所有源都忽略了 Range 请求，退化单线程重下", "warn")
                shutil.rmtree(self.out_path + ".parts", ignore_errors=True)
                self._errors.clear()
                with self._lock:
                    self._done = 0
                self._no_range = False
                self._download_single(self.mirrors[0])
        else:
            self._download_single(best["info"]["url"])

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
        with self._lock:
            self._done = have
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
                        self._done -= have
                    have, mode = 0, "wb"
                with open(tmp, mode) as f:
                    t_last, n_last = time.time(), self._done
                    while True:
                        if self._cancel.is_set():
                            return
                        buf = r.read(BLOCK)
                        if not buf:
                            break
                        f.write(buf)
                        if self._limiter:
                            self._limiter.acquire(len(buf))
                        with self._lock:
                            self._done += len(buf)
                        now = time.time()
                        if now - t_last >= 0.5:
                            sp = (self._done - n_last) / (now - t_last)
                            self._emit("downloading", sp)
                            t_last, n_last = now, self._done
        except DownloadError:
            raise
        except Exception as e:
            raise DownloadError(f"下载失败：{e}")
        if os.path.exists(self.out_path):
            os.remove(self.out_path)
        os.replace(tmp, self.out_path)

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

        # 统计已有进度
        for i, (s, e) in enumerate(chunks):
            p = os.path.join(parts_dir, f"part{i:04d}")
            if os.path.exists(p):
                self._done += min(os.path.getsize(p), e - s + 1)

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
                # 开了全局限速时不判定慢链，否则正常分片会被限速本身误杀。
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
            while not self._cancel.is_set():
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

        if self._errors and not self._cancel.is_set():
            raise DownloadError(f"{len(self._errors)} 个分片失败，已保留进度可重试")

        self.log("合并分片…")
        # 预分配输出再按偏移写入：写一片删一片，峰值磁盘 ≈ 总量 + 一片
        mode = "r+b" if os.path.exists(self.out_path) else "w+b"
        with open(self.out_path, mode) as out:
            out.truncate(self.size)
            for i, (start, end) in enumerate(chunks):
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
        shutil.rmtree(parts_dir, ignore_errors=True)
        self.log(f"耗时 {time.time()-t0:.1f}s")

    def _worker(self, idx, start, end, parts_dir, mirror_idx=0):  # @contract CORE-011
        path = os.path.join(parts_dir, f"part{idx:04d}")
        want = end - start + 1
        for attempt in range(self.retries + 1):
            if self._cancel.is_set():
                return
            have = os.path.getsize(path) if os.path.exists(path) else 0
            if have >= want:
                return
            url = self.mirrors[(mirror_idx + attempt) % len(self.mirrors)]
            headers = {"Range": f"bytes={start + have}-{end}"}
            try:
                with _request(url, "GET", headers, timeout=self.timeout,
                              proxy=self.proxy) as r:
                    if r.status not in (200, 206):
                        raise DownloadError(f"HTTP {r.status}")
                    if r.status == 200 and (have > 0 or want != self.size):
                        # 声称支持分段却回了整文件：继续 append 会写出超长分片
                        self._no_range = True
                        raise DownloadError("服务器忽略了 Range 请求")
                    with open(path, "ab") as f:
                        got, t0 = 0, time.time()
                        while True:
                            if self._cancel.is_set():
                                return
                            buf = r.read(BLOCK)
                            if not buf:
                                break
                            f.write(buf)
                            got += len(buf)
                            if self._limiter:
                                self._limiter.acquire(len(buf))
                            with self._lock:
                                self._done += len(buf)
                            el = time.time() - t0
                            if (self.slow_kb and not self._limiter and el > self.slow_sec
                                    and got / el < self._floor_kb * 1024):
                                raise DownloadError("速度过慢，切换下载源")
                    if os.path.getsize(path) >= want:
                        return
            except Exception as e:
                self.log(f"  分片{idx} 第{attempt+1}次失败（{e}），换源重试", "warn")
                # 指数退避 + 抖动：避免多分片同时重连打爆服务端
                time.sleep(_backoff(attempt))
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
            for b in iter(lambda: f.read(4 * 1024 * 1024), b""):
                h.update(b)
        got = h.hexdigest()
        if got != want:
            bad = self._quarantine("哈希不符")
            raise DownloadError(
                f"{algo.upper()} 校验失败\n  期望 {want}\n  实际 {got}\n"
                f"  已隔离到：{bad}")
        self.log(f"{algo.upper()} 校验通过", "ok")


# ---------------- CLI ----------------
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="多线程分段下载器")
    ap.add_argument("url", help="下载链接（可多次传入作为镜像）")
    ap.add_argument("-o", "--out", help="保存目录或完整文件路径")
    ap.add_argument("-t", "--threads", type=int, default=16, help="线程数（默认 16）")
    ap.add_argument("--sha256", help="期望的哈希（sha256/sha1/md5 自动识别）")
    ap.add_argument("--mirror", action="append", default=[], help="额外镜像前缀或完整地址")
    ap.add_argument("--chunk", type=int, default=None, help="每片大小 MB（默认自动均分）")
    ap.add_argument("--slow", type=int, default=15, help="慢速阈值 KB/s，0 关闭（默认 15）")
    ap.add_argument("--slow-sec", type=int, default=12, help="慢速持续秒数（默认 12）")
    ap.add_argument("--retries", type=int, default=6, help="单片重试次数（默认 6）")
    ap.add_argument("--timeout", type=int, default=30, help="连接超时秒数（默认 30）")
    a = ap.parse_args(argv)

    urls = [a.url]
    for m in a.mirror:
        urls.append(m + a.url if m.endswith("/") and a.url.startswith("http") else m)
    urls = build_mirror_urls(a.url) + [u for u in urls[1:] if u not in build_mirror_urls(a.url)]

    last = [0.0]

    def prog(d):
        now = time.time()
        if now - last[0] < 0.5 and d["phase"] == "downloading":
            return
        last[0] = now
        if d["phase"] == "downloading":
            eta = ""
            if d["speed"] > 0 and d["total"]:
                s = int((d["total"] - d["done"]) / d["speed"])
                eta = f"  剩余 {s//60:02d}:{s%60:02d}"
            print(f"\r  {d['percent']:5.1f}%  {human(d['done'])}/{human(d['total'])}  "
                  f"{human(d['speed'])}/s{eta}   ", end="", flush=True)

    t = DownloadTask(urls, a.out, a.threads, a.sha256,
                     log=lambda m, lv="info": print(f"[{lv}] {m}"), progress=prog,
                     chunk_mb=a.chunk, slow_kb=a.slow, slow_sec=a.slow_sec,
                     retries=a.retries, timeout=a.timeout)
    try:
        p = t.run()
        print(f"\n已保存：{p}")
        return 0
    except DownloadError as e:
        print(f"\n失败：{e}")
        return 1
    except KeyboardInterrupt:
        t.cancel()
        print("\n已中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
