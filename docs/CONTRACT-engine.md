# CONTRACT · 下载引擎

模块 `downloader.py` ｜ 契约版本 v1.0 ｜ 消费方：`dl.py`、`gui.pyw`、未来的队列层

实现分布在若干模块：`downloader.py`（引擎主体）、`httpinfo.py`（HTTP 语义判定与探测）、`naming.py`（文件名规整）、`netio.py`（传输层）、`diskutil.py`（落盘预检）、`resume.py`（续传指纹）、`mirrors.py`（加速源）。`downloader` 再导出公开符号，公开面以 CORE-001 为准。

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
               "build_mirror_urls", "expand_mirror_urls", "is_github_release",
               "human", "EXIT_FAIL", "EXIT_NO_MIRROR"]},
    {"type": "public_symbols", "module": "taskqueue",
     "names": ["DownloadQueue"]}
  ]
}
```

**引擎不含命令行入口（CLI-010）**：`downloader` 只暴露引擎 API，命令行参数解析一律在 `dl.py`。引擎模块里不得出现 `argparse`。

`mirrors` 的数据表 `GITHUB_MIRRORS` **不再经引擎再导出**（BUG-41）：需要它的人直接 `import mirrors`。再导出的只有 `build_mirror_urls` / `expand_mirror_urls` / `is_github_release` 三个函数。

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
| `max_speed_kb` | 0–∞，0=不限 | 每任务令牌桶限速（同一任务内跨线程共享）。**开启后自动关闭慢链判定**，否则限速本身会被误判成慢链。并发多任务时各自独立限速，合计速率可能高于设定值 |

**新增参数规则**：只能追加在末尾且必须有默认值。已发布参数不得改名、不得改默认值。

## 3. 常量（CORE-003）

这些值参与行为判定，改动等于改契约。其中 `SLOW_BYTES` / `SLOW_WINDOW` / `MAX_RETRY` 同时是构造参数的默认值来源，改动会同时改变默认行为。

**每个常量都必须真被读取**（CODE-015）：只定义、从不读取的常量等于契约里的谎言——它宣称「参与行为判定」，实际上一行代码都没用到。校验器按 AST 判定：常量名必须在声明范围内出现一次**读取**（`ast.Name` 且 `ctx=Load`），模块级赋值本身是 `Store`，不计入。

```contract
{
  "checks": [
    {"type": "const", "module": "downloader",
     "values": {"BLOCK": 262144, "MIN_CHUNK": 1048576, "MAX_CHUNK": 33554432,
                "SLOW_BYTES": 15360, "SLOW_WINDOW": 12, "MAX_RETRY": 6}},
    {"type": "const_used", "module": "downloader",
     "constants": ["BLOCK", "MIN_CHUNK", "MAX_CHUNK",
                   "SLOW_BYTES", "SLOW_WINDOW", "MAX_RETRY"],
     "aliases": {},
     "files": ["downloader.py", "dl.py", "taskqueue.py", "gui.pyw"]}
  ]
}
```

> `files` 是读取发生过的范围，不做「所有大写常量」的自动推断——`DEFAULTS`（GUI 配置字典）、`GITHUB_MIRRORS`（数据表）本就不该有「行为判定」语义。

**匹配是第一级（精确）**：常量名本身必须作为 `ast.Name` 且处于 `Load` 语境出现。**裸文本匹配会让常量定义行自身命中，恒为「已使用」，检查等于空转**——这正是 `check_anchors` 空转过一轮的同类陷阱。定义行上的自引用（`X = X + 1`）同样不计。

`aliases` 是留给将来的第二级（构造参数别名）——本轮**留空**。它会遮蔽第一级：有人把默认值改成硬编码时，第一级正确判「未使用」，第二级却因别名仍被读取而判「已使用」，漏过。低精度规则吞掉高精度规则的判定是净负收益。

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

**`done` / `percent` 的上界**：两者按同一口径计算（见 CORE-025），因此恒有 `done ≤ total`、`percent ≤ 100`。`percent` 达到 100 的充要条件是**全部分片长度恰好等于期望长度**——此时合并必定成功。回调方不得假设 `percent` 会出现大于 100 的值，也不得把「`percent == 100`」当作「可以合并了」的信号（那是引擎内部的事）。

**兼容规则**：允许新增键，禁止删键或改键名。回调方必须容忍未知键。

## 7. `probe()` 返回结构（CORE-006）

```python
{"url": str, "size": int|None, "ranges": bool, "name": str|None,
 "etag": str|None, "error": str|None}
