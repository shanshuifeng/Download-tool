# CONTRACT · 下载引擎

模块 `downloader.py` ｜ 契约版本 v1.0 ｜ 消费方：`dl.py`、`gui.pyw`、未来的队列层

## 0. 边界

- 引擎**只负责**：探测、分片、重试、合并、校验、落盘
- 引擎**不负责**：界面、配置持久化、任务排队、剪贴板、通知
- 引擎**禁止** `import tkinter`，禁止引入任何第三方库

## 1. 公开符号（CORE-001）

只有下列符号允许被外部引用。其余以下划线开头的一律视为私有，改动不通知。

```contract
{
  "checks": [
    {"type": "public_symbols", "module": "downloader",
     "names": ["DownloadError", "DownloadTask", "probe", "rank_mirrors",
               "build_mirror_urls", "is_github_release", "human", "main"]},
    {"type": "public_symbols", "module": "taskqueue",
     "names": ["DownloadQueue"]}
  ]
}
```

## 2. `DownloadTask` 构造参数（CORE-002）

```contract
{
  "checks": [
    {"type": "signature", "module": "downloader", "target": "DownloadTask",
     "params": {
       "urls": "<required>",
       "out_path": "None",
       "threads": "16",
       "sha256": "None",
       "log": "None",
       "progress": "None",
       "verify_hash": "None",
       "chunk_mb": "None",
       "slow_kb": "15",
       "slow_sec": "12",
       "retries": "6",
       "timeout": "30",
       "proxy": "None",
       "max_speed_kb": "0"
     }}
  ]
}
```

| 参数 | 取值域 | 说明 |
|---|---|---|
| `urls` | 非空 list[str] | 同一文件的多个镜像，顺序即优先级兜底 |
| `out_path` | None / 目录 / 完整路径 | 目录则沿用服务器文件名；无扩展名按目录处理 |
| `threads` | 1–64，越界自动夹紧 | `@contract CORE-004` |
| `chunk_mb` | None/0=自动均分；否则 1–32 | 越界夹到 `[MIN_CHUNK, MAX_CHUNK]` |
| `slow_kb` | 0–∞，0=关闭慢速断链 | 单位 KB/s |
| `slow_sec` | ≥3 | 低于阈值持续多少秒判定慢链 |
| `retries` | 0–20 | 单分片重试次数 |
| `timeout` | 5–300 | 连接与读超时（秒） |
| `proxy` | None / `"direct"` / 代理地址 | None=跟随 `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`；`direct`=强制直连；其他=http 与 https 共用 |
| `max_speed_kb` | 0–∞，0=不限 | 全局令牌桶限速，跨线程共享。**开启后自动关闭慢链判定**，否则限速本身会被误判成慢链 |

**新增参数规则**：只能追加在末尾且必须有默认值。已发布参数不得改名、不得改默认值。

## 3. 常量（CORE-003）

这些值参与行为判定，改动等于改契约。

```contract
{
  "checks": [
    {"type": "const", "module": "downloader",
     "values": {"BLOCK": 262144, "MIN_CHUNK": 1048576, "MAX_CHUNK": 33554432,
                "SLOW_BYTES": 15360, "SLOW_WINDOW": 12, "MAX_RETRY": 6}}
  ]
}
```

## 4. 生命周期与返回值（CORE-003b）

```
t = DownloadTask(...)        # 纯构造，不做 IO、不起线程
path = t.run()               # 阻塞当前线程直到完成/失败/取消
t.cancel()                   # 可从任意线程调用，幂等
```

| 结果 | 表现 |
|---|---|
| 成功 | `run()` 返回最终绝对路径；文件已校验通过 |
| 失败 | 抛 `DownloadError`，消息为面向用户的中文原因 |
| 取消 | 抛 `DownloadError("已取消…")`；已下载分片保留，下次可续传 |
| 二次 `run()` | 同一 `out_path` 再次调用应接着下，不重下已完成分片 |

**副作用清单**（外部可依赖的文件行为）：

- 产物：`out_path`
- 中间态：`<out_path>.parts/`（分片目录，成功后删除）、`<out_path>.part`（单线程中间文件）
- 校验失败：改名 `<out_path>.corrupt`，不删除原内容
- 不产生其他任何文件，不写注册表，不碰 `%TEMP%`

## 5. 线程模型（CORE-005）

| 事实 | 约束 |
|---|---|
| `run()` 在调用线程同步执行 | 调用方自己有责任放进工作线程，UI 尤其如此 |
| 内部起 `n` 个分片线程 + 1 个进度线程，全部 daemon | 主线程退出即结束，不做 join 阻塞进程 |
| **`log` / `progress` 回调在引擎的工作线程里执行** | 回调方必须自己转成线程安全的形式交给 UI，不得直接操作 Tk |
| 共享可变状态只有 `_done` / `_errors`，均过 `_lock` | 新增共享状态必须同样加锁 |

## 6. 回调契约（CORE-005b）

```python
log(msg: str, level: str = "info")   # level ∈ {info, warn, error, ok}
progress(d: dict)                    # d 的键固定为下表
```

| progress 键 | 类型 | 出现时机 |
|---|---|---|
| `phase` | `"downloading"` \| `"verifying"` \| `"done"` | 始终 |
| `done` / `total` | int | 始终 |
| `percent` | float 0–100 | 始终（total=0 时为 0） |
| `speed` | float B/s | 仅 downloading 有意义 |

**兼容规则**：允许新增键，禁止删键或改键名。回调方必须容忍未知键。

## 7. `probe()` 返回结构（CORE-006）

```python
{"url": str, "size": int|None, "ranges": bool, "name": str|None,
 "etag": str|None, "error": str|None}
```

