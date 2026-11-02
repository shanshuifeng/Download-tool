#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""naming.py —— 文件名规整（纯标准库）

把「服务器给的名字怎么变成能安全落盘的名字」从引擎里剥出来：
纯函数、无副作用、不碰网络也不碰磁盘。

三件事：
  1. 挡目录穿越（只取最后一段，../ 之类一律丢掉）
  2. 替换 Windows 非法字符、避开 CON/PRN 等保留设备名
  3. 截断过长名字时保住扩展名（.zip 之类，截掉就认不出文件类型）

分层约定：downloader 依赖 naming，naming 不得反向依赖。

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""

from __future__ import annotations

import hashlib
import os
import re
import urllib.parse

# 落盘文件名长度上限：超过 120 字符在深层目录下容易撞上 MAX_PATH
MAX_NAME = 120

_WIN_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WIN_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{p}{i}" for p in ("com", "lpt") for i in range(1, 10)}


def safe_name(name: str) -> str | None:
    """把服务器给的文件名变成能安全落盘的名字。

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
    if len(base) > MAX_NAME:
        # 截断时保留扩展名：直接截会把 .zip 之类的后缀切掉，文件类型识别随之失效
        stem, ext = os.path.splitext(base)
        ext = ext[:20]
        base = stem[:MAX_NAME - len(ext)] + ext
    return base[:MAX_NAME]


def fallback_name(url: str) -> str:
    """服务器没给文件名时，用 URL 派生稳定名，避免多个任务都叫 download.bin。"""
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"download_{h}.bin"


def filename_from(headers, url) -> str | None:
    """从响应头与 URL 里取文件名；取不到返回 None。"""
    cd = headers.get("Content-Disposition") or ""
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", cd, re.I)
    if m:
        got = safe_name(urllib.parse.unquote(m.group(1).strip()))
        if got:
            return got
    path = urllib.parse.urlparse(url).path
    base = safe_name(urllib.parse.unquote(os.path.basename(path)))
    if base:
        if "." in base:
            return base
        # 无扩展名但看起来像正常文件名（如 SHA256SUMS）也照用
        if re.fullmatch(r"[\w\-.]+", base) and len(base) > 3:
            return base
    return None
