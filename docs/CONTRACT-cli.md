# CONTRACT · 命令行接口

入口 `dl.py` → `下载工具.exe`（命令行模式）｜ 契约版本 v1.0（schema v2）｜ 消费方：脚本、批处理、CI、AI Agent

## 0. 定位

打包后与界面共用同一个 exe：带参数走本接口，没参数开界面（`gui.pyw` 的 `main()` 分发）。
接口名称仍是 `dl`，`--schema` 的输出格式不变；本文中的 `下载工具.exe` 均指其命令行模式。

本接口（命令行模式）是**机器接口**，不是给人看的。三条铁律：

1. 参数进、事件出、退出码说话
2. 不弹窗、不交互、不等待输入
3. 人类可读输出可以变，结构和退出码不能变

## 1. 参数集（CLI-001）

`SCHEMA["args"]` 与实际 `argparse` 定义必须完全一致，由校验器保证。

```contract
{
  "checks": [
    {"type": "schema_vs_argparse", "module": "dl"}
  ]
}
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `<url>...` | 位置，可多个 | 必填 | 多个视为同一文件的镜像 |
| `-o/--out` | str | 必填 | 目录或完整路径 |
| `-t/--threads` | int | 16 | 1–64 |
| `--sha256` | str | — | sha256/sha1/md5/sha512 按长度自动识别 |
| `--chunk` | int | 0 | 每片 MB，0=自动 |
| `--slow` | int | 15 | 慢速阈值 KB/s，0=关闭 |
| `--slow-sec` | int | 12 | 慢速持续秒数 |
| `--retries` | int | 6 | 单片重试 |
| `--timeout` | int | 30 | 连接超时秒数 |
| `--proxy` | str | — | 代理地址，支持 `http://` 与 `socks5://`（可带用户名密码）；`direct` = 强制直连；省略则跟随 `HTTP_PROXY` 等环境变量 |
| `--max-speed` | int | 0 | 每任务限速 KB/s，0 = 不限（并发多任务时合计速率高于设定值） |
| `--mirror` | str，可重复 | — | 镜像前缀（以 `/` 结尾则直接拼在原 URL 前） |
| `--hash` | flag | 关 | 下载后计算并输出 sha256 |
| `--json` | flag | 关 | JSON Lines 事件流 |
| `--quiet` | flag | 关 | 只输出最终结果 |
| `--job` | str | — | 从 JSON 文件读参数 |
| `--schema` | flag | 关 | 打印接口描述后退出 |

### 1.1 参数优先级（CLI-001a）

**命令行优先于 job 文件。** 三档取值，从上到下：

| 优先级 | 来源 | 判据 |
|---|---|---|
| 1 | 命令行 | 该参数**显式出现过**（哪怕显式传的就是默认值，如 `--threads 16`） |
| 2 | job 文件 | 命令行没传，且 job 文件里写了该字段 |
| 3 | 业务默认值 | 两边都没写 |

实现约束（BUG-29）：

- `argparse` 的默认值一律是 `None` 哨兵，**不得**把业务默认值直接写进 `default=`。否则「用户没传」与「用户显式传了默认值」无法区分，job 文件会反过来覆盖命令行
- 业务默认值集中在 `DEFAULTS`，其内容与 `SCHEMA["defaults"]` 同源；`SCHEMA["args"]` 的描述里也必须继续写明默认值，schema 是给消费方看的机器可读描述，不能因为内部改哨兵就丢掉默认值信息
- job 文件没写的字段一律视为「未指定」，走默认值，不得在解析阶段就把默认值烤进 job 字典

### 1.2 `--schema` 的 `defaults` 段（CLI-005b）

`SCHEMA["defaults"]` 以机器可读方式给出上表「默认」列的取值（`threads` / `chunk` / `slow` / `slow_sec` / `retries` / `timeout` / `max_speed`），供脚本与 AI Agent 直接读取。`SCHEMA["args"]` 的文字描述同样保留默认值，两处不得互相矛盾。

