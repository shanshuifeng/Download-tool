# CONTRACT · 命令行接口

入口 `dl.py` → `dl.exe` ｜ 契约版本 v1.0（schema v1）｜ 消费方：脚本、批处理、CI、AI Agent

## 0. 定位

`dl.exe` 是**机器接口**，不是给人看的。三条铁律：

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
| `--max-speed` | int | 0 | 全局限速 KB/s，0 = 不限 |
| `--mirror` | str，可重复 | — | 镜像前缀（以 `/` 结尾则直接拼在原 URL 前） |
| `--hash` | flag | 关 | 下载后计算并输出 sha256 |
| `--json` | flag | 关 | JSON Lines 事件流 |
| `--quiet` | flag | 关 | 只输出最终结果 |
| `--job` | str | — | 从 JSON 文件读参数 |
| `--schema` | flag | 关 | 打印接口描述后退出 |

**注意**：`--threads/--slow/--slow-sec/--retries/--timeout` 的 argparse 默认值与 job 文件同名字段存在「谁优先」的问题——当前实现用「等于默认值则取 job 文件」来判定用户是否显式传参。这是已知的语义缺陷（用户显式传 `--threads 16` 时会被 job 覆盖），**在 v2 之前不得依赖该行为**。修复方向：改用 `argparse.SUPPRESS` 或哨兵默认值。

## 2. 退出码（CLI-002）

```contract
{
  "checks": [
    {"type": "exit_codes", "module": "dl",
     "codes": {"0": "EXIT_OK", "1": "EXIT_FAIL", "2": "EXIT_ARGS",
               "3": "EXIT_NOMIRROR", "130": "EXIT_CANCEL"}}
  ]
}
```

| 码 | 含义 | 判据 |
|---|---|---|
| 0 | 成功 | 文件已下载并通过校验 |
| 1 | 下载或校验失败 | 分片耗尽重试、哈希不符、大小不符 |
| 2 | 参数错误 | 缺 url、缺 `-o`、job 文件读不了 |
| 3 | 所有镜像不可用 | `run()` 抛的消息含「不可用」 |
| 130 | 被中断 | `KeyboardInterrupt` |

**禁止**新增退出码而不更新本表。判据「消息含『不可用』」是脆弱实现，**v2 应改为异常子类区分**，在此之前改动错误文案必须同步检查此处。

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
| `progress` | 下载中，≥1.5s 且百分比变化 ≥1% 才发 | `eta` 在速度 <2KB/s 时为 `null`；`speed` 为 B/s |
| `done` | 成功后一次 | `verified` 无期望哈希时为 `null`；`avg_speed` 为 B/s |
| `error` | 失败后一次 | `code` 与退出码一致 |

`start` 事件曾在 schema 中声明但实现从未发出，已移除（见变更记录）。若将来需要，应先改本节再改代码。

**兼容规则**：字段只增不改。消费方必须忽略未知字段。

## 4. 输出通道（CLI-004）

| 通道 | 内容 | 编码 |
|---|---|---|
| stdout | 进度、`done` 事件、`--quiet` 时的最终路径 | 强制 UTF-8（`reconfigure`），不可用时静默跳过 |
| stderr | `[error]` 人类可读错误 | 同上 |

- `--json` 与 `--quiet` 同时存在时，`--json` 优先，仍然输出事件
- `--quiet` 且非 `--json` 时，stdout 只输出一行文件路径（便于 `$(dl.exe ...)` 取值）
- 不得向 stdout 输出除以上之外的内容

## 5. `--schema`（CLI-005）

必须自描述且与实际行为一致：`dl.exe --schema` 的输出就是本档第 1/2/3 节的机器可读版本。校验器确保 `SCHEMA` 常量与 `argparse` 不漂移。

## 6. 明确不做

| 编号 | 项 | 理由 |
|---|---|---|
| CLI-008 | `--concurrent` 队列并发数 | 一个进程就是一次任务，进程内排队没有意义。批量并发应由调用方（脚本 / Agent）自己控制进程数 |
| CLI-009 | 单独的 `--socks5` 参数 | 已由 `--proxy socks5://host:port` 覆盖，多一个入口只会增加歧义 |
