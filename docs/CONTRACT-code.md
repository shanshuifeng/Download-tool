# CONTRACT · 代码规约

契约版本 v1.0 ｜ 适用：`downloader.py`、`dl.py`、`gui.pyw`、`build_and_sign.py`

目的是让三个文件读起来像一个人写的。每条都有明确判据，不做风格争论。

## 1. 依赖（CODE-001）

**只用标准库。** 任何 `pip install` 才能跑的东西都不许进源码。

```contract
{
  "checks": [
    {"type": "stdlib_only",
     "files": ["downloader.py", "netio.py", "taskqueue.py", "dl.py", "gui.pyw"]}
  ]
}
```

例外：`build_and_sign.py` 不受此限（构建期允许 shell 出去装 PyInstaller），但也不许 import 第三方包。

理由：11MB 单 exe、插 U 盘就能跑是这个项目的立身之本。破一次就回不去了。

## 2. 分层（CODE-002）

```
gui.pyw ──┬──> downloader.py ──> netio.py
          └──> taskqueue.py ───> downloader.py
dl.py ────────> downloader.py
```

- `netio.py` 是传输层（UA、opener、代理、SOCKS5、`_request`），**不得反向依赖** `downloader`
- `taskqueue.py` 是多任务调度，只依赖 `downloader`，**不得被 downloader 依赖**（否则循环导入）
- `downloader.py` 只允许依赖 `netio`，不得依赖 `gui.pyw` / `dl.py` / `taskqueue.py`
- `gui.pyw` / `dl.py` 不得互相 import
- 三者都不得 import `build_and_sign.py`（构建脚本是终端节点）
- 引擎层不得出现 `tkinter`；界面层不得出现网络调用

## 3. 规模（CODE-003）

```contract
{
  "checks": [
    {"type": "max_lines",
     "limits": {"downloader.py": 900, "netio.py": 260, "taskqueue.py": 220,
                "dl.py": 400, "gui.pyw": 1100}}
  ]
}
```

超限说明该拆了。这轮 `downloader.py` 到 990 行时就是按这条把传输层拆成了 `netio.py`。后续若界面层超限，拆出 `widgets.py`（自绘控件），不要再往 `gui.pyw` 堆。

## 4. 命名（CODE-004）

| 对象 | 规则 | 例 |
|---|---|---|
| 模块级常量 | 全大写 | `MIN_CHUNK`、`DEFAULTS` |
| 类 | PascalCase | `DownloadTask`、`SlimScroll` |
| 函数/方法 | snake_case | `rank_mirrors`、`_download_chunked` |
| 私有成员 | 单下划线前缀 | `_worker`、`_lock` |
| 布尔变量 | `is_` / `has_` / 形容词 | `ranges`、`advanced_open` |

禁止：拼音命名、无意义缩写（`d`、`tmp2`）、同一概念两个名字（镜像统一叫 `mirror`，不混用 `source`）。

## 5. 错误处理（CODE-005）

- **对外只抛 `DownloadError`**，消息必须是能指导用户行动的中文；底层异常要么被翻译，要么被包装，不得直接冒泡
- `except Exception: pass` 仅允许出现在**无关紧要的清理路径**（删临时文件、写配置、图标加载、DPI 设置），且必须加注释说明为什么可以吞
- 捕获后必须做出区分：永久错误（4xx）不重试，暂时错误（超时/重置/5xx）退避重试
- 禁止裸露的 `except:`（不带异常类型）

## 6. 并发（CODE-006）

| 规则 | 判据 |
|---|---|
| 共享可变状态必须过锁 | 新增一个被多线程写的属性，就必须在同一行附近出现 `with self._lock` |
| 取消用 `threading.Event` | 不用布尔标志位，`is_set()` 可跨线程安全读 |
| 线程一律 `daemon=True` | 主线程退出不得被阻塞 |
| 不在持锁期间做 IO | 锁只包住计数与列表追加，不包 `write()` / `read()` |

## 7. 注释（CODE-007）

- 中文，解释**为什么**，不解释**是什么**
- 模块头必须写：这是什么、设计参考了谁、边界在哪
- 参数与返回值的坑（例如「0 表示关闭」）必须写在 docstring 里
- 不写 `# 循环遍历` 这类废话注释
- 关键实现点用 `# @contract CORE-00X` 锚定契约编号

## 8. 日志文案（CODE-008）

| 级别 | 用途 | 格式 |
|---|---|---|
| `ok` | 成功终态 | `完成：<路径>` |
| `info` | 过程播报 | 陈述句，无感叹号 |
| `warn` | 可恢复问题 | `分片3 第2次失败（…），换源重试` |
| `error` | 致命 | 面向用户的原因 + 建议 |

数字必须经 `human()` 格式化，不得直接 `str(int)` 输出字节数。进度日志不得带 `\r`（GUI 里会串行）。

## 9. 编码与文件（CODE-009）

- 全部 UTF-8，首行 `#!/usr/bin/env python3` + `# -*- coding: utf-8 -*-`（`gui.pyw` 保留 `.pyw` 后缀）
- 缩进 4 空格，行宽 ≤ 100
- 每文件末尾一个空行
- 不用 `from x import *`

## 11. 需求与测试的绑定（CODE-010）

「已完成」不是靠嘴说的。`REQ.md` 里每条标了「已完成」的需求，都必须在文末的对照表里挂一个真实存在的测试函数，**并且那个测试的 docstring 里要写明对应的 `REQ-0xx`**——两边都写，校验器交叉核对。

```contract
{
  "checks": [
    {"type": "req_tests", "req": "REQ.md",
     "tests": ["tests/test_engine.py", "tests/test_gui.py",
               "tests/test_contract.py"]}
  ]
}
```

为什么要求双向声明：只校验「函数名存在」的话，把 REQ-011 挂到任意一个测试上都能过，防不住「挂错」。加上测试体内的 REQ 标记，至少能挡住复制粘贴挂错行。

新增需求时：先写测试（docstring 带 REQ 编号）→ 再挂对照表 → 最后改状态。反过来做就会出现「标了完成但根本不能用」——本项目在 REQ-011 上踩过一次。

**校验器自身的规则**：未知检查类型一律判失败，`SKIP` 也计入失败。静默跳过的检查等于没有检查。

## 12. 提交前检查清单

改完代码，按顺序过一遍：

1. `python docs/verify_contract.py` 全绿
2. 三个入口都能起来：`python src/downloader.py --help`、`python src/dl.py --schema`、双击 `src/gui.pyw`
3. 小文件（<2MB）走单线程、大文件走分段，两条路径都跑通
4. 中途 `Ctrl+C` / 关窗口，`.parts` 保留且能续传
5. 改过界面的，125% 与 150% 缩放下各看一遍
6. 改过打包相关，跑 `build_and_sign.py --no-sign` 确认能出 exe