### 1.3 唯一命令行入口（CLI-010）

**`dl.py` 是本项目唯一的命令行实现。** 引擎层（`downloader.py`）不提供命令行入口，也不得出现 `argparse`。

| 位置 | 职责 |
|---|---|
| `dl.py` | 唯一的参数解析、事件输出、退出码映射 |
| `downloader.py` | 纯引擎 API，不含任何参数解析代码 |
| `gui.pyw` | 唯一图形入口；带参数时转发给 `dl.main()` |

理由：两套解析器并存时，第二套不受任何检查覆盖，能力差异会长期潜伏（BUG-30 的成因）。收敛到一处后，校验器的 `schema_vs_argparse` 才能覆盖全部参数。

`python src/downloader.py` 已不再是入口，直接运行会提示改用 `dl.py` 并以非零码退出。

## 2. 退出码（CLI-002）

```contract
{
  "checks": [
    {"type": "exit_codes", "module": "dl",
     "codes": {"0": "EXIT_OK", "1": "EXIT_FAIL", "2": "EXIT_ARGS",
               "3": "EXIT_NO_MIRROR", "130": "EXIT_CANCEL"}}
  ]
}
```

| 码 | 含义 | 判据 |
|---|---|---|
| 0 | 成功 | 文件已下载并通过校验 |
| 1 | 下载或校验失败 | 分片耗尽重试、哈希不符、大小不符 |
| 2 | 参数错误 | 缺 url、缺 `-o`、job 文件读不了 |
| 3 | 所有镜像不可用 | `run()` 抛出携带 `code=3` 的 `DownloadError` |
| 130 | 被中断 | `KeyboardInterrupt` |

**禁止**新增退出码而不更新本表。退出码由异常自带：`DownloadError.code` 为缺省退出码，`dl.py` 直接取用该字段，**不再依据错误文案判定**。新增失败类型时须同时给出对应的 `code`。

## 3. 事件流（CLI-003）

`--json` 时 stdout 每行一个对象，UTF-8，`ensure_ascii=False`。

```contract
{
  "checks": [
    {"type": "event_fields", "module": "dl",
     "events": {
       "progress": ["event", "percent", "done", "total", "speed", "eta"],
       "done": ["event", "path", "size", "sha256", "sha256_expected", "verified", "elapsed", "avg_speed"],
       "error": ["event", "code", "message"]
     }}
  ]
}
```

| 事件 | 时机 | 关键字段语义 |
|---|---|---|
| `progress` | 下载中；**距上次输出 ≥1.5s 或**相对上次输出的**百分比变化 ≥1%** 时发出（**OR 关系**，见 CLI-012） | `eta` 在速度 <2KB/s 时为 `null`；`speed` 为 B/s |
| `done` | 成功后一次 | `verified` 无期望哈希时为 `null`；`avg_speed` 为 B/s |
| `error` | 失败后一次 | `code` 与退出码一致 |

`start` 事件曾在 schema 中声明但实现从未发出，已移除。若将来需要，应先改本节再改代码。

**兼容规则**：字段只增不改。消费方必须忽略未知字段。

### 3.1 `progress` 节流判据（CLI-012）

节流判据是 **OR**，不是 AND：

```
输出 ⟺ 距上次输出 ≥ 1.5s  **或**  相对上次输出的百分比变化 ≥ 1%
```

| 判据 | 取值 |
|---|---|
| `PROGRESS_INTERVAL_SEC` | 1.5 |
| `PROGRESS_PERCENT_DELTA` | 1.0 |

```contract
{
  "checks": [
    {"type": "const", "module": "dl",
     "values": {"PROGRESS_INTERVAL_SEC": 1.5, "PROGRESS_PERCENT_DELTA": 1.0}}
  ]
}
```

