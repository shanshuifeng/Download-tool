#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resume.py —— 单线程续传指纹（纯标准库）

分片路径靠 `meta.json` 判定旧分片能不能复用；单线程路径只有一个 `.part`，
同样需要一份指纹。否则远端换成同长度内容后，续传会把新旧字节拼在一起，
产出既不是旧文件也不是新文件的产物（BUG-15）。

文件格式属于 DATA-004：`<out>.part.json`，缺失或损坏一律视为不可信，
调用方应当丢弃已有 `.part` 从头下载。

分层约定：downloader 依赖 resume，resume 不得反向依赖。

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""

from __future__ import annotations

import json
import os

VERSION = 1


def meta_path(out: str) -> str:
    return out + ".part.json"


def load(out: str) -> dict | None:
    """读指纹；文件不存在、坏 JSON、不是对象，一律当作没有。"""
    try:
        with open(meta_path(out), encoding="utf-8") as f:
            got = json.load(f)
    except Exception:  # noqa: BLE001  指纹坏了只该导致重下，不该阻断下载
        return None
    return got if isinstance(got, dict) else None


def save(out: str, *, size: int, etag: str | None, url: str) -> None:
    """先写临时文件再替换：断电时宁可没有指纹，也不要半个 JSON。"""
    path = meta_path(out)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": VERSION, "size": size,
                       "etag": etag, "url": url}, f)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def matches(meta: dict | None, size: int, etag: str | None) -> bool:
    """文件大小必须一致；双方都有 ETag 时再比 ETag。

    指纹格式版本必须一致：将来改动格式后，旧指纹不能继续被当作有效。
    服务器不给 ETag 时只能退回比大小——这是本机制的天花板，
    调用方应打一条 warn 告诉用户「同长度变更检测不到」。
    """
    if not meta or meta.get("version") != VERSION:
        return False
    if meta.get("size") != size:
        return False
    old = meta.get("etag")
    if old and etag:
        return old == etag
    return True


def clear(out: str) -> None:
    """成功落盘后清掉指纹；文件本来就不在也不算错。"""
    for path in (meta_path(out), meta_path(out) + ".tmp"):
        try:
            os.remove(path)
        except OSError:
            pass
