# CONTRACT · 数据与磁盘布局

契约版本 v1.0 ｜ 消费方：三个入口 + 外部调用方（Agent 会读 job.json）

## 1. 配置目录决策（DATA-001）

| 场景 | 配置位置 |
|---|---|
| 源码运行（未打包） | 源码目录 |
| 打包后，exe 位于用户目录内（桌面、文档、下载） | `%APPDATA%\下载工具\config.json` |
| 打包后，exe 位于用户目录外（U 盘、D 盘） | exe 同目录 `config.json` |

判据：`sys.frozen` 为真，且 `BASE` 的绝对路径以用户主目录开头（不区分大小写）。

**约束**：目录不可写时静默退回 `BASE`；读写失败一律静默（不能让配置问题阻断下载）。

## 2. `config.json`（DATA-002）

```contract
{
  "checks": [
    {"type": "dict_keys", "file": "gui.pyw", "name": "DEFAULTS",
     "keys": ["last_url", "last_dir", "threads", "chunk_mb", "slow_kb",
              "slow_sec", "retries", "timeout", "max_speed_kb", "proxy",
              "concurrent", "extra_mirrors", "advanced_open"]}
  ]
}
```

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `last_url` | str | `""` | 上次输入，重开时回填 |
| `last_dir` | str | `~/Downloads` | 上次保存位置 |
| `threads` | int | 16 | 1–32（GUI 滑杆上限） |
| `chunk_mb` | int | 0 | 0=自动 |
| `slow_kb` | int | 15 | 0=关闭 |
| `slow_sec` | int | 12 | ≥3 |
| `retries` | int | 6 | 0–20 |
| `timeout` | int | 30 | 5–120 |
| `max_speed_kb` | int | 0 | 每任务限速，0=不限（GUI 滑杆上限 10MB/s）；并发多任务时合计速率高于设定值 |
| `proxy` | str | `""` | 空=跟随系统代理；`direct`=强制直连；其他为代理地址 |
| `concurrent` | int | 2 | 同时进行的任务数，1–4 |
| `extra_mirrors` | str | `""` | 逗号分隔的镜像前缀 |
| `advanced_open` | bool | false | 高级面板展开状态 |

**新增规则**：新键必须有默认值；`load_cfg()` 用默认字典打底再 `update`，因此旧配置文件自动兼容。**不得**依赖某个键必定存在。

`concurrent` 与剪贴板监听均已落地（REQ-013 / REQ-011）。剪贴板不写配置项，按 `after(900)` 轮询。

## 3. 分片目录与 `meta.json`（DATA-003）

```
<out_path>.parts/
├── meta.json
├── part0000
├── part0001
└── ...
```

```json
{
  "size": 367525888,
  "chunks": [[0, 33554431], [33554432, 67108863]],
  "mirrors": ["https://gh-proxy.com/https://github.com/..."],
  "etag": "\"5f3c1a-2b8e0\""
}
```

| 字段 | 类型 | 语义 |
|---|---|---|
| `size` | int | 文件总字节数，用于校验分片边界 |
| `chunks` | list[[start, end]] | 闭区间，按序即合并顺序 |
| `mirrors` | list[str] | 本次探测后的可用源，仅供排查，不参与续传判定 |
| `etag` | str/null | 服务端 `ETag`，缺失时退回 `Last-Modified`；与当前响应不一致即作废旧分片 |

**复用规则**：`size`、`chunks`、`etag` 三者**全部一致**才复用旧分片；任一不符删除全部 `part*` 重新开始。这是硬边界，改判定条件等于改契约。旧版本 meta 没有 `etag` 字段，会判为不符——属于一次性代价，宁可重下也不拼错。

**`part` 文件语义**：文件名 `part%04d`，内容是该区间**从头开始**的连续字节，长度 ≤ `end-start+1`。续传时以文件大小作为已下载量，因此**必须追加写（`ab`）**，且必须保证服务器返回的正是该区间——这正是 REQ-001 要修的洞。

**超长分片**：长度超过 `end-start+1` 的分片一律**计 0**（进度口径见 CORE-025），且必须整片删除重下——**不得截断**，截断只会保住前面的垃圾字节，静默产出坏文件，尺寸校验查不出、只有哈希能发现。引擎在**写入前**就拦截越界数据（超出的部分属于别的区间，落盘即污染本片），因此超长片不得进入合并阶段。

**进度口径**：分片计入进度的字节数由 `_credited(size, want)` 决定（`size > want` 时计 0）。计入与扣减走同一函数，不另立口径。

## 4. 临时文件与隔离文件（DATA-004）

| 路径 | 何时出现 | 何时消失 |
|---|---|---|
| `<out>.part` | 单线程路径的中间文件 | 成功后 `os.replace` 为正式文件 |
| `<out>.part.json` | 单线程续传指纹（`size` / `etag` / `url`），开下前写入 | 成功落盘后删除；取消/失败保留 |
| `<out>.parts/` | 分段路径 | 合并成功后 `rmtree` |
| `<out>.corrupt` | 大小或哈希校验失败 | 下次失败时被覆盖；不自动删除 |

**约束**：不得在项目目录、`%TEMP%`、注册表、用户目录之外写任何东西。

**指纹缺失或损坏**一律视为不可信：调用方丢弃 `.part` 从头下载，不做「按大小接着写」的猜测。
`etag` 缺失时只能退回比大小，属于已知天花板（DATA-003 同理）。

## 5. `job.json`（DATA-005）

供 `下载工具.exe --job` 使用。字段与命令行参数一一映射，且**接受两套别名**以兼容早期版本。

| 键 | 别名 | 类型 | 缺省 |
|---|---|---|---|
| `urls` | `url`（单值） | list[str] | — |
| `out` | `output` | str | — |
| `threads` | — | int | 16 |
| `sha256` | — | str/null | null |
| `chunk_mb` | `chunk` | int | 0 |
| `slow_kb` | `slow` | int | 15 |
| `slow_sec` | — | int | 12 |
| `retries` | — | int | 6 |
| `timeout` | — | int | 30 |
| `proxy` | — | str/null | null |
| `max_speed` | `max_speed_kb` | int | 0 |
| `mirrors` | — | list[str] | [] |

**优先级**：命令行显式参数 > job 文件 > 内置默认。当前实现的判定方式是「值等于默认值即认为未显式传入」，存在歧义（见 CONTRACT-cli 第 1 节说明），v2 修复前不要依赖。

## 6. 哈希识别（DATA-006）

只按长度识别，不信任前缀：

| 长度 | 算法 |
|---|---|
| 32 | md5 |
| 40 | sha1 |
| 64 | sha256 |
| 128 | sha512 |

大小写不敏感，比较前统一转小写；输出时原样返回。长度不匹配任何算法（例如 50 位）时**直接报「哈希长度不匹配任何支持的算法」**，不要伪装成「校验失败」——后者会让用户误以为是文件坏了。

---

作者：shanshuifeng ｜ 项目地址：https://github.com/shanshuifeng/Download-tool ｜ 许可：Apache-2.0（见 `LICENSE`）
