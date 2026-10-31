# 缺陷报告

扫描日期 2026-10-31 ｜ 修复日期 2026-10-31 ｜ 覆盖 3,700 行源码 + 文档 + 构建流程

18 条（原报告 14 条 + 核实新增 4 条）已全部收口：13 条改代码、3 条前一轮已修、1 条改契约、1 条改判。
每条都标注了验证方式；可执行测试在 `tests/test_bugs.py`，函数体内写明编号。
执行顺序与边线见 `FIXPLAN.md`。

严重度定义：**P0** 功能不可用或产出错误文件；**P1** 与宣称行为不符；**P2** 体验/维护成本；**P3** 风格细节。

## 总览

| 编号 | 标题 | 严重度 | 状态 | 验证方式 |
|---|---|---|---|---|
| BUG-01 | 0 字节文件完全无法下载 | P0 | 已修 | 测试 `test_bug01_zero_byte` |
| BUG-02 | 任务清空后底部汇总不复位 | P0 | 已修 | 测试 `test_bug02_forget_resets_stats` / `test_bug02_clear_finished` |
| BUG-03 | 构建流程不产出便携版 zip | P0 | 已修（pack_portable） | 人工：检查 `build/便携版/` |
| BUG-04 | 契约 CORE-016 描述与实现不符 | P1 | 已修（契约改写） | 契约 `CORE-016` |
| BUG-05 | 章节编号断裂（缺 10） | P1 | 已修 | 静态：章节 1–11 连续 |
| BUG-06 | FAT32 U 盘 >4GB 必然失败，且下载完才暴露 | P1 | 已修 | 测试 `test_bug06_fat32_reject` / `test_bug06_space_precheck` |
| BUG-07 | 镜像不强制哈希，供应链风险 | P1 | 已修（文档 + 运行时 warn） | 测试 `test_bug07_mirror_warns_without_hash` |
| BUG-08 | 超长路径失败且报错误导 | P2 | 已修 | 测试 `test_bug08_long_path` |
| BUG-09 | `dl.py` 重复哈希整个文件 | P2 | 已修 | 测试 `test_bug09_hash_single_pass` / `test_bug09_done_verified_for_md5` |
| BUG-10 | 无剩余空间预检 | P2 | 已修 | 测试 `test_bug10_enospc_fast_fail` / `test_bug10_enospc_single` |
| BUG-11 | REQ 依赖图缺 016–020 | P2 | 已修 | 静态：依赖图覆盖 001–020 |
| BUG-12 | `downloader.py` 残留未使用导入 | P2 | 已修 | 静态：`test_source_no_dead_imports` |
| BUG-13 | 测速失败仍参与加权分配 | P3 | 不成立（已改判） | 见正文反例 |
| BUG-14 | 2 行超出 100 列 | P3 | 已修 | 静态：`test_source_line_width` |
| BUG-15 | 单线程续传不校验指纹，静默产出坏文件 | P0 | 已修 | 测试 `test_bug15_single_resume_detects_change` |
| BUG-16 | `add()` 与 `_pump()` 竞态，任务永久卡 running | P1 | 已修 | 测试 `test_bug16_add_pump_race` |
| BUG-17 | 测速对忽略 Range 的源无界读取 | P1 | 已修 | 测试 `test_bug17_measure_bounded` |
| BUG-18 | 校验器锚点检查在目录重组后空转 | P2 | 已修 | 静态：`test_anchor_check_scans_src` |

---

## BUG-01 · 0 字节文件完全无法下载（P0）

**现象**：以下载服务返回 `Content-Length: 0` 的合法文件时报「所有下载源都不可用」。

**复现**：

```
空文件下载失败 → 所有下载源都不可用
```

**根因**：`downloader.probe()` 用 `if not size:` 判定探测失败，把 `0` 和 `None` 混为一谈。

**建议**：改为 `if size is None:`；同时 `_measure_mirror` 的 `if not info["size"]` 一并改。空文件仍要走单线程路径（`size > MIN_CHUNK*2` 为假，天然正确）。

