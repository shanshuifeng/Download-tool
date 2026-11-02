# CONTRACT · 代码规约

契约版本 v1.0 ｜ 适用：`downloader.py`、`dl.py`、`gui.pyw`、`build_and_sign.py`

目的是让三个文件读起来像一个人写的。每条都有明确判据，不做风格争论。

## 1. 依赖（CODE-001）

**只用标准库。** 任何 `pip install` 才能跑的东西都不许进源码。

```contract
{
  "checks": [
    {"type": "stdlib_only",
     "files": ["downloader.py", "netio.py", "taskqueue.py", "dl.py", "gui.pyw",
               "diskutil.py", "resume.py", "mirrors.py", "naming.py",
               "httpinfo.py"]}
  ]
}
```

例外：`build_and_sign.py` 不受此限（构建期允许 shell 出去装 PyInstaller），但也不许 import 第三方包。

理由：单文件、免安装、可置于移动介质是本项目的交付前提，该形态一旦破坏难以恢复。

## 2. 分层（CODE-002）

```
gui.pyw ──┬──> dl.py ───────────> downloader.py ──┬──> httpinfo.py ──┬──> netio.py
          │                                        │   └──> naming.py
          ├──> downloader.py ──────────────────────┼──> netio.py
          │                                        ├──> naming.py
          │                                        ├──> diskutil.py
          │                                        ├──> resume.py
          │                                        └──> mirrors.py
          └──> taskqueue.py ───> downloader.py
```

- `netio.py` 是传输层（UA、opener、代理、SOCKS5、`_request`），**不得反向依赖** `downloader`
- `httpinfo.py`（HTTP 语义判定与探测）、`naming.py`（文件名规整）、`diskutil.py`（落盘预检）、`resume.py`（续传指纹）与 `mirrors.py`（加速源策略）是叶子模块，**不得反向依赖**。其中 `httpinfo` 额外依赖 `netio` 与 `naming`，`naming` 被 `httpinfo` 与 `downloader` 共用
- `downloader` 重新导出 `mirrors` 的公开符号（`build_mirror_urls` / `expand_mirror_urls` / `is_github_release`）与 `httpinfo.probe`，以保持 CORE-001 的公开面不变。**`mirrors.GITHUB_MIRRORS` 是数据表，不再经引擎再导出**（BUG-41）：需要它的人直接 `import mirrors`
- `taskqueue.py` 是多任务调度，只依赖 `downloader`，**不得被 downloader 依赖**（否则循环导入）
- `downloader.py` 只允许依赖 `netio` / `diskutil` / `resume` / `mirrors` / `naming` / `httpinfo` 这六个下层模块，不得依赖 `gui.pyw` / `dl.py` / `taskqueue.py`
- **`dl.py` 是唯一的命令行实现**；`downloader.py` 不得出现 `argparse`，也不得提供 `main()`（CLI-010）
- `gui.pyw` 是唯一入口：`main()` 里按 `sys.argv` 分发，有参数才 import `dl`（单向，不得反向）
- 三者都不得 import `build_and_sign.py`（构建脚本是终端节点）
- 引擎层不得出现 `tkinter`；界面层不得出现网络调用

### 2.1 不得越界访问私有符号（CODE-012）

CORE-001 规定「以下划线开头的符号视为私有」。这条必须**可执行**，不能只写在文档里：

- **同模块豁免**：属性名只出现在本模块的私有符号集合里 → 放行（对象访问自己模块的内部实现是正常的）
- **`self` 豁免**：`self._x` 一律放行（对象访问自己的私有成员是正常的）
- **显式白名单**：`allow` 支持 `"模块名.属性名"` 形式的逐条豁免
- **按文件启用**：只在显式列出的 `files` 上启用，不做全库自动扫描，避免将来新增模块时突然报红

私有符号集合的定义：某模块的模块级下划线名字，**加上**其类中所有 `self._xxx` 属性名。

```contract
{
  "checks": [
    {"type": "no_private_access",
     "files": ["taskqueue.py", "dl.py", "gui.pyw", "downloader.py"],
     "modules": ["downloader", "netio", "taskqueue", "dl", "gui",
                 "mirrors", "naming", "httpinfo", "resume", "diskutil"],
     "allow": []}
  ]
}
```

## 3. 规模（CODE-003）

```contract
{
  "checks": [
    {"type": "max_lines",
     "limits": {"downloader.py": 900, "netio.py": 260, "taskqueue.py": 220,
                "dl.py": 400, "gui.pyw": 1100, "diskutil.py": 160,
                "resume.py": 90, "mirrors.py": 80, "naming.py": 100,
                "httpinfo.py": 160, "docs/verify_contract.py": 1100}}
  ]
}
```

