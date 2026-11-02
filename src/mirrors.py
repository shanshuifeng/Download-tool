#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mirrors.py —— GitHub 加速源策略（纯标准库）

把「哪些链接值得套加速源、套哪几个」从下载引擎里剥出来：这一层只做 URL 判定
与候选构造，不涉及任何网络行为，引擎与各入口共用同一份策略。

分层约定：downloader 依赖 mirrors，mirrors 不得反向依赖。

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""

from __future__ import annotations

import urllib.parse

# 按实测速度排序的可用加速源
GITHUB_MIRRORS = [
    "https://gh-proxy.com/",
    "https://ghfast.top/",
    "https://ghproxy.net/",
]


def is_github_release(url: str) -> bool:  # @contract CORE-007
    """是否为 GitHub 发布页或 raw 地址。

    按 URL 解析判定主机名，不做子串匹配——否则
    `https://example.com/?ref=github.com` 这类地址会被误判并套上加速源前缀。
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host not in ("github.com", "www.github.com"):
        return False
    return "/releases/download/" in parsed.path or "/raw/" in parsed.path


def build_mirror_urls(url: str) -> list[str]:
    """给 GitHub 链接补上加速镜像候选；普通链接原样返回。已在镜像内的不再套娃。"""
    urls = [url]
    if is_github_release(url) and not any(m in url for m in GITHUB_MIRRORS):
        for m in GITHUB_MIRRORS:
            urls.append(m + url)
    return urls


def expand_mirror_urls(urls: list[str]) -> list[str]:
    """对入口给出的全部 URL 补上内置加速源，并按首次出现顺序去重。

    界面、命令行与源码入口都必须经过这里：加速源功能此前只在遗留的
    `downloader.main()` 中生效，用户实际使用的两个入口并未接入（BUG-19）。
    """
    out: list[str] = []
    for u in urls:
        for cand in build_mirror_urls(u):
            if cand not in out:
                out.append(cand)
    return out