为什么是 OR 而不是 AND：AND 语义下，1GB 文件的 1% 意味着 10MB，链路上 1.5s 内很难变化 1%，会出现长时间静默——对脚本、CI、AI Agent 这类消费方不友好。OR 语义下事件流至少每 1.5s 有一条进度，慢速下载不会被误判为卡死。

边界：两个判据都是「≥」而非「>」，恰好等于阈值即触发输出。

## 4. 输出通道（CLI-004）

| 通道 | 内容 | 编码 |
|---|---|---|
| stdout | 进度、`done` 事件、`--quiet` 时的最终路径 | 强制 UTF-8（`reconfigure`），不可用时静默跳过 |
| stderr | `[error]` 人类可读错误 | 同上 |

- `--json` 与 `--quiet` 同时存在时，`--json` 优先，仍然输出事件
- `--quiet` 且非 `--json` 时，stdout 只输出一行文件路径（便于 `$(下载工具.exe ...)` 取值）
- 不得向 stdout 输出除以上之外的内容

## 5. `--schema`（CLI-005）

必须自描述且与实际行为一致：`下载工具.exe --schema` 的输出就是本档第 1/2/3 节的机器可读版本。校验器确保 `SCHEMA` 常量与 `argparse` 不漂移。

### 5.1 `SCHEMA.version` 的递增义务（CLI-011）

`SCHEMA["version"]` 是**接口版本号**，供脚本与 AI Agent 判断兼容性。`SCHEMA` 的任何内容变化都必须递增版本号，由校验器强制。

**结构指纹算法**（校验器与本档使用同一套）：

```
指纹 payload = SCHEMA 去掉 "version" 键后的全部键；
序列化方式 = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")；
哈希算法 = sha256，取十六进制小写。
```

取**全部键**而非逐键列举（`args` / `defaults` / `events` / `exit_codes` / `name` / `usage`）：逐键列举会漏掉将来新增的顶层键，`defaults` 就是这样漏过一次。指纹的用途是检测 `--schema` 输出的任何变化——`defaults` 是输出的一部分，消费方读得到，它变了就该要求契约更新；排除在外等于给「默认值被悄悄改掉」开后门。

口径必须写在本节正文而不能只写在 JSON 块里：下一个维护者按别的口径去算指纹，得到的值与契约声明对不上，检查立刻报红，而且报红原因还难懂。

**改接口时的四步**（顺序不可颠倒）：

1. 改 `SCHEMA`（文案或增删键）；
2. 算新指纹；
3. `SCHEMA["version"]` 递增；
4. 契约块换最终态（`version` / 当前指纹 / `previous` 三项）。

第 3 步与第 4 步的两半必须相邻——只升版本号不写块，或只写块不升版本号，都会报红。

```contract
{
  "checks": [
    {"type": "schema_version", "module": "dl",
     "version": 2,
     "fingerprint": "e0e5aed3c2b389dc4babfa0eaf2d9fe2cd92dfbffad97b370a94dec766d89b47",
     "previous": {"version": 1,
                  "fingerprint": "1eae02a14e5b6704f69e69c1af8babd0169c272f79493e021eeacf5023b9fa37"}}
  ]
}
```

**四级判定规则**：

| # | 场景 | 判据 | 动作 |
|---|---|---|---|
| 1 | 内容漂移 | 实算指纹 ≠ 声明指纹 | RED |
| 2 | 版本号漂移 | `SCHEMA["version"]` ≠ 声明 version | RED |
| 3 | 版本降级 | `version < previous.version` | RED |
| 4 | **递增与内容变化不同步** | `(version > previous.version)` 与 `(fingerprint != previous.fingerprint)` **必须同真同假** | RED |

第四条措辞要精确：不是「两个都要真」（那会让中间态误报），而是「要么都真（升了版且内容变了），要么都假（没升版且内容没变）」。

规则 3 不可省：`fingerprint != previous.fingerprint` 只能发现「内容变了」，发现不了「内容变了但版本号没跟上」——而后者正是 BUG-36 要防的事。消费方看到 `version` 没变就以为接口没变。