超限说明该拆了。这轮 `downloader.py` 到 990 行时就是按这条把传输层拆成了 `netio.py`。后续若界面层超限，拆出 `widgets.py`（自绘控件），不要再往 `gui.pyw` 堆。

### 3.1 规模上限的语义（CODE-011）

`max_lines` 不只是「行数超了才报红」。三条判定同时成立：

| 判定 | 失败信息 |
|---|---|
| `limits` 中每个键都必须 `resolve()` 到一个**存在的文件** | 「契约声明了上限但文件不存在」 |
| `src/` 下每个 `.py` / `.pyw` 文件都必须在 `limits` 中有对应条目（按 `resolve()` 后的绝对路径比对） | 「该模块未定义规模上限」 |
| 行数 > 上限 | 「文件 N 行 > 上限 M」 |

第二条是本条存在的理由：**新增模块漏登记上限**在旧语义下完全无人察觉——旧校验器只遍历 `limits` 里的键，没登记的文件等于不受任何约束。键写 `"downloader.py"` 与 `"src/downloader.py"` 命中同一个文件。

`docs/` 下的文件不参与「必须登记」的判定（文档不是源码），但可以自愿登记上限。

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
- 不写复述代码含义的注释（如 `# 循环遍历`）
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

## 10. 需求与测试的绑定（CODE-010）

「已完成」不是靠嘴说的。`REQ.md` 里每条标了「已完成」的需求，都必须在文末的对照表里挂一个真实存在的测试函数，**并且那个测试的 docstring 里要写明对应的 `REQ-0xx`**——两边都写，校验器交叉核对。

```contract
{
  "checks": [
    {"type": "req_tests", "req": "REQ.md",
     "tests": ["tests/test_engine.py", "tests/test_gui.py",
               "tests/test_contract.py", "tests/test_bugs.py"]},
    {"type": "bug_tests", "bugs": "BUGS.md",
     "tests": ["tests/test_engine.py", "tests/test_gui.py",
               "tests/test_contract.py", "tests/test_bugs.py"]}
  ]
}
```

为什么要求双向声明：只校验「函数名存在」，把 REQ-011 挂到任意一个测试上都能通过，无法识别挂错；测试体内标注 REQ 编号后可识别复制粘贴导致的错误挂载。

### 10.1 绑定的有效性（CODE-014）

「挂上了」不等于「挂对了」。三条判定同时成立：

| 判定 | 要求 |
|---|---|
| 标记位置 | REQ 编号必须出现在测试的 **docstring** 里。写在注释里不算——注释不参与文档生成，下次改动极易被删掉 |
| 用例有效 | 测试体至少含一条断言调用（`ast.Call` 且被调者 `Attribute.attr` 以 `assert` 开头），且不得整体只有 `self.skipTest(...)` |
| 多需求共用 | 一条测试可映射多条需求（REQ-008 与 REQ-016 共用 `test_chunk_count_independent_of_threads`），此时 docstring 必须**同时**写明全部编号 |

新增需求时：先写测试（docstring 带 REQ 编号）→ 再挂对照表 → 最后改状态。顺序颠倒会产生「标记完成但实际不可用」的结果，本项目在 REQ-011 上曾出现该情况。

**校验器自身的规则**：未知检查类型一律判失败，`SKIP` 也计入失败。静默跳过的检查等于没有检查。

## 11. 校验器自身的检查项（CODE-011 ~ CODE-015）

校验器是契约的执行者。它自己有盲区：只做取值比对、不做存在性与语义比对，就会漏掉「文档说 A、代码是 B」的一整类漂移。以下五条把这类盲区堵上。

| 编号 | 检查项 | 类型 | 位置 |
|---|---|---|---|
| CODE-011 | 规模上限的语义（未定义即失败） | `max_lines` | §3.1 |
| CODE-012 | 不得越界访问私有符号 | `no_private_access` | §2.1 |
| CODE-013 | 契约行为落地（调用点必须存在） | `call_site` | `CONTRACT-engine.md` §10.1 |
| CODE-014 | 需求↔测试绑定的有效性 | `req_tests` | §10.1 |
| CODE-015 | 常量必须真被使用 | `const_used` | `CONTRACT-engine.md` §3 |

CODE-015 的判定式：常量名必须在声明范围内出现一次**读取**（AST 中 `ast.Name` 且 `ctx=Load`）。模块级赋值处于 `Store` 上下文，天然不计入，因此「只定义不读取」不会被误判为已使用。边界情况 `X = X + 1` 这类自引用：定义行的 `X` 既是 Store 也是 Load，实现时按「与顶层定义语句同行则不计」排除。

**匹配必须是 AST 语境，不能用裸文本 grep**：文本匹配会让常量**定义行自身**命中，恒为「已使用」，检查等于空转——这正是 `check_anchors` 空转过一轮的同类陷阱，不能重犯。

