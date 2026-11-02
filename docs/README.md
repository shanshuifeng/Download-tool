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

## 发布

```bash
git tag -a v1.3.0 -m "v1.3.0"
git push origin master
git push origin v1.3.0
```

推送标签触发 `.github/workflows/release.yml`：按 tag 渲染版本资源 → 打包 → 收集产物 → 发布 Release。版本号因此只有 tag 一个来源，不需要改任何文件。CI 亦在每次推送与合并请求时执行契约校验与测试。

产物在 Windows runner 上构建，两条经验写在代码里，改动发布链路时不要退回：

- **资产名必须是 ASCII**。带中文的文件名会在上传环节被代码页丢弃（`下载工具_便携版.zip` 曾变成 `_.zip`，页面显示的却仍是中文——那是 `label`，不是真实文件名）。
- **收集产物用 Python 而非 shell**。同名逻辑经 shell 时会在解析阶段就被破坏，且 Windows 控制台默认非 UTF-8，打印中文会抛异常让步骤失败。

### 代码签名

当前不签名。这不是省事，是权衡后的结论：

- **自签名证书对公开分发没有帮助。** SmartScreen 仍会拦截，除非用户手动把证书导入受信任根——没有普通用户会这么做。微软的分类里它属于「Dev/testing only, or enterprise with managed certificate trust」。
- **商业证书无法直接用于 CI。** 按 CA/B 论坛要求，2023 年起代码签名私钥必须存放在硬件或云 HSM，不能再以 `.pfx` 形式放进仓库或 Secrets。要在 CI 落地，需配套云签名服务。
- **EV 不再有特殊待遇。** 2024 年起与 OV 在 SmartScreen 上无差别，都需要积累声誉。

若将来要真实签名，可选路径：

| 方案 | 成本 | 说明 |
|---|---|---|
| OV 证书 | 约 $150–300/年 | 全球可申请，需身份审核；CI 需配套云签名服务 |
| EV 证书 | 约 $400+/年 | 与 OV 在 SmartScreen 上无差别 |
| SignPath Foundation | 免费（开源项目） | 基金会持证并代签，发布者显示为 SignPath Foundation，每次发版需人工批准 |
| Azure Artifact Signing | 约 $10/月 | 个人开发者仅限美国与加拿大 |
| Microsoft Store (MSIX) | 免费 | 商店代签，无 SmartScreen 提示，但需按 MSIX 打包并过审 |

在此之前，完整性由 SHA-256 保障：GitHub 为每个资产计算摘要，用户可用 `certutil -hashfile` 核对。