**形态校验硬失败**：`version` 必须是整数、`fingerprint` 必须是 64 位小写十六进制、`previous` 必须是恰好含 `version` 与 `fingerprint` 两键的字典。形态不合法直接记 RED 并说明缺什么，**不允许因字段缺失就跳过这项检查**——静默放行正是本条要堵的洞。

**报红信息里的 payload 键集必须由实际 payload 派生，不得硬编码。** 这条看着只是多打几个字，实际救过一次误判：若报红信息只说「指纹不符」而不说键集，维护者会以为「内容变了」，而实际上可能是「口径变了」。诊断信息本身也是契约的一部分，**必须与实现同源**——否则它会在说谎，把排查方向直接带偏。形态校验失败时，报红信息同样要带上声明指纹与实算指纹（或说明「无法比对指纹」的原因），让一条信息同时覆盖「形状不对」与「指纹漂移」两种情况。

### 5.2 默认值只写一处（CLI-013）

`SCHEMA["args"]` 的文案描述**接口形状**，`SCHEMA["defaults"]` 描述**取值**。同一事实只写一处：文案的「默认 N」句式与 `defaults` 重复，删掉前者。

但**哨兵语义不是默认值重复**，必须保留：

| 文本 | 含义 | 处置 |
|---|---|---|
| `--chunk` 的「0=自动」 | 取 0 会自动分片（哨兵语义） | **保留** |
| `--max-speed` 的「0=不限」 | 取 0 表示不限速（哨兵语义） | **保留** |
| `--slow` 的「0=关闭」 | 取 0 表示关闭慢速判定（阈值语义） | **保留** |
| 「默认 16」这类句式 | 不传时用多少（默认值重复） | **删除** |

把「0=自动」当成默认值重复是错的：将来只把 `defaults["chunk"]` 从 0 改成 4，文案「每片大小 MB，0=自动」**仍为真**（0 始终是自动分片的哨兵值）。而若改成「不指定则自动均分」，将来默认值改成 4 后这句话**立刻变假**——机器可读接口里的话变成假话是最坏的一类缺陷。

**判据是句式，不是数字扫描**：用正则匹配「默认 N」句式，而不是扫描文案里出现的所有数字。

```contract
{
  "checks": [
    {"type": "schema_defaults", "module": "dl",
     "map": {"threads": "-t/--threads", "chunk": "--chunk", "slow": "--slow",
             "slow_sec": "--slow-sec", "retries": "--retries",
             "timeout": "--timeout", "max_speed": "--max-speed"},
     "pattern": "默认\\s*(\\d+)",
     "must_contain": {"chunk": "0=自动", "max_speed": "0=不限"}}
  ]
}
```

| 情形 | 结论 |
|---|---|
| 不含「默认 N」句式 | 合规 |
| 含「默认 N」且 N == `defaults` 的值 | **重复** —— 默认值被写了两遍，应删除该句式 |
| 含「默认 N」且 N != `defaults` 的值 | **漂移** —— 文案说的是另一个数 |
| 含「0=」句式 | **豁免** —— 哨兵语义，合法 |

**归一化**：args 参数名去掉 `-x/` 前缀 → 连字符转下划线。`--slow-sec` → `slow_sec`、`--max-speed` → `max_speed`、`-t/--threads` → `threads`。不换下划线会漏掉两条。

**契约 `map` 是显式声明，不是事实源。** 检查以 `SCHEMA["defaults"]` 与 `SCHEMA["args"]` 的归一化反查为准；`map` 本身也受校验——它把某个默认值声明到不对应的参数上时同样报红。`map` 的价值是「把对应关系写出来给人看」，而不是「靠它决定查哪个参数」。

