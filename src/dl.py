#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dl.py —— 命令行 / 自动化入口（供脚本与 AI Agent 调用）

打包后与界面共用同一个 exe：`下载工具.exe` 带上参数就走本模块，没参数开界面。
接口名称仍是 `dl`，`--schema` 的输出格式不变。

设计目标：一次调用、结构化输出、可预测退出码，不需要解析人类可读文本。

用法示例：
    下载工具.exe "https://example.com/a.zip" -o "D:\\dl"
    下载工具.exe "https://..." -o "D:\\dl" --json
    下载工具.exe --job job.json --json
    下载工具.exe --schema

退出码：
    0  成功
    1  下载或校验失败
    2  参数错误
    3  所有镜像不可用
    130 被中断

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""

import argparse
import json
import os
import sys
import time

from downloader import EXIT_FAIL, EXIT_NO_MIRROR, DownloadError, DownloadTask, human

EXIT_OK = 0  # @contract CLI-002
EXIT_ARGS = 2
EXIT_NOMIRROR = EXIT_NO_MIRROR
EXIT_CANCEL = 130

# progress 节流阈值（CLI-012）。契约由校验器锁住，改这里就要改契约。
PROGRESS_INTERVAL_SEC = 1.5     # 两次输出之间的最小间隔
PROGRESS_PERCENT_DELTA = 1.0    # 相对上次输出的百分比变化阈值

