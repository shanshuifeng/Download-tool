# 实现文档

本目录是**实现层面的事实来源**。根目录 `README.md` 面向使用者，这里面向维护者。

## 文档地图

| 想了解 | 读这份 |
|---|---|
| 需求从哪来、验收标准是什么 | `REQ.md`（`REQ-`） |
| 下载引擎的公开符号、线程模型、回调与异常 | `CONTRACT-engine.md`（`CORE-`） |
| 命令行参数、事件流、退出码、输出通道分工 | `CONTRACT-cli.md`（`CLI-`） |
| 界面控件接口、Tk 线程规则、队列消息、状态机 | `CONTRACT-gui.md`（`GUI-`） |
| `config.json` / `meta.json` / `job.json` 与磁盘布局 | `CONTRACT-data.md`（`DATA-`） |
| 依赖、分层、规模、命名、并发、日志、编码等统一规约 | `CONTRACT-code.md`（`CODE-`） |
| 已修复缺陷的现象、根因与验证方式 | `BUGS.md`（`BUG-`） |

代码组织：`downloader.py` 是下载引擎（探测、分片、调度、合并）；`dl.py` 是唯一的命令行入口，并持有机器可读的接口描述；`gui.pyw` 是界面与总入口；`netio.py` 负责传输、代理与重试；`httpinfo.py` 判定 HTTP 语义（分段能力、永久错误）；`mirrors.py` 管理镜像；`taskqueue.py` 调度多任务；`resume.py` 与 `diskutil.py` 分别处理续传指纹与落盘预检；`naming.py` 规整文件名。

## 一致性如何保障

文档与代码通过三层机制保持同步。

**一、机器可读的契约块。** 每份 `CONTRACT-*.md` 含若干 ```contract 围栏块（JSON）。它们既是规格，也是校验器的输入。接口变更应从这里开始。

**二、可执行校验。**

```bash
python docs/verify_contract.py           # 25 项检查
python docs/verify_contract.py -v        # 逐项细节
python docs/verify_contract.py --json    # 机器可读
```

发现漂移即以非零退出码结束。当前 25 项检查分布如下：

| 关注点 | 检查 |
|---|---|
| 依赖与分层 | `stdlib_only`、`forbidden_imports`、`imports_from`×2、`no_private_access` |
| 公开接口 | `public_symbols`×2、`signature`、`dict_keys`、`const`×2、`const_used`、`literal_dict` |
| 命令行契约 | `schema_vs_argparse`、`schema_version`、`schema_defaults`、`exit_codes`、`event_fields` |
| 行为可追溯 | `call_site`×2、`error_table`、`anchors` |
| 工程约束 | `max_lines`、`req_tests`、`bug_tests` |

**三、代码锚点。** 关键实现点用注释绑定契约编号：

```python
self.threads = max(1, min(int(threads), 64))   # @contract CORE-004
```

锚点只做单向校验：代码引用了文档中不存在的编号即报错。反向（每个编号都必须有锚点）不作要求——部分条目属于文档级约定，强制标注只会产生无意义的注释。

## 变更协议

1. 涉及接口形状的变更（函数签名、参数、事件字段、文件格式、退出码），**先改契约文档**
2. 跑校验器，确认结果由预期失败转为通过
3. 同步 `REQ.md` 中对应条目的状态；新增缺陷则登记到 `BUGS.md`
4. 纯内部重构不涉及契约；若锚点编号变化需同步

**测试先行**：新增或修复行为时，先写用例并在函数体内标注需求或缺陷编号。校验器会双向核对——标为已完成的条目必须有对应用例，用例引用的编号也必须在文档中存在。

## 兼容性约束

以下内容对已发布的调用方构成契约，只能新增，不能改变语义：

- `--json` 的事件字段与退出码
- `config.json` 的既有键：新增键必须带默认值，缺省时行为与旧版本一致
- `DownloadTask` 的既有参数：新增参数只能追加在末尾并带默认值
- `meta.json` 的既有字段：新增字段缺失时按旧逻辑回退
- `--schema` 输出的结构：顶层键集合受结构指纹约束，变动必须同时递增 `SCHEMA.version`

## 提交前检查

```bash
python docs/verify_contract.py
python -m unittest discover -s tests
```

两项都必须全绿，且**不允许出现 SKIP**——静默跳过的检查等同于没有检查。
