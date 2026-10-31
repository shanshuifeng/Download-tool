# CONTRACT · 界面层

入口 `gui.pyw` → `下载工具.exe` ｜ 契约版本 v1.0 ｜ 消费方：`gui.pyw` 自身、未来的任务列表改造

## 0. 边界

- 界面层**只负责**：收集输入、展示进度、把用户动作翻译成引擎调用
- 界面层**不碰网络**：不得 import `urllib` / `http.client` / `socket`，一切下载都经 `DownloadTask`
- 界面层只允许从引擎取三个符号：

```contract
{
  "checks": [
    {"type": "imports_from", "file": "gui.pyw", "module": "downloader",
     "names": ["human"]},
    {"type": "imports_from", "file": "gui.pyw", "module": "taskqueue",
     "names": ["DownloadQueue"]},
    {"type": "forbidden_imports", "file": "gui.pyw",
     "names": ["urllib.request", "http.client", "socket", "requests"]}
  ]
}
```

## 1. Tk 线程规则（GUI-001）

**唯一一条不可协商的规则**：Tk 控件只能在主线程操作。

引擎的 `log` / `progress` 回调跑在工作线程里，因此必须：

```
工作线程 ──put──> queue.Queue ──after(80ms)──> 主线程 _drain() ──> 改控件
```

禁止事项：
- 在工作线程里直接 `config()` / `insert()` / `set()`
- 用 `root.after` 从工作线程调度（Tk 非线程安全）
- 用 `wait_variable` / `mainloop` 嵌套等待

## 2. 队列消息协议（GUI-002）

主线程与工作线程之间只有一个通道：`queue.Queue`。元素固定为二元组 `(kind, payload)`，当前只有一种 kind：

| kind | payload | 触发 |
|---|---|---|
| `"task"` | `(kind, tid, kw)` 三元组 | 队列的 state / progress / log 事件 |

`kw` 按子类型区分：

| 子 kind | kw |
|---|---|
| `"state"` | `state` ∈ queued/running/done/failed/cancelled；`path` / `message` 视状态可选 |
| `"progress"` | `data`：引擎的 progress dict（见 CORE-005b） |
| `"log"` | `msg`、`level` |

**新增 kind 必须同时改 `_drain()` 与本表**。未知 kind 必须被忽略而不是抛异常（向前兼容）。

## 3. 控件 API（GUI-003）

自绘控件统一遵循：构造时给逻辑像素，内部过 `S()` 转物理像素。

| 控件 | 签名 | 关键约束 |
|---|---|---|
| `Button` | `(master, text, command, kind="primary", height=46, width=None)` | `kind ∈ {primary, ghost}`；`set_state("normal"/"disabled")`；`set_text()` 后需重绘 |
| `Slider` | `(master, lo, hi, value, step=1, fmt=None, label_w=84)` | `.value` 为当前值；拖动结束不触发额外回调 |
| `ThinBar` | `(master)` | `.set(pct: float 0–100)`；不留系统边框 |
| `HintEntry` | `(master, hint="")` | `.value()` 返回去空白的文本；空时返回 `""` 而非占位符 |
| `SlimScroll` | `(master, target)` | 绑定目标 `Canvas`/`Text` 的 yview |

**样式令牌**集中定义在文件头（`BG`/`SURFACE`/`TEXT`/`MUTED`/`ACCENT`/`ERR`/`WARN`/`PLACEHOLDER` 等），**禁止在控件内部硬编码色值**。新增颜色必须先加令牌再引用。

## 4. DPI（GUI-004）

- 进程级：`SetProcessDpiAwareness(2)`（per-monitor），失败退回 `SetProcessDPIAware()`
- 所有像素尺寸、线宽、圆角半径必须经 `S()`；`HAIR = max(1, S(1))` 保证 1px 细线不被抹掉
- 字体字号不缩放（Tk 字体由系统 DPI 处理），但容器尺寸必须缩放
- 深色标题栏通过 `DwmSetWindowAttribute(hwnd, 20|19, 1)`，且需在 `update_idletasks()` 之后调用两次（首次可能不生效）

## 5. 界面状态机（GUI-005）

状态属于**每个任务**，不再属于窗口。窗口只有一个底部汇总条。

```
queued ──调度──> running ──成功──> done
   │                │
   │                ├──失败──> failed
   └──取消──────────┴──取消──> cancelled
```

| 状态 | 行内按钮 | 点击行为 |
|---|---|---|
| queued | 取消 | 直接从待办队列摘除，不会启动 |
| running | 取消 | 置取消标志，已下分片保留 |
| done | 打开 | `explorer /select,` 定位文件 |
| done（文件已不在） | 打开 → 移除 | 首次提示「文件已不在」，按钮切到「移除」；再点才删行，不得静默抹掉 |
| failed / cancelled | 移除 | 从列表删除该行；列表空时整块隐藏 |

**底部汇总**：`进行中 N · 等待 N · 完成 N · 失败 N`，进度条 = 完成数 / 总数。主按钮始终是「开始下载」，可反复追加任务。右侧「清除已完成」只在存在终态任务时出现，点击后把 done/failed/cancelled 行从列表与 `stats()` 里一并摘掉（`forget`），汇总归零、列表整块隐藏。

**约束**：任务行只在 `_drain()`（主线程）里改文字和进度，工作线程一律走队列。

## 6. 输入解析（GUI-006）

- 链接框允许多行，每行一个；忽略空行、`#` 开头注释行、含 `…` 的占位符行
- 额外镜像框逗号分隔；以 `/` 结尾的前缀拼在**第一个** URL 前
- 提交前必须把当前滑杆值写回 `config` 并 `save_cfg`，保证异常退出也不丢设置

## 7. 已落地

| 编号 | 内容 |
|---|---|
| GUI-007 | 剪贴板监听：`after(900)` 轮询，输入框为空且剪贴板是 http(s) 直链时自动填入并在日志提示；同一链接只提一次（`_clip_seen`）。**未采用**「弹提示条 + 忽略按钮」的原设计——单页极简布局里多一条提示条反而更吵 |
| GUI-008 | 任务列表：`TaskRow`（标题 + `ThinBar` + 状态 + 行内按钮）装在 `Canvas + Frame` 里，右侧 `SlimScroll`；最多露 3 行，超出滚动 |
| GUI-009 | 高级面板新增「限速」「并发任务」「代理」三项 |
| GUI-010 | 清除已完成：底部文本按钮，仅当存在终态任务时显示；逐行 `DownloadQueue.forget` + `destroy`，列表空时整块隐藏，汇总随之归零 |

**已知开销**：`SlimScroll` 若不显式设 `height`，Canvas 默认高度会把窗口顶高约 400px —— 已用 `configure(height=S(1))` 压掉。新增滚动容器时务必照做。