SCHEMA = {  # @contract CLI-005
    "name": "dl",
    "version": 2,   # @contract CLI-011  接口变了就递增，校验器强制
    "usage": "dl <url...> -o <dir|file> [options] | dl --job <file> [--json]",
    "args": {
        "url": "下载链接，可传多个（视为同一文件的镜像）",
        "-o/--out": "保存目录或完整文件路径（必填，除非 job 文件里给了）",
        "-t/--threads": "并发分片数，1-64",
        "--sha256": "期望哈希，sha256/sha1/md5 自动识别",
        "--chunk": "每片大小 MB，0=自动",
        "--slow": "慢速阈值 KB/s，0=关闭",
        "--slow-sec": "慢速持续秒数",
        "--retries": "单片重试次数",
        "--timeout": "连接超时秒数",
        "--proxy": "HTTP/HTTPS 代理，direct=强制直连，省略则读环境变量",
        "--max-speed": "每任务限速 KB/s，0=不限（并发多任务时合计速率高于设定值）",
        "--mirror": "额外镜像前缀，可重复",
        "--hash": "下载后计算并输出文件 sha256",
        "--json": "输出 JSON Lines 事件流（机器可读）",
        "--quiet": "不输出进度，只在结束时给结果",
        "--job": "从 JSON 文件读取任务参数",
        "--schema": "打印本接口的机器可读描述后退出",
    },
    "defaults": {
        "threads": 16,
        "chunk": 0,
        "slow": 15,
        "slow_sec": 12,
        "retries": 6,
        "timeout": 30,
        "max_speed": 0,
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

# CLI 的业务默认值。argparse 一律用 None 作哨兵（BUG-29）：
# 只有「用户没传」才是 None，显式传了默认值（--threads 16）也能与默认值区分开。
# 默认值本身写在 SCHEMA 里，schema 是给消费方看的机器可读描述，不能丢。
DEFAULTS = dict(SCHEMA["defaults"])


def _utf8_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _num(j, *keys):
    """取第一个非空数值字段；都没有则返回 None（表示「job 文件没写」）。"""
    for k in keys:
        v = j.get(k)
        if v is not None:
            return int(v)
    return None


def _load_job(path):
    """读 job 文件。没写的字段留 None，由默认值兜底（BUG-29）。"""
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    urls = j.get("urls") or ([j["url"]] if j.get("url") else [])
    return {
        "urls": urls,
        "out": j.get("out") or j.get("output"),
        "threads": _num(j, "threads"),
        "sha256": j.get("sha256"),
        "chunk": _num(j, "chunk_mb", "chunk"),
        "slow": _num(j, "slow_kb", "slow"),
        "slow_sec": _num(j, "slow_sec"),
        "retries": _num(j, "retries"),
        "timeout": _num(j, "timeout"),
        "proxy": j.get("proxy"),
        "max_speed": _num(j, "max_speed_kb", "max_speed"),
        "mirrors": j.get("mirrors") or [],
    }


def _pick(cli_value, job_value, key):  # @contract CLI-001a
    """命令行优先于 job 文件；两边都没给才用默认值（BUG-29）。

    哨兵是 None：命令行显式传了默认值（--threads 16）时 cli_value 不是 None，
    不会被 job 文件里的同名字段顶掉。
    """
    if cli_value is not None:
        return cli_value
    if job_value is not None:
        return job_value
    return DEFAULTS[key]


def build_parser():  # @contract CLI-001
    p = argparse.ArgumentParser(
        prog="dl", add_help=True,
        description="多线程分段下载器（命令行/自动化接口）")
    p.add_argument("url", nargs="*", help="下载链接，可多个（同一文件的镜像）")
    p.add_argument("-o", "--out", help="保存目录或完整文件路径")
    # 默认值一律 None 作哨兵：未指定与「显式指定为默认值」必须能区分（BUG-29）
    p.add_argument("-t", "--threads", type=int, default=None)
    p.add_argument("--sha256", default=None)
    p.add_argument("--chunk", type=int, default=None, help="每片 MB，0=自动")
    p.add_argument("--slow", type=int, default=None, help="慢速阈值 KB/s，0=关闭")
    p.add_argument("--slow-sec", type=int, default=None)
    p.add_argument("--retries", type=int, default=None)
    p.add_argument("--timeout", type=int, default=None)
    p.add_argument("--proxy", default=None, help="HTTP/HTTPS 代理，direct=直连")
    p.add_argument("--max-speed", type=int, default=None,
                   help="每任务限速 KB/s，0=不限（并发多任务时合计速率高于设定值）")
    p.add_argument("--mirror", action="append", default=[])
    p.add_argument("--hash", action="store_true", help="下载后计算文件 sha256")
    p.add_argument("--json", action="store_true", help="JSON Lines 事件流")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--job", help="从 JSON 文件读取参数")
    p.add_argument("--schema", action="store_true", help="打印接口描述")
    return p


def _throttle_ok(now, last_t, last_pct, pct) -> bool:  # @contract CLI-012
    """节流判据：间隔够长 **或** 百分比变化够大就输出（OR，不是 AND）。

    抽成模块级函数是为了能单测；阈值提为常量是为了让契约能锁住。
    """
    return (now - last_t >= PROGRESS_INTERVAL_SEC
            or abs(pct - last_pct) >= PROGRESS_PERCENT_DELTA)


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
        threads = _pick(args.threads, j["threads"], "threads")
        sha = args.sha256 or j["sha256"]
        chunk = _pick(args.chunk, j["chunk"], "chunk")
        slow = _pick(args.slow, j["slow"], "slow")
        slow_sec = _pick(args.slow_sec, j["slow_sec"], "slow_sec")
        retries = _pick(args.retries, j["retries"], "retries")
        timeout = _pick(args.timeout, j["timeout"], "timeout")
        proxy = args.proxy or j["proxy"]
        max_speed = _pick(args.max_speed, j["max_speed"], "max_speed")
        mirrors = args.mirror + list(j["mirrors"])
    else:
        urls = args.url
        out = args.out
        threads = _pick(args.threads, None, "threads")
        sha = args.sha256
        chunk = _pick(args.chunk, None, "chunk")
        slow = _pick(args.slow, None, "slow")
        slow_sec = _pick(args.slow_sec, None, "slow_sec")
        retries = _pick(args.retries, None, "retries")
        timeout = _pick(args.timeout, None, "timeout")
        proxy = args.proxy
        max_speed = _pick(args.max_speed, None, "max_speed")
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
            if not _throttle_ok(now, last[0], state["pct"], pct):
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
        # 退出码由异常自带，不再匹配中文文案（CLI-002）
        code = getattr(e, "code", EXIT_FAIL)
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
    if expected and task.hash_algo == "sha256" and task.actual_hash:
        # _verify 已经把整个文件读过一遍，别再读第二遍（BUG-09）
        actual = task.actual_hash
    elif args.hash or expected:
        # 期望值是 md5/sha1 时 done.sha256 仍要填 sha256，只能另算一次
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(4 * 1024 * 1024), b""):
                h.update(b)
        actual = h.hexdigest()
    emit({"event": "done", "path": path, "size": size,
          "sha256": actual,
          "sha256_expected": expected,
          # 能走到这里说明 _verify 已经比对通过；不能再拿 sha256 值和 md5 期望值比
          "verified": (True if expected else None),
          "elapsed": round(elapsed, 1),
          "avg_speed": round(size / elapsed if elapsed else 0)}, as_json)
    if not quiet:
        print(f"\n已保存：{path}")
    elif not as_json:
        print(path)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