**影响**：GitHub 仓库中 `.gitkeep`、空的 `__init__.py`、空配置文件都属此类。

---

## BUG-02 · 任务清空后底部汇总不复位（P0）

**现象**：删光任务行后，底部仍显示「完成 2」、进度条停在 100%。

**复现**：

```
移除前底部: 完成 2 | 进度: 100.0
移除后行数: 0 | 列表显示: False
移除后底部: 完成 2 | 统计: {'total': 2, 'done': 2, ...}
```

**根因**：`DownloadQueue._state` 只写不删，`stats()` 统计全部历史任务；GUI 的「移除行」只删了 `rows`，没有通知队列。

**建议**：新增 `DownloadQueue.forget(tid)`，`_task_action` 删行时调用；或者 `stats()` 只统计 `_rows` 里存在的任务。修完顺带让 `_state` 不再无限增长。

**影响**：视觉上「清不干净」，且与契约里「长会话不涨内存」的说法自相矛盾。

---

## BUG-03 · 构建流程不产出便携版 zip（P0）

**现象**：`build_and_sign.py` 只部署 exe，从不生成 `下载工具_便携版.zip`；但 README 承诺桌面有该文件。

**证据**：

```
$ grep -n "zip" build_and_sign.py
→ 没有任何 zip 相关代码
```

**根因**：zip 一直靠手工打包，从未进入构建脚本。

**建议**：构建脚本增加 `pack_portable()`：把两份 exe + README + 使用说明 + job 示例复制到 `build/便携版/`，再 `zipfile` 打成 `下载工具_便携版.zip`，同时投放一份到桌面。

**影响**：每次发版后 zip 会静默过期（内含旧 exe），没有任何机制能发现。

---

## BUG-04 · 契约 CORE-016 描述与实现不符（P1）

**现象**：`CONTRACT-engine.md` 写「任务进入终态后从 `_tasks` 移除，长会话不涨内存」。实际 `_tasks` 确实移除，但 `_state`、`_path_lock` 的条目永不释放。

**建议**：修 BUG-02 时一并补 `forget()`，或把描述改成「`_tasks` 释放，`_state` 保留用于查询」。

---

## BUG-05 · 章节编号断裂（P1）

**现象**：`CONTRACT-code.md` 章节为 1–9、11、12，缺第 10 章。

**建议**：重新编号为 1–11，或把「提交前检查清单」编为 10 并把需求绑定编为 11。

---

## BUG-06 · FAT32 U 盘 >4GB 必然失败，且下载完才暴露（P1）

**现象**：工具的定位是「丢 U 盘随身用」，但 FAT32 单文件上限 4GB−1。现在的流程是先把几 G 分片下完，合并时 `truncate(size)` 才失败。

**根因**：无文件系统类型与剩余空间预检，`MAX_FILE_SIZE=200GB` 只挡荒谬值。

**建议**：`run()` 在确定 `size` 后、开始下载前检查目标盘：`shutil.disk_usage(dir).free < size * 1.05` 直接报「空间不足」；FAT32 判断可用 `ctypes.GetVolumeInformationW` 取文件系统名，命中 FAT32 且 `size >= 4GB` 时提前拒绝并提示「请换 exFAT/NTFS 或改存本地」。

**影响**：用户等几十分钟才被告知不行，且错误是底层 `OSError`。

---

## BUG-07 · 镜像不强制哈希（P1，仅文档警示）

**现象**：内置三个第三方 GitHub 代理，未提供哈希时只核对大小。镜像可以返回「大小正确、内容恶意」的文件，工具会报「完成」。

**建议**：无法在代码层根治。在 README「注意」区与 GUI「参数说明」里明确写：**经镜像下载的二进制必须自带哈希**。不在参数说明里藏。

---

## BUG-08 · 超长路径失败且报错误导（P2）

**现象**：

```
路径长度: 332
→ 写入失败: FileNotFoundError [Errno 2] No such file or directory
```

目录明明存在。`_safe_name` 允许 120 字符文件名，叠加深目录即超 260。

