#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diskutil.py —— 落盘前的磁盘与路径检查（纯标准库）

把「这块盘能不能装下这个文件」从下载引擎里剥出来：剩余空间、FAT32 单文件
上限、Windows MAX_PATH 长度、ENOSPC 判定。

设计原则：**预检只为提前报错，不为挡住能下的文件。** 任何探测本身失败
（UNC 路径、无权限、非 Windows）一律放行，由真正的写入去承担后果。

分层约定：downloader 依赖 diskutil，diskutil 不得反向依赖。

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""

from __future__ import annotations

import errno
import os
import shutil

# FAT32 单文件上限是 4GB-1（不是 4GB）
FAT32_MAX = 4 * 1024 ** 3 - 1

# Windows MAX_PATH 含结尾 NUL 为 260；留给 ".parts\part0000" / ".part.json" 的后缀
MAX_PATH_SAFE = 259
MAX_SUFFIX = 18

# ERROR_HANDLE_DISK_FULL / ERROR_DISK_FULL
_WIN_DISK_FULL = (39, 112)


class DiskError(Exception):
    """预检不通过。由引擎翻译成 DownloadError，对外只暴露一种异常。"""


def existing_parent(path: str) -> str:
    """目标可能还不存在：向上找到第一个真实存在的目录。"""
    cur = os.path.abspath(path)
    while cur and not os.path.isdir(cur):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return cur or os.path.abspath(os.curdir)


def fs_type(root: str) -> str | None:
    """取卷的文件系统名（NTFS / FAT32 / exFAT…）。非 Windows 或失败返回 None。"""
    if os.name != "nt":
        return None
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(64)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            root, None, 0, None, None, None, buf, len(buf))
    except Exception:  # noqa: BLE001  探测失败就该放行，不能反客为主
        return None
    return (buf.value or None) if ok else None


def free_space(path: str) -> int | None:
    try:
        return shutil.disk_usage(existing_parent(path)).free
    except OSError:
        return None


def check_target(path: str, size: int) -> str | None:
    """下载前检查路径长度、FAT32 上限与剩余空间。

    返回一条警告（空间偏紧，但还能下），或 None。不通过时抛 DiskError。
    """
    if size <= 0:
        return None

    full = os.path.abspath(path)

    if os.name == "nt" and len(full) + MAX_SUFFIX > MAX_PATH_SAFE:
        raise DiskError(
            f"保存路径过长（{len(full)} 字符，上限约 {MAX_PATH_SAFE - MAX_SUFFIX}）\n"
            f"  请换一个层级更浅的目录，或把文件名改短")

    if os.name == "nt":
        drive = os.path.splitdrive(full)[0]
        if drive:
            fs = fs_type(drive + os.sep)
            if fs and fs.upper() == "FAT32" and size > FAT32_MAX:
                raise DiskError(
                    f"目标盘是 FAT32，单文件上限 4GB，当前文件 {size / 1024 ** 3:.1f}GB\n"
                    f"  请改存到 exFAT/NTFS 盘，或换成本机目录")

    free = free_space(full)
    if free is None:
        return None   # 探测不到就不拦

    need = int(size * 1.05) + 64 * 1024 * 1024
    if free < need:
        raise DiskError(
            f"磁盘空间不足：需要约 {need / 1024 ** 3:.2f}GB，"
            f"目标盘可用 {free / 1024 ** 3:.2f}GB\n"
            f"  请清理磁盘，或换一个保存位置")
    if free < size * 2:
        # 合并阶段 .parts 与新文件并存，峰值接近 2 倍；这里只提醒，不拦
        return "磁盘余量偏紧（不足文件大小的 2 倍），合并阶段可能失败"
    return None


def is_disk_full(exc: BaseException) -> bool:
    """写盘失败是不是「没空间了」。Windows 的 winerror 也要认。"""
    if not isinstance(exc, OSError):
        return False
    if exc.errno == errno.ENOSPC:
        return True
    return getattr(exc, "winerror", None) in _WIN_DISK_FULL
