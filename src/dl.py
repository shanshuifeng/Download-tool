#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dl.py —— 命令行 / 自动化入口（供脚本与 AI Agent 调用）

设计目标：一次调用、结构化输出、可预测退出码，不需要解析人类可读文本。

用法示例：
    dl.exe "https://example.com/a.zip" -o "D:\\dl"
    dl.exe "https://..." -o "D:\\dl" --json
    dl.exe --job job.json --json
    dl.exe --schema

退出码：
    0  成功
    1  下载或校验失败
    2  参数错误
    3  所有镜像不可用
    130 被中断
"""

import argparse
import json
import os
import sys
import time

from downloader import DownloadError, DownloadTask, human

EXIT_OK = 0  # @contract CLI-002
EXIT_FAIL = 1
EXIT_ARGS = 2
EXIT_NOMIRROR = 3
EXIT_CANCEL = 130

SCHEMA = {  # @contract CLI-005
    "name": "dl",
    "version": 1,
    "usage": "dl <url...> -o <dir|file> [options] | dl --job <file> [--json]",
    "args": {
        "url": "下载链接，可传多个（视为同一文件的镜像）",
        "-o/--out": "保存目录或完整文件路径（必填，除非 job 文件里给了）",
        "-t/--threads": "并发分片数，1-64，默认 16",
        "--sha256": "期望哈希，sha256/sha1/md5 自动识别",
        "--chunk": "每片大小 MB，0=自动",
        "--slow": "慢速阈值 KB/s，0=关闭，默认 15",
        "--slow-sec": "慢速持续秒数，默认 12",
        "--retries": "单片重试次数，默认 6",
        "--timeout": "连接超时秒数，默认 30",
        "--proxy": "HTTP/HTTPS 代理，direct=强制直连，省略则读环境变量",
        "--max-speed": "全局限速 KB/s，0=不限",
        "--mirror": "额外镜像前缀，可重复",
        "--hash": "下载后计算并输出文件 sha256",
        "--json": "输出 JSON Lines 事件流（机器可读）",
        "--quiet": "不输出进度，只在结束时给结果",
        "--job": "从 JSON 文件读取任务参数",
        "--schema": "打印本接口的机器可读描述后退出",
    },
    "events": {
        "progress": {"event": "progress", "percent": "float", "done": "int",
                     "total": "int", "speed": "float", "eta": "int|null"},
        "done": {"event": "done", "path": "str", "size": "int",
                 "sha256": "str|null", "sha256_expected": "str|null",
                 "verified": "bool|null", "elapsed": "float",
                 "avg_speed": "float"},
        "error": {"event": "error", "code": "int", "message": "str"},
    },
    "exit_codes": {"0": "ok", "1": "download/verify failed",
                   "2": "bad arguments", "3": "no mirror available",
                   "130": "interrupted"},
}


def _utf8_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _load_job(path):
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    urls = j.get("urls") or ([j["url"]] if j.get("url") else [])
    return {
        "urls": urls,
        "out": j.get("out") or j.get("output"),
        "threads": int(j.get("threads", 16)),
        "sha256": j.get("sha256"),
        "chunk": j.get("chunk_mb", j.get("chunk")),
        "slow": j.get("slow_kb", j.get("slow", 15)),
        "slow_sec": j.get("slow_sec", 12),
        "retries": j.get("retries", 6),
        "timeout": j.get("timeout", 30),
        "proxy": j.get("proxy"),
        "max_speed": int(j.get("max_speed_kb", j.get("max_speed", 0)) or 0),
        "mirrors": j.get("mirrors") or [],
    }


def build_parser():  # @contract CLI-001
    p = argparse.ArgumentParser(
        prog="dl", add_help=True,
        description="多线程分段下载器（命令行/自动化接口）")
    p.add_argument("url", nargs="*", help="下载链接，可多个（同一文件的镜像）")
    p.add_argument("-o", "--out", help="保存目录或完整文件路径")
    p.add_argument("-t", "--threads", type=int, default=16)
    p.add_argument("--sha256", default=None)
    p.add_argument("--chunk", type=int, default=0, help="每片 MB，0=自动")
    p.add_argument("--slow", type=int, default=15, help="慢速阈值 KB/s，0=关闭")
    p.add_argument("--slow-sec", type=int, default=12)
    p.add_argument("--retries", type=int, default=6)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--proxy", default=None, help="HTTP/HTTPS 代理，direct=直连")
    p.add_argument("--max-speed", type=int, default=0, help="全局限速 KB/s，0=不限")
    p.add_argument("--mirror", action="append", default=[])
    p.add_argument("--hash", action="store_true", help="下载后计算文件 sha256")
    p.add_argument("--json", action="store_true", help="JSON Lines 事件流")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--job", help="从 JSON 文件读取参数")
    p.add_argument("--schema", action="store_true", help="打印接口描述")
    return p


def emit(obj, as_json):  # @contract CLI-004
    if as_json:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main(argv=None):
    _utf8_stdout()
    args = build_parser().parse_args(argv)

    if args.schema:
        print(json.dumps(SCHEMA, ensure_ascii=False, indent=2))
        return EXIT_OK

    if args.job:
        try:
            j = _load_job(args.job)
        except Exception as e:
            print(f"[error] 读取 job 文件失败: {e}", file=sys.stderr)
            return EXIT_ARGS
        urls = j["urls"]
        out = args.out or j["out"]
        threads = args.threads if args.threads != 16 else j["threads"]
        sha = args.sha256 or j["sha256"]
        chunk = args.chunk or j["chunk"] or 0
        slow = args.slow if args.slow != 15 else j["slow"]
        slow_sec = args.slow_sec if args.slow_sec != 12 else j["slow_sec"]
        retries = args.retries if args.retries != 6 else j["retries"]
        timeout = args.timeout if args.timeout != 30 else j["timeout"]
        proxy = args.proxy or j["proxy"]
        max_speed = args.max_speed or j["max_speed"]
        mirrors = args.mirror + list(j["mirrors"])
    else:
        urls = args.url
        out = args.out
        threads, sha, chunk = args.threads, args.sha256, args.chunk
        slow, slow_sec = args.slow, args.slow_sec
        retries, timeout = args.retries, args.timeout
        proxy, max_speed = args.proxy, args.max_speed
        mirrors = args.mirror

    if not urls:
        print("[error] 缺少下载链接", file=sys.stderr)
        return EXIT_ARGS
    if not out:
        print("[error] 缺少 -o 保存位置", file=sys.stderr)
        return EXIT_ARGS

    expected = (sha or "").lower() or None

    full = []
    for u in urls:
        full.append(u)
        for m in mirrors:
            full.append(m + u if m.endswith("/") else m)

    as_json = args.json
    quiet = args.quiet or as_json
    t0 = time.time()
    last = [0.0]
    state = {"size": 0, "path": None, "pct": -1.0}

    def log(msg, level="info"):
        if not quiet:
            print(f"[{level}] {msg}", flush=True)

    def progress(d):
        now = time.time()
        state["size"] = d.get("total") or state["size"]
        if d["phase"] == "downloading":
            pct = round(d["percent"], 1)
            if now - last[0] < 1.5 and abs(pct - state["pct"]) < 1.0:
                return
            last[0] = now
            state["pct"] = pct
            eta = None
            if d["speed"] > 2048 and d["total"]:
                eta = int((d["total"] - d["done"]) / d["speed"])
            emit({"event": "progress", "percent": round(d["percent"], 1),
                  "done": d["done"], "total": d["total"],
                  "speed": round(d["speed"]), "eta": eta}, as_json)
            if not quiet:
                print(f"\r  {d['percent']:5.1f}%  {human(d['done'])}/{human(d['total'])}"
                      f"  {human(d['speed'])}/s   ", end="", flush=True)

    task = DownloadTask(
        full, out, threads, sha,
        log=log, progress=progress,
        chunk_mb=chunk or None, slow_kb=slow, slow_sec=slow_sec,
        retries=retries, timeout=timeout,
        proxy=proxy, max_speed_kb=max_speed,
    )

    try:
        path = task.run()
    except DownloadError as e:
        msg = str(e)
        code = EXIT_NOMIRROR if "不可用" in msg else EXIT_FAIL
        if not quiet:
            print()
        emit({"event": "error", "code": code, "message": msg}, as_json)
        if not as_json:
            print(f"[error] {msg}", file=sys.stderr)
        return code
    except KeyboardInterrupt:
        task.cancel()
        emit({"event": "error", "code": EXIT_CANCEL, "message": "interrupted"}, as_json)
        return EXIT_CANCEL
    except Exception as e:  # noqa: BLE001
        emit({"event": "error", "code": EXIT_FAIL,
              "message": f"{type(e).__name__}: {e}"}, as_json)
        return EXIT_FAIL

    elapsed = time.time() - t0
    size = os.path.getsize(path)
    actual = None
    if args.hash or expected:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(4 * 1024 * 1024), b""):
                h.update(b)
        actual = h.hexdigest()
    emit({"event": "done", "path": path, "size": size,
          "sha256": actual,
          "sha256_expected": expected,
          "verified": (actual == expected) if expected else None,
          "elapsed": round(elapsed, 1),
          "avg_speed": round(size / elapsed if elapsed else 0)}, as_json)
    if not quiet:
        print(f"\n已保存：{path}")
    elif not as_json:
        print(path)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
