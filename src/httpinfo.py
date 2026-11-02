#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""httpinfo.py —— HTTP 语义判定与资源探测（纯标准库）

把「响应头与状态码意味着什么」从引擎里剥出来：支不支持分段、416 与永久错误
怎么判、文件多大。纯判定 + 一个探测器，不碰磁盘、不改状态。

urllib 对 4xx/5xx 直接抛 HTTPError（响应体就是异常对象），上层拿不到 r.status。
要按状态码分流就得在传输层认得这些异常：416 说明该源不支持分段，
401/403/404 说明链接本身有问题，退避重试对它们毫无意义（BUG-42）。

分层约定：downloader 依赖 httpinfo；httpinfo 依赖 netio 与 naming，不得反向依赖。

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""

from __future__ import annotations

import re
import urllib.error

from naming import filename_from
from netio import _probe_error_hint, _request

# 4xx 里仍值得退避重试的：请求超时与限流是暂时性的
RETRYABLE_HTTP_CODES = frozenset({408, 429})


def http_code(exc: BaseException) -> int | None:
    """取 HTTP 状态码；不是 HTTP 错误返回 None。"""
    if isinstance(exc, urllib.error.HTTPError):
        return int(exc.code)
    return None


def is_permanent_http_error(exc: BaseException) -> bool:
    """4xx 且不是暂时性的即为永久错误：401/403/404 之类，重试无意义。"""
    code = http_code(exc)
    if code is None or not 400 <= code < 500:
        return False
    return code not in RETRYABLE_HTTP_CODES


def range_rejected(exc: BaseException) -> bool:
    """416：服务器按 RFC 7233 拒绝了 Range 请求，等同于「该源不支持分段」。"""
    return http_code(exc) == 416


def total_from_range_error(exc: BaseException) -> int | None:
    """从 416 的 `Content-Range: bytes */<总长>` 里取文件总长。"""
    if http_code(exc) != 416:
        return None
    headers = getattr(exc, "headers", None)
    cr = (headers.get("Content-Range") if headers else "") or ""
    m = re.search(r"/(\d+)\s*$", cr)
    return int(m.group(1)) if m else None


def _etag_of(headers) -> str | None:
    """续传指纹：优先 ETag，退回 Last-Modified。"""
    return headers.get("ETag") or headers.get("Last-Modified")


def probe(url: str, timeout=15, proxy=None):  # @contract CORE-006
    """探测：最终 URL、文件大小、是否支持 Range、建议文件名、续传指纹。

    失败时在返回值的 error 字段里带上原因，供上层给出可操作的提示。

    HEAD 声称 `Accept-Ranges: bytes` 之后还要再确认一次：有的服务器在 HEAD 里
    声称支持分段，实际对 Range 请求按 RFC 7233 回 416（BUG-42）。多这一次请求，
    换来「下载开始前就知道能不能分段」，而不是下到一半才发现分片全废。
    """
    size, ranges, final, name, etag = None, False, url, None, None
    errors = []
    head_ranges = False

    # 先试 HEAD
    try:
        with _request(url, "HEAD", timeout=timeout, proxy=proxy) as r:
            final = r.geturl()
            cl = r.headers.get("Content-Length")
            ar = (r.headers.get("Accept-Ranges") or "").lower()
            size = int(cl) if cl and cl.isdigit() else None
            ranges = ar == "bytes"
            head_ranges = ranges
            name = filename_from(r.headers, final)
            etag = _etag_of(r.headers)
    except Exception as e:
        errors.append(e)

    # 再用 1 字节 Range 做确认探测：HEAD 声称的分段能力不可全信（BUG-42）
    try:
        with _request(url, "GET", {"Range": "bytes=0-0"},
                      timeout=timeout, proxy=proxy) as r:
            final = r.geturl()
            cr = r.headers.get("Content-Range") or ""
            m = re.search(r"/(\d+)", cr)
            if m:
                # Content-Range 里的总长只在 HEAD 没给出可信大小时才覆盖：
                # HEAD 谎报过大时要靠它拦下来，不能被这次确认探测冲掉
                if size is None or not head_ranges:
                    size = int(m.group(1))
                ranges = True
            elif size is None:
                cl = r.headers.get("Content-Length")
                size = int(cl) if cl and cl.isdigit() else None
            name = filename_from(r.headers, final) or name
            etag = etag or _etag_of(r.headers)
    except Exception as e:
        errors.append(e)
        if range_rejected(e):   # @contract CORE-024
            # 416：服务器按 RFC 7233 拒绝 Range —— 该源不支持分段，只能整文件下
            ranges = False
            if size is None:
                size = total_from_range_error(e)

    err = None
    if size is None:
        # 0 字节是合法大小，不能用真值判断——GitHub 上的 .gitkeep / 空 __init__.py
        # 全是 Content-Length: 0（BUG-01）
        # 优先报 HTTP 状态类错误（信息量最大），否则报第一个
        http_errs = [e for e in errors if re.search(r"HTTP Error \d{3}", str(e))]
        pick = (http_errs or errors or [None])[0]
        err = _probe_error_hint(url, pick) if pick else "无法获取文件大小，服务器可能不支持该请求"

    return {"url": final, "size": size, "ranges": ranges, "name": name,
            "etag": etag, "error": err}