**为什么必须反查、不能采信 `map`**　`map` 是手工维护的白名单，写错一个键，那条默认值就完全不受检查：`--slow-sec` 的文案即使复述了「默认 12」，只要 `map` 把它错接到 `--slow` 上就抓不到——旧实现正是采信 `map`，于是它压根没查 `--slow-sec`，全套校验照旧报绿。这与 BUG-43（键没登记）同根因：手工维护的白名单会与代码漂移，只是漂移的形态不同（没登记 / 登记错了）。实测这 7 条映射全部可由归一化反查得到且无碰撞，因此 `map` 对「查哪个参数」而言是冗余的。

**四个方向都要查**（BUG-43 / BUG-45）：

| 方向 | 判据 | 不满足时 |
|---|---|---|
| `defaults` → `args` | `defaults` 的每个键都要在 `args` 里有对应参数（**归一化反查**得到） | 报红：默认值在 args 里没有对应参数 |
| `map` → `defaults` | `map` 的每个键都必须存在于 `defaults` | 报红：默认值被删了，契约没跟上 |
| `map` → 反查结果 | `map` 声明的参数经归一化后必须等于它声明的默认值键 | 报红：声明与事实对不上 |
| `defaults` → `map` | `defaults` 的每个键都必须登记进 `map` | 报红：契约声明不完整（该默认值的文案仍按反查受检） |

**为什么必须都查**　`defaults` 与 `args` 是代码里的事实，契约 `map` 是对它们的**声明**。漏查任何一个方向都留了绕过口：漏 `defaults` → `map` 则新增的默认值键整体逃逸（BUG-43）；漏 `map` → 反查结果则 map 写错就能把一条默认值从检查里摘出去（BUG-45）。声明漏了事实、或声明与事实对不上，都是声明没跟上。

注意 `defaults` → `map` 这一条**不再意味着「该默认值不受检查」**：主判据已改为从 `args` 反查，漏登记只说明契约声明不完整，该默认值的文案照样受检。

`defaults` 的键名与 `map` 的键名形态一致（都是 `slow_sec` 这种下划线形态），比对时直接比即可。

**`args` 侧是单向的**：`defaults` 的每个键都要在 `args` 里有对应参数（归一化后），缺失即错；**反过来不查**——`url` / `-o/--out` / `--sha256` / `--proxy` / `--mirror` / `--hash` / `--json` / `--quiet` / `--job` / `--schema` 这十个参数本来就没有默认值，双向比对会一上线就全线报红。

`must_contain` 守住哨兵语义不可丢：将来有人把「0=自动」删掉改写成「不指定则自动」，用例会报红。

### 5.3 `SCHEMA` 保持纯字面量（CLI-014）

`SCHEMA` 必须是**纯字面量字典**——不得 f-string 渲染、不得 `dict(...)` 调用、不得引用变量。这条不变量是 `chk_dict_keys` 与 `schema_defaults` 能做 AST 静态提取的前提：一旦 `SCHEMA` 变成派生表达式，静态提取就失效，校验器会**静默空转**。

作用域只限 `SCHEMA` 这一个常量，不扫全模块的字典——`dl.py` 里的 `DEFAULTS = dict(SCHEMA["defaults"])` 不是字面量，而它恰恰是「运行期以 schema 为唯一来源」那条关系，扫到它就误报了。

```contract
{
  "checks": [
    {"type": "literal_dict", "file": "dl.py", "name": "SCHEMA"}
  ]
}
```

## 6. 明确不做

| 编号 | 项 | 理由 |
|---|---|---|
| CLI-008 | `--concurrent` 队列并发数 | 一个进程就是一次任务，进程内排队没有意义。批量并发应由调用方（脚本 / Agent）自己控制进程数 |
| CLI-009 | 单独的 `--socks5` 参数 | 已由 `--proxy socks5://host:port` 覆盖，多一个入口只会增加歧义 |

---

作者：shanshuifeng ｜ 项目地址：https://github.com/shanshuifeng/Download-tool ｜ 许可：Apache-2.0（见 `LICENSE`）
