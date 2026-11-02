#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""taskqueue.py —— 多任务调度（纯标准库）

引擎管「一个文件怎么下完」，这里管「谁先下、同时下几个」。
不碰网络、不碰界面，只调度 DownloadTask 并转出事件。

分层约定：taskqueue 依赖 downloader，不得反向依赖；
界面层同时依赖 downloader（人类可读格式化）与 taskqueue（调度）。

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""

from __future__ import annotations

import threading
from collections import deque

from downloader import DownloadError, DownloadTask


class DownloadQueue:  # @contract CORE-016
    """任务队列：限并发、排队、单条取消。

    分工：DownloadTask 只管一个文件怎么下完，Queue 管谁先下、同时下几个。
    事件统一走 on_event(kind, tid, **kw)，kind ∈ {state, progress, log}，
    由工作线程抛出——调用方（尤其 GUI）必须自己转到线程安全的地方。
    """

    def __init__(self, concurrent=2, on_event=None):
        self.concurrent = max(1, int(concurrent))
        self._event = on_event or (lambda kind, tid, **kw: None)
        self._lock = threading.Lock()
        self._tasks = {}
        self._state = {}
        self._pending = deque()
        self._running = {}
        self._seq = 0

    # ---------- 对外 ----------
    def add(self, urls, out_path=None, **kw):
        box = {"tid": 0}

        def log(msg, level="info"):
            self._event("log", box["tid"], msg=msg, level=level)

        def progress(d):
            self._event("progress", box["tid"], data=d)

        # 先构造再登记。反过来的话，别的任务结束触发 _pump() 会在这个 tid
        # 还没进 _tasks 时把它取走执行，_run_one 直接 KeyError，并发槽永久泄漏（BUG-16）
        task = DownloadTask(urls, out_path, log=log, progress=progress, **kw)
        with self._lock:
            self._seq += 1
            tid = box["tid"] = self._seq
            self._tasks[tid] = task
            self._state[tid] = "queued"
            self._pending.append(tid)
        self._event("state", tid, state="queued")
        self._pump()
        return tid

    def cancel(self, tid):
        with self._lock:
            state = self._state.get(tid)
            task = self._tasks.get(tid)
            if state == "queued":
                self._state[tid] = "cancelled"
        if state == "queued":
            self._event("state", tid, state="cancelled")
            return True
        if task is None or state != "running":
            return False
        task.cancel()
        return True

    def cancel_all(self):
        with self._lock:
            ids = list(self._state)
        for tid in ids:
            self.cancel(tid)

    def stats(self):
        with self._lock:
            states = list(self._state.values())
        return {"total": len(states), "queued": states.count("queued"),
                "running": states.count("running"), "done": states.count("done"),
                "failed": states.count("failed"),
                "cancelled": states.count("cancelled")}

    def state_of(self, tid):
        with self._lock:
            return self._state.get(tid)

    def forget(self, tid):
        """把已结束的任务从统计里摘掉（GUI 删行时调用）。

        只允许终态：排队中/运行中的任务必须走 cancel，不能被静默抹掉，
        否则 _running 里的槽位会漏。
        """
        with self._lock:
            if self._state.get(tid) not in ("done", "failed", "cancelled"):
                return False
            self._state.pop(tid, None)
            self._tasks.pop(tid, None)
            self._running.pop(tid, None)
            return True

    # ---------- 内部 ----------
    def _pump(self):
        with self._lock:
            while self._pending and len(self._running) < self.concurrent:
                tid = self._pending.popleft()
                if self._state.get(tid) != "queued":
                    continue
                self._state[tid] = "running"
                self._running[tid] = True
                threading.Thread(target=self._run_one, args=(tid,),
                                 daemon=True).start()

    def _run_one(self, tid):
        task = self._tasks.get(tid)
        if task is None:
            # 登记丢失属于内部错误；但不能让线程带着并发槽一起死
            with self._lock:
                self._running.pop(tid, None)
                self._state[tid] = "failed"
            self._event("state", tid, state="failed", message="任务登记丢失")
            self._pump()
            return
        self._event("state", tid, state="running")
        try:
            path = task.run()
            with self._lock:
                self._state[tid] = "done"
            self._event("state", tid, state="done", path=path)
        except DownloadError as e:
            new = "cancelled" if task.cancelled else "failed"
            with self._lock:
                self._state[tid] = new
            self._event("state", tid, state=new, message=str(e))
        except BaseException as e:  # noqa: BLE001
            # 含 KeyboardInterrupt / SystemExit：必须落终态并归还并发槽，
            # 否则任务永远停在 running，队列槽位也被占住
            with self._lock:
                self._state[tid] = "failed"
            self._event("state", tid, state="failed",
                        message=f"{type(e).__name__}: {e}")
        finally:
            with self._lock:
                self._running.pop(tid, None)
                self._tasks.pop(tid, None)   # 终态后释放，长会话不涨内存
            self._pump()