**建议**：创建输出文件前检查 `len(abspath) + 32 > 255` 就报「保存路径过长，请换浅一点的目录」；或在 Windows 上统一给绝对路径加 `\\?\` 前缀。

---

## BUG-09 · `dl.py` 重复哈希整个文件（P2）

**现象**：传入 `--sha256` 时，`_verify()` 已完整读过一遍文件，`main()` 里 `if args.hash or expected:` 又用 sha256 再读一遍。2GB 文件多读 2GB。

**建议**：`DownloadTask` 把校验结果挂到 `self.actual_hash`，`dl.py` 优先复用；只有 `--hash` 且未校验时才单独算。

**顺带修正**：期望值填 md5/sha1 时，`done.verified` 曾用 sha256 实际值去比 md5 期望值，必然报 `false`。
现在改为「能走到 done 就说明 `_verify` 已通过」，不再重复比较。

---

## BUG-10 · 无剩余空间预检（P2）

**现象**：磁盘写满后是逐个分片失败、退避重试 30 秒，观感像卡死。

**建议**：与 BUG-06 合并处理，下载前一次性检查；写入过程中捕获 `OSError errno ENOSPC` 直接中止并给出明确提示，不走重试。

---

## BUG-11 · REQ 依赖图缺 016–020（P2）

**现象**：`REQ.md` 的依赖关系图只画到 REQ-015。

**建议**：补 016（依赖 003/004）、017–020（独立或依赖 001）。

---

## BUG-12 · `downloader.py` 残留未使用导入（P2）

```
downloader.py: ['deque', 'UA']      # 核实后：死的是这两个
```

`deque` 随队列拆到 `taskqueue.py` 后遗留；`UA` 在错误翻译搬走后也失去引用。
`_opener` 是给测试保留的再导出，已经带 `# noqa: F401` 注释，不属于残留——
原报告把它一并算作死导入，属于误判。

**修法**：删掉 `deque` 与 `UA`；`_opener` 保留并注明用途。行宽与死导入都加进
`tests/test_contract.py` 做静态守卫，避免再靠人眼查。

---

## BUG-13 · 测速失败仍参与加权分配（P3，不成立）

**核实结论**：现象描述不成立，建议的修法也是空操作。

**反例**：穷举 `n=1..40` 与 10 组含 0 权重向量的组合（`[0,1]`、`[1,0]`、`[0,0,5]`、`[3,0,1]` 等），
0 权重源被分配到分片的次数为 **0**。

**原因**：`_distribute` 的配额是 `max(0.0, w) / total * n`，0 权重占比为 0、整取为 0；
最大余数法补位只按小数部分排序，0 权重的小数部分恒为 0，余数只会补给有正小数部分的源。
`total <= 0`（全部为 0）时才退化为轮转，那是刻意的兜底。

**真实存在的小问题（不作缺陷处理）**：测速为 0 的源仍留在 `self.mirrors` 里，
`_worker` 重试轮换 `(mirror_idx + attempt) % n` 会打到它。这是换源兜底的副产品，
一次尝试后即轮走；若强行剔除，会误伤「测速被限流但真能下」的源。

---

## BUG-14 · 2 行超出 100 列（P3）

`downloader.py:138`（102 列）、`gui.pyw:351`（103 列），违反自己定的 `CODE-009`。

---

## BUG-15 · 单线程续传不校验指纹（P0）

**现象**：单线程路径（<2MB 或服务器不支持分段）下到一半中断，远端换成**同长度**的另一份内容后重跑，
产物既不是旧文件也不是新文件，`run()` 正常返回，不产生 `.corrupt`。

**复现**：

```
300KB 源，预置 100KB .part → 远端换成同长度新内容 → run() 返回成功
→ 产物 sha256 既不等于旧内容也不等于新内容
```

**根因**：`_download_single` 只按 `.part` 的文件大小续传，没有任何指纹。
分片路径有 `meta.json` 的 `size/chunks/etag` 三重校验，单线程路径什么都没有——
而《使用说明》承诺「服务器文件变了则重下」。