`const_used` 的 `aliases` 字段是为将来预留的第二级（构造参数别名）匹配，本轮**留空**。它会遮蔽第一级：有人把默认值改成硬编码时，第一级正确判「未使用」，第二级却因别名仍被读取而判「已使用」，漏过。低精度规则吞掉高精度规则的判定是净负收益。

### 11.1 SCHEMA 侧的两条检查（CODE-016 / CODE-017）

机器可读接口是最容易「同一事实写两处」的地方，因此另立两条：

| 编号 | 检查项 | 类型 | 位置 |
|---|---|---|---|
| CODE-016 | 默认值只写一处 | `schema_defaults` | `CONTRACT-cli.md` §5.2 |
| CODE-017 | `SCHEMA` 保持纯字面量 | `literal_dict` | `CONTRACT-cli.md` §5.3 |

CODE-016 守的是「文案的『默认 N』句式与 `SCHEMA["defaults"]` 重复」——判据是**句式**而非数字扫描，`--chunk` 的「0=自动」（哨兵语义）与 `--slow` 的「0=关闭」（阈值语义）都豁免。**事实源是 `defaults` 与 `args` 两者**：参数名从 `args` 归一化反查得到，契约里的 `map` 只是**被验证的显式声明**——它把某个默认值声明到不对应的参数上时同样报红（否则手工维护的白名单一写错，那条默认值就整体逃逸检查，BUG-43 / BUG-45）。四个方向的判据见 `CONTRACT-cli.md` §5.2。反过来不查 `args`：十个参数本就没有默认值。

CODE-017 守的是「`SCHEMA` 不得被改成派生表达式」——一旦变成 f-string 渲染或 `dict(...)` 调用，AST 静态提取就失效，`chk_dict_keys` 与 `schema_defaults` 会**静默空转**。作用域只限 `SCHEMA` 这一个常量：`dl.py` 里的 `DEFAULTS = dict(SCHEMA["defaults"])` 不是字面量，而它恰恰是「运行期以 schema 为唯一来源」那条关系，扫到它就误报了。

### 11.2 接口指纹的口径（CLI-011）

`schema_version` 检查靠结构指纹判断「接口内容变没变」。本节只写**规则**，具体声明（当前版本号、当前指纹、上一版指纹）在 `CONTRACT-cli.md` §5.1 —— 两处各写一份声明，就制造了本项目要消灭的那类漂移。

**口径原文**：

```
指纹 payload = SCHEMA 去掉 "version" 键后的全部键；
序列化方式 = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")；
哈希算法 = sha256，取十六进制小写。
```

**为什么不用「显式枚举 payload 键集」**　枚举会把将来新增的顶层键漏在检测之外——加一个键不改变指纹，正是这个检查要防的漂移本身。`defaults` 就是这样漏过一次：它一度不在枚举里，于是「默认值被悄悄改掉」无人察觉。

**四级判定**（摘要，完整表述见 `CONTRACT-cli.md` §5.1）：

| # | 场景 | 判据 |
|---|---|---|
| 1 | 内容漂移 | 实算指纹 ≠ 声明指纹 |
| 2 | 版本号漂移 | `SCHEMA["version"]` ≠ 声明 version |
| 3 | 版本降级 | `version < previous.version` |
| 4 | 递增与内容变化不同步 | `(version > previous.version)` 与 `(fingerprint != previous.fingerprint)` **必须同真同假** |

规则 3 不可省：`fingerprint != previous.fingerprint` 只能发现「内容变了」，发现不了「内容变了但版本号没跟上」——而后者正是消费方误判兼容性的那条路径。

**报红信息里的 payload 键集必须由实际 payload 派生，不得硬编码**　这条看着只是多打几个字，实际救过一次误判：若报红信息只说「指纹不符」而不说键集，维护者会以为「内容变了」，而实际上可能是「口径变了」。**诊断信息本身也是契约的一部分，必须与实现同源**——否则它会在说谎，把排查方向直接带偏。形态校验失败时，报红信息同样要带上声明指纹与实算指纹（或说明「无法比对指纹」的原因）。

## 12. 提交前检查清单

改完代码，按顺序过一遍：

1. `python docs/verify_contract.py` 全绿
2. 两个入口都能起来：`python src/dl.py --schema`、双击 `src/gui.pyw`（`python src/downloader.py` 应打印迁移提示并非零退出，见 CLI-010）
3. 小文件（<2MB）走单线程、大文件走分段，两条路径都跑通
4. 中途 `Ctrl+C` / 关窗口，`.parts` 保留且能续传
5. 改过界面的，125% 与 150% 缩放下各看一遍
6. 改过打包相关，跑 `build_and_sign.py --no-sign` 确认能出 exe

---

作者：shanshuifeng ｜ 项目地址：https://github.com/shanshuifeng/Download-tool ｜ 许可：Apache-2.0（见 `LICENSE`）