- `size` 为 None 时 `error` 必须有值，且必须是可读中文
- 探测顺序：先 `HEAD`，拿不到 size 或缺 `Accept-Ranges` 时退化为 `Range: bytes=0-0`
- 不得因探测失败抛异常，一律通过 `error` 字段返回
- `etag` 取 `ETag`，缺失时退回 `Last-Modified`，仅用于续传判定（REQ-007）

## 8. 错误翻译表（CORE-006b）

`_probe_error_hint` 必须覆盖下列 HTTP 状态码，每条给出可操作建议而非复述状态码。

```contract
{
  "checks": [
    {"type": "error_table", "module": "downloader", "func": "_probe_error_hint",
     "codes": [400, 401, 403, 404, 405, 410, 416, 429, 500, 502, 503, 504]}
  ]
}
```

## 9. 镜像与分片调度（CORE-007 / CORE-008 / CORE-018）

| 条目 | 契约 |
|---|---|
| `build_mirror_urls` | 仅对 `github.com` + `/releases/download/` 或 `/raw/` 追加内置镜像；已在镜像内的不再套娃 |
| `rank_mirrors` | **并发**探测（每源一线程），全部返回后按原始顺序补日志，再按 `(failed, -speed)` 升序排序。排序语义是 `run()` 取 `ok[0]` 的前提 |
| `_measure_mirror` | 单源测速：`probe` + 拉 256KB 量吞吐；失败返回 `failed=True, speed=0` |
| `_distribute(weights, n)` | 最大余数法分配配额，轮转交错输出；返回长度恒等于 `n`。等权重时退化为轮转 |
| 分片→镜像 | `assign = _distribute(mirror_speeds, len(chunks))`，worker 取 `mirrors[(assign[i] + attempt) % n]`，重试时轮换 |
| 分片数 | `n_chunks = ceil(size / chunk)`，**与线程数无关**；`workers = min(threads, n_chunks)` |
| 线程池（CORE-018） | 固定 `workers` 个线程从 `queue.Queue` 领分片，单线程可连续处理多片。禁止「一片一线程」的写法——分片数可以远大于线程数 |

> 历史坑：旧实现把 `n` 同时当作线程数和分片数，指定 `chunk_mb` 且 `ceil(size/chunk) > threads` 时**尾部数据整段丢失**，只靠最后的大小校验兜住。修法是分离两个概念并改为队列取片（REQ-016）。

## 10. 已落地的关键行为（批次 1）

| 编号 | 行为 | 判据 |
|---|---|---|
| CORE-009 | 动态慢速下限 | reporter 每 0.5s 更新：全局速度 `g`（KB/s）满足 `g >= slow_kb*4` 时，`_floor_kb = max(slow_kb, g*0.2)`。未达 4 倍门限不抬高，避免低速链路上误杀分片。`slow_kb=0` 时整条逻辑关闭 |
| CORE-011 | 分段路径的 200 保护 | 只有「该分片覆盖整个文件且 `have==0`」才接受 200；否则置 `_no_range=True` 并抛错换源。`_download_chunked` 失败后若 `_no_range` 且未取消，清空 `.parts`、归零进度、退化 `_download_single` |
| CORE-012 | 单线程路径的 200 保护 | `have>0` 且返回 200 时丢弃已下部分（`mode="wb"` 覆盖写）并回退 `_done`，绝不 append |
| CORE-006b | 错误翻译表 | 12 个 HTTP 状态码全覆盖，由校验器守着，缺一个就红 |
| CORE-013 | 代理 | `_opener(proxy)` 按 key 缓存 opener。`None`→读环境变量、`direct/none/off/no`→空 ProxyHandler、其他→`{"http": p, "https": p}`。`_request`/`probe`/`rank_mirrors` 全链路透传 |
| CORE-014 | 全局限速 | `_RateLimiter`：桶容量=1 秒速率，`acquire(n)` 跨线程阻塞；worker 与单线程路径每写一块后调用 |
| CORE-015 | 哈希识别 | 按长度查表 `{32:md5, 40:sha1, 64:sha256, 128:sha512}`；长度不匹配时抛「不匹配任何支持的算法」，不伪装成校验失败 |
| CORE-016 | 任务队列（实现在 `taskqueue.py`） | `DownloadQueue(concurrent=2, on_event)`：`add()` 返回 tid、`cancel(tid)` 对排队任务直接摘除对运行任务置标志、`stats()` 返回各状态计数。事件 `(kind, tid, **kw)` 由工作线程抛出。任务进入终态后从 `_tasks` 移除，长会话不涨内存 |
| CORE-017 | SOCKS5 | `_socks5_connect()` 完成握手与 CONNECT；`_socks_opener()` 用动态子类替换 `HTTPConnection.connect`，HTTPS 再套 `_context.wrap_socket`。支持无认证与用户名密码 |
| — | 重试退避 | `min(8.0, 2**attempt) + random(0, 0.4)`，即 1/2/4/8/8 秒并带抖动 |
| — | 续传指纹 | `meta.json` 记录 `etag`；`size`、`chunks`、`etag` 三者任一不符即删除全部分片 |

**并发约定**：`_floor_kb` 由 reporter 线程写、worker 线程读，依赖 CPython 对单个属性赋值/读取的原子性。若将来改成浮点或复合结构，必须加锁——`CODE-006` 对「共享可变状态」的要求优先。

## 11. 待实现契约（占位，落地后转为正式条目）

| 编号 | 内容 | 关联 |
|---|---|---|
| CORE-010 | 动态分片调度中的「把一片再切细」——已评估后放弃：队列取片 + 4× 粒度 + 慢链换源已覆盖主要收益，动态改写分片边界会破坏 `meta.json` 的续传稳定性 | REQ-008b（不做） |