**建议**：新增 `<out>.part.json`（`size` + `etag` + `url`），开下前写入、成功后删除；
续传前比对，不符即删 `.part` 从头下。服务器不给 ETag 时允许续传但打 `warn`。

**影响**：镜像/发布页替换同名文件后，续传会静默产出哈希不符的文件，且没有任何提示。

---

## BUG-16 · `add()` 与 `_pump()` 竞态（P1）

**现象**：偶发任务永远停在「连接中」，队列再不启动新任务。

**根因**：`add()` 先在锁内把 tid 放进 `_pending`，**释放锁之后**才构造 `DownloadTask`、
再进锁写 `_tasks`。若这期间有任务结束触发 `_pump()`，新 tid 会被取走并起线程，
`_run_one` 里 `self._tasks[tid]` 抛 `KeyError`；线程死掉，`_running[tid]` 永不释放，
状态停在 `running`，并发槽少一个。`concurrent=1` 时队列彻底不动。

**复现**：假任务在 `__init__` 里等待，第一个任务在其构造期间结束 →
`KeyError: 2`、`state_of(2)=running`、`_running=[2]`。

**建议**：先构造 task，再在同一把锁里一次性登记 `_tasks/_state/_pending`；
`_run_one` 改用 `.get(tid)` 并兜底归还并发槽。

---

## BUG-17 · 测速无界读取（P1）

**现象**：源忽略 Range 时，测速阶段把整个响应读进内存。

**根因**：`_measure_mirror` 用 `r.read()` 统计吞吐，没有长度参数。Range 生效时只回 256KB，
不生效时回整个文件。32MB 源实测峰值内存 48MB；GB 级源与多镜像并发会直接打爆进程。

**建议**：改成循环读取，最多读 `256KB`（`BLOCK` 一块一块读），
读满即停，不依赖服务端遵守 Range。

**影响**：下载「不支持分段的大文件」这一本就存在的场景，会在测速阶段 OOM。

---

## BUG-18 · 校验器锚点检查空转（P2）

**现象**：`verify_contract.py -v` 输出「0 处锚点全部有效」——看着全绿，实际一个锚点都没检查。

**根因**：`check_anchors()` 只扫 `ROOT.glob("*.py")`。v1.6 把源码收进 `src/` 后，根目录只剩
`build_and_sign.py`（没有锚点），检查从此变成空转。`defined_ids()` 仍从 `docs/` 收集编号，
所以「代码引用了不存在的契约编号」这条永远报不出来。

**修法**：扫描范围补上 `src/*.py` 与 `src/*.pyw`；再加一条「锚点数量不得为 0」的测试，
防止将来再次搬家把检查搬丢。

**影响**：`CODE-007` 要求的关键实现点锚定形同虚设，契约与代码的第三层保护（锚点）失效。

---

## 修复记录

原报告 14 条 + 核实新增 3 条，已全部收口。逐条修法与边线见 `FIXPLAN.md`。

- P0：BUG-01（`if not size` → `if size is None`，两处）、BUG-15（新增 `resume.py`，`<out>.part.json` 指纹）、BUG-02（`DownloadQueue.forget` + 「清除已完成」入口）
- P1：BUG-06+10（新增 `diskutil.py`：空间/FAT32/路径长度/ENOSPC）、BUG-16（队列登记原子化）、BUG-17（测速有界读）、BUG-07（README/GUI/使用说明 + 运行时 warn）
- P2/P3：BUG-08（路径预检）、BUG-09（哈希复用）、BUG-12（删 `deque`/`UA`）、BUG-14（两处折行）、BUG-13（改判，不动代码）
- 契约：`CORE-006/012/016/020` 更新，新增 `CORE-021/022/023`；`DATA-004` 增 `.part.json`；`GUI-010`；`CODE-003` 加两个新模块
- 结构：`downloader.py` 921 行再次触顶，按 `CODE-003` 把错误翻译表拆到 `netio.py`，最终 875 行
- 工具：BUG-18（`check_anchors` 补扫 `src/`，21 处锚点重新生效）