```

- `size` 为 None 时 `error` 必须有值，且必须是可读中文
- `size` 为 `0` 是合法值（空文件），只有 `None` 才表示探测失败；`error` 仅在 `None` 时非空
- 探测顺序：先 `HEAD`，再用 `Range: bytes=0-0` 确认
- **确认探测无条件执行**：HEAD 声称 `Accept-Ranges: bytes` 也要再确认一次。代价是每个源多一次请求（服务端通常只回 1 字节），收益是下载开始前就知道能不能分段——有的服务器 HEAD 里声称支持分段，实际对 Range 请求按 RFC 7233 回 416（BUG-42）
- 确认探测收到 **416** 时判定 `ranges=False`（该源不支持分段）；HEAD 没给出大小时，从 416 的 `Content-Range: bytes */<总长>` 取回文件总长
- 确认探测里的 `Content-Range` 总长**只在 HEAD 没给出可信大小时才覆盖 `size`**：HEAD 谎报过大时要靠它拦下来（CORE-020），不能被确认探测冲掉
- 不得因探测失败抛异常，一律通过 `error` 字段返回
- `etag` 取 `ETag`，缺失时退回 `Last-Modified`，仅用于续传判定（REQ-007）
- 实现位于 `httpinfo.py`，由 `downloader` 再导出，CORE-001 的公开面不变

## 8. 错误翻译表（CORE-006b）

`_probe_error_hint` 必须覆盖下列 HTTP 状态码，每条给出可操作建议而非复述状态码。

```contract
{
  "checks": [
    {"type": "error_table", "module": "netio", "func": "_probe_error_hint",
     "codes": [400, 401, 403, 404, 405, 410, 416, 429, 500, 502, 503, 504]}
  ]
}
```

## 9. 镜像与分片调度（CORE-007 / CORE-008 / CORE-018）

| 条目 | 契约 |
|---|---|
| `build_mirror_urls` | 仅对 `github.com` + `/releases/download/` 或 `/raw/` 追加内置镜像；已在镜像内的不再套娃。主机名按 URL 解析判定，不做子串匹配 |
| `expand_mirror_urls` | 对入口给出的全部 URL 调用 `build_mirror_urls` 并去重；`DownloadTask.run()` 必须调用它，使界面、命令行与源码入口行为一致 |
| `rank_mirrors` | **并发**探测（每源一线程），全部返回后按原始顺序补日志，再按 `(failed, -speed)` 升序排序。排序语义是 `run()` 取 `ok[0]` 的前提 |
| `_measure_mirror` | 单源测速：`probe` + 拉 256KB 量吞吐；失败返回 `failed=True, speed=0`。**计时从响应头到达后开始**：DNS 解析、TCP 连接、TLS 握手与 `probe` 本身的耗时不计入分母（它们与源快慢无关）；首字节延迟仍计入（连接建立后迟迟不吐数据的源本就该是慢源） |
| `_distribute(weights, n)` | 最大余数法分配配额，轮转交错输出；返回长度恒等于 `n`。等权重时退化为轮转 |
| 分片→镜像 | `assign = _distribute(mirror_speeds, len(chunks))`，worker 取 `mirrors[(assign[i] + attempt) % n]`，重试时轮换 |
| 分片数 | `n_chunks = ceil(size / chunk)`，**与线程数无关**；`workers = min(threads, n_chunks)` |
| 线程池（CORE-018） | 固定 `workers` 个线程从 `queue.Queue` 领分片，单线程可连续处理多片。禁止「一片一线程」的写法——分片数可以远大于线程数 |

> 历史坑：旧实现把 `n` 同时当作线程数和分片数，指定 `chunk_mb` 且 `ceil(size/chunk) > threads` 时**尾部数据整段丢失**，只靠最后的大小校验兜住。修法是分离两个概念并改为队列取片（REQ-016）。

## 10. 已落地的关键行为（批次 1）

| 编号 | 行为 | 判据 |
|---|---|---|
| CORE-009 | 动态慢速下限 | reporter 每 0.5s 更新：全局速度 `g`（KB/s）满足 `g >= slow_kb*4` 时，`_floor_kb = max(slow_kb, g*0.2)`。未达 4 倍门限不抬高，避免低速链路上误杀分片。`slow_kb=0` 时整条逻辑关闭 |
| CORE-011 | 分段路径的 200 保护 | 只有「该分片覆盖整个文件且 `have==0`」才接受 200；否则记录该镜像「忽略 Range」并抛错换源。**仅当全部镜像都被观测到忽略 Range 时**才判定整体不支持分段：清空 `.parts`、归零进度、退化 `_download_single`。部分源不支持 Range 时不得作废已下载分片。服务器用 416 拒绝 Range 时同样记入这份名单（CORE-024） |
| CORE-012 | 单线程路径的 200 保护 | `have>0` 且返回 200 时丢弃已下部分（`mode="wb"` 覆盖写）并回退 `_done`，绝不 append。续传指纹见 CORE-021 |
| CORE-006b | 错误翻译表 | 12 个 HTTP 状态码全覆盖，由校验器守着，缺一个就红 |
| CORE-013 | 代理 | `_opener(proxy)` 按 key 缓存 opener。`None`→读环境变量、`direct/none/off/no`→空 ProxyHandler、其他→`{"http": p, "https": p}`。`_request`/`probe`/`rank_mirrors` 全链路透传 |
| CORE-014 | 限速 | `_RateLimiter`：桶容量=1 秒速率，`acquire(n)` 跨线程阻塞。**`acquire(n)` 必须在 `_write` 之前调用**：先取配额再落盘，限速作用于真正写进磁盘的字节，不得先写后补。限速器为 `DownloadTask` 实例属性，作用域为**单个任务**；队列中多个任务各自独立限速，合计速率可能达到设定值的数倍 |
| CORE-015 | 哈希识别 | 按长度查表 `{32:md5, 40:sha1, 64:sha256, 128:sha512}`；长度不匹配时抛「不匹配任何支持的算法」，不伪装成校验失败 |
| CORE-016 | 任务队列（实现在 `taskqueue.py`） | `DownloadQueue(concurrent=2, on_event)`：`add()` 先构造任务、再在同一把锁里登记 `_tasks/_state/_pending`（避免 `_pump` 取走尚未登记的任务）；`cancel(tid)` 对排队任务直接摘除、对运行任务置标志；`forget(tid)` 只接受终态，移除后 `stats()` 立即减少；`_tasks` 终态释放，`_state` 保留到 `forget`。`_PATH_LOCKS` 按路径缓存、进程内不回收（已知限制，每路径约 100B） |
| CORE-017 | SOCKS5 | `_socks5_connect()` 完成握手与 CONNECT；`_socks_opener()` 用动态子类替换 `HTTPConnection.connect`，HTTPS 再套 `_context.wrap_socket`。支持无认证与用户名密码 |
| CORE-019 | 路径互斥 | `_path_lock(out)` 按规范化绝对路径取进程内锁；`run()` 非阻塞抢锁，失败即抛「同一文件已有任务在下载」。持锁范围覆盖下载 + 合并 + 校验，`finally` 释放。**已知限制**：仅进程内有效，两个 exe 同时下同一文件仍会冲突 |
| CORE-020 | 大小上限与落盘预检 | `MAX_FILE_SIZE = 200GB`。`run()` 在确定 `size` 后、建目录之前检查路径长度、FAT32 单文件上限与剩余空间，不通过直接拒绝且不创建任何文件。探测本身失败（UNC、无权限、非 Windows）一律放行——预检只为提前报错，不得挡住能下的文件 |
| CORE-021 | 单线程续传指纹 | `<out>.part.json` 记 `size/etag/url`：开下前写入（先写 `.tmp` 再 `replace`）、成功落盘后删除、取消/失败保留。续传前 `size` 必比，双方都有 ETag 时比 ETag；不符即删 `.part` 从头下。服务器无 ETag 时允许续传，但必须打 warn |
| CORE-022 | ENOSPC 快速失败 | 写入遇 `errno.ENOSPC`（或 winerror 39/112）立即中止：分片路径置 `_fatal`、停止领片并在 join 后抛出；单线程路径直接抛。不得进退避重试。合并阶段失败时删除半成品输出、保留 `.parts` |
| CORE-023 | 路径与文件系统预检 | 路径 `len(abspath) + 18 > 259` 拒绝（18 是 `.parts\part0000` 的后缀余量）；FAT32 且 `size > 4GB-1` 拒绝；可用空间 `< size*1.05 + 64MB` 拒绝，`< size*2` 只 warn（合并阶段分片与新文件并存） |
| — | 超长分片自愈 | `_worker` 遇 `have > want` 直接删掉该分片重下。**不能用截断**：截断只去掉尾部，前面的垃圾字节会随合并进入成品，尺寸校验查不出、只有哈希能发现 |
| CORE-024 | HTTP 错误分流 | `urllib` 对 4xx/5xx 直接抛 `HTTPError`，拿不到 `r.status`，必须按 `code` 分流（实现在 `httpinfo.py`）。**416**：视同「该源不支持分段」，记入 `_no_range_mirrors`（与 CORE-011 的 200 保护同一份名单）；全部源都 416 时置 `_fatal` 结束分片阶段（与 CORE-022 的 ENOSPC 同一通路），由 `_fetch` 退化 `_download_single`；部分源 416 时不得作废已下载分片。**401/403/404 等永久错误**：不按退避策略重试同一源，但允许换源再试一次（每个源至多一次；全部源都永久失败才判定该分片失败）。**408/429** 视为暂时性，仍按退避重试 |
| CORE-025 | 进度计入口径 | 进度与合并校验必须同源，否则会出现「进度满格然后失败」。判据式：`credit_i = _credited(size_i, want_i)`，其中 `size_i` 是第 i 片在磁盘上的实际长度、`want_i` 是该片的期望长度，`_credited(size, want) = size if 0 <= size <= want else 0`（**超长的一分不算**，该片无效必须整片重下）。因此 `done = Σ credit_i ≤ total`，`percent ≤ 100` 恒成立；「进度 100%」的充要条件是全部分片长度恰好等于期望长度，此时合并必定成功。计入与扣减必须走同一个函数：分片被删除时按 `_credited` 扣回，不另立口径。**写入前拦截**：写入的数据超出本片期望长度时不得落盘（超出的部分属于别的区间），必须先判后写并换源重试 |
| — | 取消检查点 | 合并每片前、`_verify` 每 4MB 前都检查 `_cancel`，大文件取消不必等全量拷贝/哈希完成 |
| — | 重试退避 | `min(8.0, 2**attempt) + random(0, 0.4)`，即 1/2/4/8/8 秒并带抖动 |
| — | 续传指纹 | `meta.json` 记录 `etag`；`size`、`chunks`、`etag` 三者任一不符即删除全部分片 |

**并发约定**：`_floor_kb` 由 reporter 线程写、worker 线程读，依赖 CPython 对单个属性赋值/读取的原子性。若将来改成浮点或复合结构，必须加锁——`CODE-006` 对「共享可变状态」的要求优先。

### 10.1 契约行为落地（CODE-013）

契约用文字描述的「必须发生」的行为，必须在代码里真的发生。下列调用点是本模块的落地清单，校验器逐条核对（CODE-013）：

```contract
{
  "checks": [
    {"type": "call_site", "module": "downloader",
     "calls": [
       {"in": "DownloadTask.run", "call": "expand_mirror_urls"},
       {"in": "DownloadTask.run", "call": "diskutil.check_target"},
       {"in": "DownloadTask.run", "call": "rank_mirrors"},
       {"in": "DownloadTask._download_chunked", "call": "_credited"},
       {"in": "DownloadTask._worker", "call": "_credited"},
       {"in": "DownloadTask._worker", "call": "range_rejected"},
       {"in": "DownloadTask._merge", "call": "shutil.copyfileobj"},
       {"in": "_measure_mirror", "call": "probe"}
     ]},
    {"type": "call_site", "module": "httpinfo",
     "calls": [
       {"in": "probe", "call": "filename_from"}
     ]}
  ]
}
```

`in` 的定位规则：`Class.method` 先按「模块内类名 + 方法名」精确匹配；`function` 按模块级函数名匹配。匹配不到函数本身即判失败（提示「契约声明的调用点不存在」），不静默跳过。

`call` 的匹配规则分两档，**不得用末段名近似**：

| 声明形态 | 匹配要求 | 例 |
|---|---|---|
| 单段名 `S` | 被调用者是 `Name(id=S)` 或 `Attribute(attr=S)`，且 `Attribute` 的基对象不是别的模块别名 | `"probe"` 命中 `probe(...)`；`"filename_from"` 命中 `filename_from(...)` |
| 多段名 `M.S` | 必须精确匹配 `Attribute(value=Name("M"), attr="S")` 的完整形式 | `"diskutil.check_target"` 命中 `diskutil.check_target(...)`，但**不**命中别处的裸 `check_target(...)` |

多段名不采用「末段名近似」，是为了让「哪个模块提供的」这条边界可判定 —— 否则 `httpinfo.probe` 里的 `filename_from` 会让 `downloader` 作用域的同名裸调用误判为命中。

`httpinfo` 那块守的是「`httpinfo.probe` 用 `naming` 取文件名」：`naming` 模块的存在意义正是封装这条调用链，契约里没有它的锚点就是「实现里有、契约里无」，正是本检查要显性化的东西。

## 11. 待实现契约（占位，落地后转为正式条目）

| 编号 | 内容 | 关联 |
|---|---|---|
| CORE-010 | 动态分片调度中的「把一片再切细」——已评估后放弃：队列取片 + 4× 粒度 + 慢链换源已覆盖主要收益，动态改写分片边界会破坏 `meta.json` 的续传稳定性 | REQ-008b（不做） |

---

作者：shanshuifeng ｜ 项目地址：https://github.com/shanshuifeng/Download-tool ｜ 许可：Apache-2.0（见 `LICENSE`）
