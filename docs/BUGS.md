# 缺陷报告

本文件记录本项目已确认的缺陷及其处置状态。

- **建立日期**：2026-10-31
- **覆盖范围**：全部源码（约 3,750 行）、6 份契约文档、构建流程
- **当前状态**：45 条全部处置完毕——其中 31 条修改代码、8 条修改契约或文档、1 条经复核改判（BUG-13 不成立）、1 条改判后成立（BUG-38）、3 条为此前轮次已修复、1 条补校验器自测（BUG-44）

## 严重度口径

| 级别 | 判定标准 |
|---|---|
| P0 | 功能不可用，或会产出与预期不符的文件 |
| P1 | 实际行为与文档声明不一致 |
| P2 | 影响使用体验或维护成本 |
| P3 | 风格与规范问题，不影响功能 |

## 关闭方式

一条缺陷只以下列三种方式之一关闭：

| 方式 | 适用场景 | 证据要求 |
|---|---|---|
| 修改代码 | 行为本身有误 | 新增测试先失败后通过，测试体内标注缺陷编号 |
| 修改契约 | 实现合理、契约描述有误 | 契约条目改写，校验器保持通过 |
| 经复核改判 | 缺陷本身不成立 | 在本文件中记录反例与复核方法 |

「验证方式」列标明证据来源：测试（自动化用例）、静态（静态检查用例）、契约（校验器条目）、人工（人工核对）、文档（说明文字）、改判（复核结论）。

凡验证方式为「测试」或「静态」的条目，均由 `docs/verify_contract.py` 的 `bug_tests` 检查强制：所挂用例必须真实存在，且用例体内必须写明对应的缺陷编号。

## 总览

| 编号 | 标题 | 严重度 | 状态 | 验证方式 | 测试 |
|---|---|---|---|---|---|
| BUG-01 | 0 字节文件无法下载 | P0 | 已修 | 测试 | `test_bug01_zero_byte` |
| BUG-02 | 任务清空后底部汇总不复位 | P0 | 已修 | 测试 | `test_bug02_forget_resets_stats`、`test_bug02_clear_finished` |
| BUG-03 | 构建流程不产出便携版 zip | P0 | 已修 | 人工 | — |
| BUG-04 | 契约 CORE-016 描述与实现不符 | P1 | 已修 | 契约 | — |
| BUG-05 | 契约文档章节编号断裂 | P1 | 已修 | 人工 | — |
| BUG-06 | FAT32 介质上大于 4GB 的文件必然失败 | P1 | 已修 | 测试 | `test_bug06_fat32_reject`、`test_bug06_space_precheck` |
| BUG-07 | 镜像下载不强制校验哈希 | P1 | 已修 | 文档 | `test_bug07_mirror_warns_without_hash` |
| BUG-08 | 超长路径失败且错误提示误导 | P2 | 已修 | 测试 | `test_bug08_long_path` |
| BUG-09 | `dl.py` 对同一文件重复计算哈希 | P2 | 已修 | 测试 | `test_bug09_hash_single_pass`、`test_bug09_done_verified_for_md5` |
| BUG-10 | 缺少剩余空间预检 | P2 | 已修 | 测试 | `test_bug10_enospc_fast_fail`、`test_bug10_enospc_single` |
| BUG-11 | 需求依赖图缺少 016–020 | P2 | 已修 | 人工 | — |
| BUG-12 | `downloader.py` 残留未使用的导入 | P2 | 已修 | 静态 | `test_source_no_dead_imports` |
| BUG-13 | 测速失败的源仍参与加权分配 | P3 | 不成立 | 改判 | — |
| BUG-14 | 两行超出 100 列 | P3 | 已修 | 静态 | `test_source_line_width` |
| BUG-15 | 单线程续传不校验指纹 | P0 | 已修 | 测试 | `test_bug15_single_resume_detects_change`、`test_bug15_single_resume_when_unchanged` |
| BUG-16 | `add()` 与 `_pump()` 存在竞态 | P1 | 已修 | 测试 | `test_bug16_add_pump_race` |
| BUG-17 | 测速对忽略 Range 的源无界读取 | P1 | 已修 | 测试 | `test_bug17_measure_bounded` |
| BUG-18 | 校验器锚点检查空转 | P2 | 已修 | 静态 | `test_anchor_check_scans_src` |
| BUG-19 | GitHub 加速源未接入界面与命令行入口 | P0 | 已修 | 测试 | `test_bug19_mirrors_expanded_for_every_entry`、`test_bug19_github_host_matched_exactly` |
| BUG-20 | 命令行退出码由中文文案判定 | P1 | 已修 | 测试 | `test_bug20_exit_code_not_from_message` |
| BUG-21 | 部分源不支持分段时整体退化 | P1 | 已修 | 测试 | `test_bug21_partial_no_range_keeps_chunks` |
| BUG-22 | 文件名截断切掉扩展名 | P1 | 已修 | 测试 | `test_bug22_safe_name_keeps_extension` |
| BUG-23 | 队列访问引擎私有属性 | P2 | 已修 | 测试 | `test_bug23_queue_uses_public_cancel` |
| BUG-24 | 续传指纹未校验格式版本 | P2 | 已修 | 测试 | `test_bug24_resume_checks_version` |
| BUG-25 | 构建日志明文打印签名口令 | P1 | 已修 | 静态 | `test_bug25_password_not_logged` |
| BUG-26 | 跨线程共享状态未在锁内写入 | P1 | 已修 | 静态 | `test_bug26_shared_state_under_lock` |
| BUG-27 | 契约守护的常量从未被使用 | P2 | 已修 | 静态 | `test_bug27_constants_are_defaults` |
| BUG-28 | 任务线程遇到 BaseException 会遗留并发槽 | P3 | 已修 | 测试 | `test_bug28_base_exception_releases_slot` |
| BUG-29 | job 文件参数优先级以默认值为哨兵 | P2 | 已修 | 测试 | `test_bug29_cli_beats_job_file`、`test_bug29_job_used_when_cli_silent` |
| BUG-30 | 源码命令行入口与打包命令行能力不一致 | P2 | 已修 | 测试 | `test_bug30_downloader_has_no_cli_entry`、`test_bug30_readme_points_to_dl` |
| BUG-31 | 校验器存在五类盲区 | P2 | 已修 | 测试 | `test_bug31_const_used_detects_dead_constant`、`test_bug31_const_used_accepts_used_constant`、`test_bug31_private_access_detected`、`test_bug31_call_site_detects_missing_call`、`test_bug31_max_lines_flags_undeclared_module`、`test_bug31_req_test_requires_docstring_marker` |
| BUG-32 | 进度统计口径与合并校验口径不一致 | P3 | 已修 | 测试 | `test_bug32_progress_never_exceeds_total` |
| BUG-33 | 删除超长分片时进度不回退 | P3 | 已修 | 测试 | `test_bug33_oversized_part_rolls_back_progress` |
| BUG-34 | 测速把探测耗时计入分母 | P3 | 已修 | 测试 | `test_bug34_measure_excludes_probe_time` |
| BUG-35 | 限速在写盘之后才生效 | P3 | 已修 | 测试 | `test_bug35_limiter_acquires_before_write` |
| BUG-36 | `SCHEMA.version` 不随接口变化递增 | P3 | 已修 | 测试 | `test_bug36_schema_version_increments`、`test_bug36_schema_version_check_detects_drift` |
| BUG-37 | `progress` 节流文案与实现语义不一致 | P3 | 已修 | 测试 | `test_bug37_progress_throttle_is_or_of_interval_and_delta` |
| BUG-38 | 剪贴板监听覆盖用户正在输入的内容 | P2 | 已修 | 测试 | `test_bug38_clipboard_not_filled_in_focus_gap`、`test_bug38_clipboard_fills_again_after_focusout` |
| BUG-39 | 限速语义只改了一半，CLI 与契约仍称「全局限速」 | P2 | 已修 | 测试 | `test_bug39_rate_limit_wording_consistent` |
| BUG-40 | CODE-002 关于 downloader 依赖的表述与自身矛盾 | P3 | 已修 | 文档 | — |
| BUG-41 | CORE-001 公开符号未包含再导出的 `GITHUB_MIRRORS` | P3 | 已修 | 文档 | — |
| BUG-42 | 416 Range Not Satisfiable 未被识别，声称支持分段的服务器完全下不下来 | P2 | 已修 | 测试 | `test_bug42_probe_reports_no_ranges_on_416`、`test_bug42_download_succeeds_when_416`、`test_bug42_worker_416_falls_back_to_single`、`test_bug42_permanent_error_no_full_retry` |
| BUG-43 | `schema_defaults` 的参数映射是手工白名单，新增默认值键可整体逃逸检查 | P2 | 已修 | 测试 | `test_bug43_schema_defaults_detects_unmapped_default_key`、`test_bug43_schema_defaults_detects_map_key_absent_from_defaults` |
| BUG-44 | `literal_dict` 检查没有自测用例，改坏了无人察觉 | P3 | 已修 | 测试 | `test_bug44_literal_dict_detects_non_literal`、`test_bug44_literal_dict_accepts_literal` |
| BUG-45 | `schema_defaults` 采信契约 map 的参数名，map 错接时该默认值不受检查 | P2 | 已修 | 测试 | `test_bug45_schema_defaults_reverse_lookup_from_args`、`test_bug45_schema_defaults_detects_map_mispointing`、`test_bug45_schema_defaults_catches_text_under_wrong_map` |

---

## BUG-01 · 0 字节文件无法下载（P0）

**现象**　服务端返回 `Content-Length: 0` 的合法文件时，探测结果被判为失败，下载以「所有下载源都不可用」结束。GitHub 仓库中的空文件（`.gitkeep`、空的 `__init__.py`、空配置模板）均属此类。

**根因**　`probe()` 以 `if not size:` 判定探测失败，把 `0` 与 `None` 混为一谈；`_measure_mirror()` 中存在同样写法。

**处置**　两处判定改为 `is None`。空文件不再发起测速请求。契约 CORE-006 补充说明：`size` 为 `0` 是合法值，`error` 仅在 `size is None` 时非空。

**验证**　`test_bug01_zero_byte`。

---

## BUG-02 · 任务清空后底部汇总不复位（P0）

**现象**　任务行从界面移除后，底部汇总仍显示历史计数，进度条停留在 100%。

**根因**　`DownloadQueue._state` 只写不删，`stats()` 统计全部历史任务；界面删除任务行时未通知队列。契约中「长会话不涨内存」的表述因此只对 `_tasks` 成立。

**处置**　新增 `DownloadQueue.forget(tid)`：仅接受终态（done / failed / cancelled），移除后 `stats()` 立即减少；界面在移除任务行时调用该方法。界面底部新增「清除已完成」入口，用于清理终态任务并复位汇总；同时修正了「文件已不存在时点击『打开』会静默删除该行」的行为，改为提示并切换按钮。

**验证**　`test_bug02_forget_resets_stats`（队列层）、`test_bug02_clear_finished`（界面层）。

---

## BUG-03 · 构建流程不产出便携版 zip（P0，已修复）

**现象**　`build_and_sign.py` 只部署 exe，从不生成 `下载工具_便携版.zip`，而 README 声明该文件在构建时生成。

**根因**　打包步骤长期依赖人工操作。

**处置**　构建脚本新增 `pack_portable()`，把产物、README、使用说明与任务示例一并归入 `build/便携版/` 并生成 zip，同时复制一份到桌面。

**验证**　人工核对 `build/便携版/` 目录内容与 zip 内条目。

---

## BUG-04 · 契约 CORE-016 描述与实现不符（P1）

**现象**　契约写「任务进入终态后从 `_tasks` 移除，长会话不涨内存」。实现中 `_tasks` 确实移除，但 `_state` 与 `_PATH_LOCKS` 的条目从不释放。

**处置**　随 BUG-02 一并处理：新增 `forget()` 使 `_state` 可被释放；`_PATH_LOCKS` 按路径缓存、进程内不回收，改由契约明确写出该限制，不再声称「不涨内存」。

---

## BUG-05 · 契约文档章节编号断裂（P1，已修复）

**现象**　`CONTRACT-code.md` 的章节编号缺少第 10 章。

**处置**　重新编号为连续的 1–11。

---

## BUG-06 · FAT32 介质上大于 4GB 的文件必然失败（P1）

**现象**　本工具的定位是放在 U 盘随身使用，而 FAT32 单文件上限为 4GB−1。原实现先把全部分片下载完成，合并阶段调用 `truncate(size)` 才失败，用户需等待数十分钟，且最终得到的是底层 `OSError`。

**根因**　缺少文件系统类型与剩余空间预检。`MAX_FILE_SIZE = 200GB` 只能拦截明显不合理的体积。

**处置**　新增 `src/diskutil.py`，在 `run()` 确定目标路径后、建目录之前执行三项预检：路径长度、FAT32 单文件上限、目标盘剩余空间。任何一项探测本身失败（UNC 路径、无权限、非 Windows）一律放行，预检不得阻断本可完成的下载。

**验证**　`test_bug06_fat32_reject`、`test_bug06_space_precheck`。

---

## BUG-07 · 镜像下载不强制校验哈希（P1）

**现象**　内置的三个第三方 GitHub 加速源未提供哈希时只核对文件大小。镜像可以返回「大小正确、内容被替换」的文件，工具仍报告下载完成。

**处置**　代码层无法验证镜像内容，只能约束与告知：

- 运行时在多源且未提供哈希的情况下输出一条 warn；
- README、界面参数说明与使用说明中明确写出「经镜像下载的二进制必须自带哈希」。

**验证**　`test_bug07_mirror_warns_without_hash`。

---

## BUG-08 · 超长路径失败且错误提示误导（P2）

**现象**　保存路径超过 Windows `MAX_PATH` 时，写入失败并抛出 `FileNotFoundError [Errno 2]`，而目录实际存在。

**根因**　`_safe_name` 允许 120 字符文件名，与较深的目录叠加后超出长度限制。

**处置**　在下载前检查路径长度，超限时给出可执行的提示（当前长度与建议），不再暴露底层错误码。判定式与阈值写入契约 CORE-023。

**验证**　`test_bug08_long_path`。

---

## BUG-09 · `dl.py` 对同一文件重复计算哈希（P2）

**现象**　传入 `--sha256` 时，`_verify()` 已完整读过一遍文件，`main()` 随后又用 sha256 读一遍，2GB 文件多读 2GB。

**处置**　`DownloadTask` 在校验后记录实际算法与结果，`dl.py` 优先复用；期望值为 md5/sha1 时仍单独计算一次 sha256 以填充 `done.sha256` 字段。顺带修正：期望值为 md5 时，`done.verified` 曾用 sha256 实际值与 md5 期望值比较，必然误报 `false`。

**验证**　`test_bug09_hash_single_pass`、`test_bug09_done_verified_for_md5`。

---

## BUG-10 · 缺少剩余空间预检（P2）

**现象**　磁盘写满后，失败被逐分片捕获并按退避策略重试，观感上与卡死无异。

**处置**　与 BUG-06 合并处理：下载前一次性检查可用空间；写入阶段捕获 `ENOSPC` 后立即中止，不进入退避重试，合并阶段失败时删除半成品输出并保留分片。

**验证**　`test_bug10_enospc_fast_fail`、`test_bug10_enospc_single`。

---

## BUG-11 · 需求依赖图缺少 016–020（P2，已修复）

**现象**　`REQ.md` 的依赖关系图只覆盖到 REQ-015。

**处置**　补齐 016（依赖 001）、017（依赖 016）、018–020（独立）。

---

## BUG-12 · `downloader.py` 残留未使用的导入（P2）

**现象**　静态检查发现 `deque` 与 `UA` 已无引用；`_opener` 为测试所需的再导出，原报告将其一并计为残留属误判。

**处置**　删除 `deque` 与 `UA`；`_opener` 保留并注明用途。行宽与死导入检查并入 `tests/test_contract.py`，形成静态守卫。

**验证**　`test_source_no_dead_imports`。

---

## BUG-13 · 测速失败的源仍参与加权分配（P3，不成立）

**复核结论**　现象描述不成立，建议的修法亦为空操作。

**反例**　穷举分片数 1–40 与 10 组含零权重的权重组合（`[0,1]`、`[1,0]`、`[0,0,5]`、`[3,0,1]` 等），零权重源被分配到分片的次数为 0。

**原因**　`_distribute` 的配额为 `max(0.0, w) / total * n`，零权重占比为零；最大余数法的补位按小数部分排序，零权重的小数部分恒为零，余数只会分配给具有正小数部分的源。仅当全部权重为零时退化为轮转，该行为为刻意设计。

**相关事实**　测速速度为零的源仍保留在 `mirrors` 中，`_worker` 的重试轮换会访问该源。这属于换源容错的组成部分，一次尝试后即轮走；强行剔除会误伤「测速被限流但实际可用」的源。

---

## BUG-14 · 两行超出 100 列（P3）

**现象**　`downloader.py:138`（102 列）与 `gui.pyw:351`（103 列）违反 CODE-009。

**处置**　折行处理，并将行宽检查加入 `tests/test_contract.py`。

**验证**　`test_source_line_width`。

---

## BUG-15 · 单线程续传不校验指纹（P0）

**现象**　单线程路径（小于 2MB，或服务端不支持分段）中断后续传，若服务端已用**同长度**的另一份内容替换文件，最终产物既不是旧文件也不是新文件；`run()` 正常返回，且不产生 `.corrupt` 隔离文件。

**根因**　`_download_single` 仅依据 `.part` 的大小续传，没有指纹校验。分片路径有 `meta.json` 的 `size` / `chunks` / `etag` 三重校验，单线程路径缺少等价机制。

**处置**　新增 `src/resume.py`，以 `<out>.part.json` 记录 `size` / `etag` / `url`：开始写入前落盘（先写临时文件再替换），成功落盘后删除，中断时保留。续传前比对 `size`，双方均有 ETag 时比对 ETag，不符即删除 `.part` 重新下载。服务端不提供 ETag 时允许续传，但输出 warn 说明该情形下无法检测同长度变更。

**影响**　镜像或发布页替换同名文件后续传，会静默产出哈希不符的文件，且无任何提示。

**验证**　`test_bug15_single_resume_detects_change`（内容变更必须被检出）、`test_bug15_single_resume_when_unchanged`（内容未变更时必须真正续传，不得退化为全量重下）。

---

## BUG-16 · `add()` 与 `_pump()` 存在竞态（P1）

**现象**　任务偶发停留在「连接中」，且队列不再启动新任务。

**根因**　`add()` 先将 tid 放入 `_pending`，释放锁之后才构造 `DownloadTask` 并写入 `_tasks`。若此期间有任务结束并触发 `_pump()`，该 tid 会被取出并启动，`_run_one` 中 `self._tasks[tid]` 抛出 `KeyError`；工作线程随之退出，`_running[tid]` 永不释放，状态停留在 `running`，并发槽位减少一个。`concurrent=1` 时队列完全停滞。

**处置**　调整为先构造任务、再在同一把锁内一次性登记 `_tasks` / `_state` / `_pending`；`_run_one` 改用 `.get(tid)`，取不到时归还并发槽位。

**验证**　`test_bug16_add_pump_race`（以事件同步复现竞态窗口）。

---

## BUG-17 · 测速对忽略 Range 的源无界读取（P1）

**现象**　源忽略 Range 时，测速阶段把整个响应读入内存。32MB 源实测峰值内存 48MB；GB 级源会直接耗尽内存，且多源并发时叠加。

**根因**　`_measure_mirror` 以 `r.read()` 统计吞吐，未限制读取长度。Range 生效时响应仅 256KB，未生效时为完整文件。

**处置**　改为循环读取，最多读取 256KB，读满即止，不依赖服务端遵守 Range。

**验证**　`test_bug17_measure_bounded`。

---

## BUG-18 · 校验器锚点检查空转（P2）

**现象**　`verify_contract.py -v` 输出「0 处锚点全部有效」，实际未检查任何锚点。

**根因**　`check_anchors()` 只扫描仓库根目录。v1.6 将源码移入 `src/` 之后，根目录仅剩构建脚本，锚点检查自此形同虚设，「代码引用了不存在的契约编号」这一检查永远无法触发。

**处置**　扫描范围补入 `src/` 下的 Python 文件；并增加一条断言，确保锚点数量不为零。当前 21 处锚点全部有效。

**验证**　`test_anchor_check_scans_src`。

---

## BUG-19 · GitHub 加速源未接入界面与命令行入口（P0）

**现象**　README、使用说明、界面参数说明与契约 CORE-007 均声明「GitHub 链接自动补充加速镜像」，但该逻辑只存在于 `downloader.py` 的遗留命令行入口。界面与打包后的命令行入口都未调用 `build_mirror_urls()`，用户实际使用的两条路径均无此功能。

**根因**　加速源补全写在入口层而非引擎层，两个正式入口各自组装 URL 时都未纳入。

**处置**　新增 `src/mirrors.py` 承载加速源策略（主机名判定、候选构造、批量展开），`DownloadTask.run()` 统一调用 `expand_mirror_urls()`，三个入口行为一致。主机名改为按 URL 解析判定，不再做子串匹配，避免查询串中出现 `github.com` 即被误判。

**影响**　这是面向国内用户最核心的一项功能，此前在交付的产物上从未生效。

**验证**　`test_bug19_mirrors_expanded_for_every_entry`、`test_bug19_github_host_matched_exactly`。

---

## BUG-20 · 命令行退出码由中文文案判定（P1）

**现象**　`dl.py` 以「消息中是否含『不可用』」判定退出码 3。保存位置不可用（盘符不存在、目录只读）的错误消息同样含「不可用」，被报成「所有镜像不可用」。

**根因**　失败类型依赖错误文案判定，文案一改，退出码即错。

**处置**　`DownloadError` 携带 `code` 字段，引擎层定义 `EXIT_FAIL` 与 `EXIT_NO_MIRROR`，命令行入口直接取用该字段。契约 CLI-002 的判据同步改写。

**验证**　`test_bug20_exit_code_not_from_message`。

---

## BUG-21 · 部分源不支持分段时整体退化（P1）

**现象**　任一分片在任一镜像上收到 200 即置全局标志，随后整批下载退化为单线程重下。若镜像 A 不支持分段而镜像 B 支持，已下载的分片仍被作废。

**根因**　退化判据是「有任一源忽略 Range」，而非「全部源忽略 Range」。

**处置**　改为按镜像记录「忽略 Range」，仅当全部镜像都被观测到如此时才整体退化；否则该分片换源重试。

**验证**　`test_bug21_partial_no_range_keeps_chunks`。

---

## BUG-22 · 文件名截断切掉扩展名（P1）

**现象**　超过 120 字符的文件名被直接截断，扩展名一并丢失，文件类型识别随之失效。

**处置**　截断时保留扩展名，扩展名本身另设长度上限。

**验证**　`test_bug22_safe_name_keeps_extension`。

---

## BUG-23 · 队列访问引擎私有属性（P2）

**现象**　`taskqueue.py` 读取 `task._cancel`，违反 CORE-001「以下划线开头的符号视为私有」。

**处置**　`DownloadTask` 暴露公开属性 `cancelled`，队列改读该属性。

**验证**　`test_bug23_queue_uses_public_cancel`。

---

## BUG-24 · 续传指纹未校验格式版本（P2）

**现象**　`resume.py` 写入 `version` 字段，判定时却不检查；格式变更后旧指纹仍被采信。

**处置**　`matches()` 增加版本校验。

**验证**　`test_bug24_resume_checks_version`。

---

## BUG-25 · 构建日志明文打印签名口令（P1）

**现象**　`build_and_sign.py` 的 `run()` 无条件打印完整命令行，签名口令随 `/p` 参数进入日志；CI 日志长期保留。

**处置**　`run()` 增加 `redact` 参数，签名调用时把 `/p` 后的值替换为 `***`。构建脚本的输出包装移入 `main()`，使模块可被测试导入。

**验证**　`test_bug25_password_not_logged`。

---

## BUG-26 · 跨线程共享状态未在锁内写入（P1）

**现象**　`_errors.append()`、`_fatal` 赋值与镜像忽略 Range 的记录均在锁外执行，与 CODE-006、CORE-005 的明文规定不符。

**处置**　三处写入统一纳入 `self._lock`，并增加静态用例守住。

**验证**　`test_bug26_shared_state_under_lock`。

---

## BUG-27 · 契约守护的常量从未被使用（P2）

**现象**　`SLOW_BYTES` / `SLOW_WINDOW` / `MAX_RETRY` 在全文件中仅出现于定义处，从未被读取；契约 CORE-003 却声明它们「参与行为判定」，校验器只比对常量取值，不检查是否真被使用。

**处置**　三个常量改为构造参数默认值的来源，默认行为不变，契约表述随之成立。

**验证**　`test_bug27_constants_are_defaults`。

---

## BUG-28 · 任务线程遇到 BaseException 会遗留并发槽（P3）

**现象**　`_run_one` 只捕获 `Exception`，`KeyboardInterrupt` / `SystemExit` 会使线程退出，`_state` 停在 `running`，并发槽不归还。

**处置**　改为捕获 `BaseException`，落终态并归还槽位。

**验证**　`test_bug28_base_exception_releases_slot`。

---

## BUG-29 · job 文件参数优先级以默认值为哨兵（P2）

**现象**　用户显式传入与默认值相同的参数时，job 文件的值会覆盖命令行：`dl --threads 16 --job job.json`（job 里写了 `threads: 4`）最终按 4 跑。用户的显式意图被静默丢弃。

**根因**　`argparse` 的默认值直接写成业务默认值，解析后无法区分「用户没传」与「用户传了个等于默认值的数」。

**处置**　`argparse` 一律用 `None` 作哨兵，业务默认值集中到 `DEFAULTS`（与 `SCHEMA["defaults"]` 同源）。取值走三档：命令行显式值 > job 文件 > 业务默认值。契约新增 CLI-001a 记录这条优先级。

**验证**　`test_bug29_cli_beats_job_file`（命令行优先）、`test_bug29_job_used_when_cli_silent`（job 文件仍生效）。

---

## BUG-30 · 源码命令行入口与打包命令行能力不一致（P2）

**现象**　`downloader.main()` 只有 8 个参数，`dl.main()` 有 16 个。README 至今宣传 `python src/downloader.py`，用户按文档敲进去会发现 `--proxy` / `--max-speed` / `--hash` / `--json` / `--quiet` / `--job` / `--schema` 全都不存在。

**根因**　两套解析器并存，而**只有一套被契约与校验器覆盖**——`schema_vs_argparse` 检查的是 `dl` 的 `SCHEMA` 与 `dl` 的 `argparse`。第二套解析器不受任何检查保护，能力差异因此长期潜伏。

**处置**　删除 `downloader.main()`，引擎层收敛为纯引擎 API：公开符号表删掉 `main`，模块内不得出现 `argparse`。唯一命令行实现是 `dl.py`（契约新增 CLI-010）。直接运行 `python src/downloader.py` 会打印迁移提示并以非零码退出——保留这段守卫是为了让用户看到明确指引，而不是「静默成功」。

**影响**　交付产物的命令行路径本就只有 `dl.main()` 一条，删除第二套解析器不改变任何可达行为。

**验证**　`test_bug30_downloader_has_no_cli_entry`（引擎不再导出 `main`、不含 `argparse`）、`test_bug30_readme_points_to_dl`（README 指向唯一入口）。

---

## BUG-31 · 校验器存在五类盲区（P2）

**现象**　契约与代码之间有五类漂移，17 项检查全都发现不了：

| 类 | 盲区 | 为什么漏 |
|---|---|---|
| a | 常量是否真被使用 | `chk_const` 只比取值，从未被读取的常量照样 PASS |
| b | 公共符号是否被越界访问 | CORE-001 写了「下划线开头视为私有」，却无人检查 `task._cancel` 这类访问 |
| c | 契约行为是否落地 | CORE-007 写「`run()` 必须调用 `expand_mirror_urls`」，却无人验证调用点存在 |
| d | 规模上限的语义 | `chk_max_lines` 只在「行数 > 上限」时报红；**新增模块漏登记上限则完全不受约束** |
| e | 需求与测试的对应是否有效 | 只验「测试函数存在」+「函数体内出现 REQ 编号」，编号写在注释里、测试体是空的都能蒙混过关 |

**根因**　校验器只做**取值比对**，不做**存在性比对**与**语义比对**。

**处置**　补四类可执行检查，并加强两项既有检查：

| 新检查 | 判据 |
|---|---|
| `const_used` | 常量名必须在声明范围内出现一次**读取**（AST 的 `Load` 上下文）。模块级赋值是 `Store`，天然不计入 |
| `no_private_access` | 扫描 `ast.Attribute`，命中**别模块**的私有符号即失败。同模块豁免、`self` 豁免、`allow` 白名单 |
| `call_site` | 契约声明的调用点必须存在。`call` 分两档匹配：裸名命中 `Name(id=S)`，点号名必须精确匹配 `M.S` 的完整形式 |
| `schema_version` | `SCHEMA.version` 与结构指纹必须与契约一致；指纹变了版本必须升，指纹没变版本不许动 |

既有检查的加强：`max_lines` 增加「声明了上限但文件不存在」与「`src/` 下有模块未登记上限」两条判定；`req_tests` 要求 REQ 编号写在 **docstring** 里（注释不算），且用例体至少含一条断言。

**验证**　`test_bug31_const_used_detects_dead_constant`、`test_bug31_const_used_accepts_used_constant`、`test_bug31_private_access_detected`、`test_bug31_call_site_detects_missing_call`、`test_bug31_max_lines_flags_undeclared_module`、`test_bug31_req_test_requires_docstring_marker`（六条各守一类盲区，且都带「零误报」的正向用例）。

---

## BUG-32 · 进度统计口径与合并校验口径不一致（P3）

**现象**　进度条先显示 100%，随后合并阶段报「分片长度异常」。

**根因**　进度与合并用了两套互不相同的口径：

| 位置 | 口径 | 后果 |
|---|---|---|
| 续传扫描 | `min(磁盘大小, 期望长度)` | 超长片按满额计入 |
| 写入累加 | `+= len(buf)`，不夹紧 | 超长片把 `_done` 顶过 `total` |
| 合并校验 | `磁盘大小 == 期望长度`，严格相等 | 不等即抛「长度异常」 |

**处置**　统一为单一判据「分片有效字节」：新增 `_credited(size, want)`，**超长的一分不算**（该片无效，必须整片重下）。进度、写入累加、删除扣减全部走这一个函数。于是 `done ≤ total` 恒成立，「进度 100%」的充要条件就是全部分片长度恰好等于期望长度。契约新增 CORE-025。

**配套加固**　写入前拦截：数据超出本片期望长度时**不落盘**（超出的部分属于别的分片），整片作废并换源重试——错误从合并期提前到分片期，文案更明确。

**验证**　`test_bug32_progress_never_exceeds_total`（假服务器返回超出分片范围的数据，进度不得越过 100%，且失败原因不得是「长度异常」）。

---

## BUG-33 · 删除超长分片时进度不回退（P3）

**现象**　`_worker` 删除超长分片时 `_done` 里已计入的字节没有同步扣减，进度虚高；该片重下后进度直接冲过总量。

**根因**　删除分片只做了 `os.remove` 与 `have = 0`，没动计数；而已计入的字节仍留在 `_done` 里。

**处置**　与 BUG-32 合并为同一次改动：删除分片时按**同一个** `_credited` 函数扣回，计入与扣减不可能分叉。超长片在续传扫描阶段就计 0，删除时扣 0——不产生虚高，也不产生负数（无条件减 `want` 会把进度打到 0 以下）。

**验证**　`test_bug33_oversized_part_rolls_back_progress`（预置超长分片 + 三项全等的 `meta.json`，进度全程不越界，产物哈希与服务器一致）。

---

## BUG-34 · 测速把探测耗时计入分母（P3）

**现象**　探测越慢，测出的速度越低；该速度直接决定 `_distribute` 的分片加权分配，探测慢的源因此被少分片。

**根因**　`_measure_mirror` 的 `t0 = time.time()` 放在 `probe(u)` **之前**，`dt` 因此包含了 DNS 解析、TCP 连接、TLS 握手与探测本身的全部开销。

**处置**　把计时起点移到「响应头到达之后、第一次读之前」。DNS/连接/TLS/探测耗时不计入分母（它们与源快慢无关）；首字节延迟仍计入——连接建立后迟迟不吐数据的源本就该是慢源。契约 CORE-007 同步改写。

**验证**　`test_bug34_measure_excludes_probe_time`（把 `probe` 换成慢 0.4 秒的桩，测出的速度不得因此腰斩）。

---

## BUG-35 · 限速在写盘之后才生效（P3）

**现象**　开启限速后，第一个数据块（`BLOCK` = 256KB）无阻写入磁盘，瞬时速率高于设定值。

**根因**　两处写盘循环都是「先写后补」：`_write(f, buf)` → `self._limiter.acquire(len(buf))`。

**处置**　两处都改为**先取配额再落盘**：限速作用于真正写进磁盘的字节。契约 CORE-014 同步改写。令牌桶的夹紧逻辑保证单次请求不超过桶容量，不会死等。

**验证**　`test_bug35_limiter_acquires_before_write`（桩掉限速器与写盘点，记录事件顺序，第一次 `write` 之前必须出现过 `acquire`）。

---

## BUG-36 · `SCHEMA.version` 不随接口变化递增（P3）

**现象**　`--schema` 是面向脚本与 AI Agent 的机器可读接口，消费方靠 `version` 判断兼容性；但该字段自建立起一直是 `1`，而期间 `SCHEMA` 改过多次（加 `sha256_expected` / `verified` 字段、删 `start` 事件、参数集扩到 16 个）。

**根因**　`SCHEMA["version"] = 1` 是手工维护的常量，没有任何机制把「接口形状变了」与「版本号要变」关联起来。

**处置**　`version` 升到 2，并把版本号变成**受校验器约束的量**：契约新增 CLI-011，声明当前版本、结构指纹与上一版基线；校验器新增 `schema_version` 检查，四级判定：

| # | 场景 | 判据 |
|---|---|---|
| 1 | 内容漂移 | 实算指纹 ≠ 声明指纹 |
| 2 | 版本号漂移 | `SCHEMA["version"]` ≠ 声明 version |
| 3 | 版本降级 | `version < previous.version` |
| 4 | **递增与内容变化不同步** | `(version > previous.version)` 与 `(fingerprint != previous.fingerprint)` **必须同真同假** |

规则 3 不可省：`fingerprint != previous.fingerprint` 只能发现「内容变了」，发现不了「内容变了但版本号没跟上」——而后者正是本条要防的事，消费方看到 `version` 没变就以为接口没变。规则 4 用「同真同假」而非「两个都要真」，是为了让中间态（版本与指纹都没动）合法通过。

**指纹口径**：`payload = SCHEMA` 去掉 `version` 后的**全部键**，`sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()`。取全部键而非逐键列举：`defaults` 是 `--schema` 输出的一部分，消费方读得到，漏掉它等于给「默认值被悄悄改掉」开后门——而那正是本条要防的漂移。逐键列举还会漏掉将来新增的顶层键。

**形态校验硬失败**：`version` 必须是整数、`fingerprint` 必须是 64 位小写十六进制、`previous` 必须是恰好含这两键的字典。形态不合法直接记 RED，**不允许因字段缺失就跳过这项检查**——静默放行正是本条要堵的洞。

**验证**　`test_bug36_schema_version_increments`（版本已递增）、`test_bug36_schema_version_check_detects_drift`（指纹漂移与形态不合法都必须报红）。

---

## BUG-37 · `progress` 节流文案与实现语义不一致（P3）

**现象**　契约写「≥1.5s **且** 百分比变化 ≥1% 才发」，实现是「满足**其一**即输出」。

**根因**　文案与实现各说各话，且没有任何检查能发现——文案类漂移不在校验器的射程内。

**处置**　改文案、保留实现的 OR 语义。理由四条：AND 语义下 1GB 文件的 1% 意味着 10MB，链路上 1.5s 内很难变化 1%，会出现长时间静默，对脚本 / CI / AI Agent 不友好；OR 语义下「百分比变化 ≥1% 立即发」是有意义的实质信号；改文档成本一行，改实现要动节流逻辑并新增行为用例，风险与收益不成比例；界面侧本就每 80ms 轮询、无节流，CLI 的 1.5s 是采样频率而非「无变化就不报」。

**配套**　节流判据从闭包提取为模块级可测函数 `_throttle_ok`，阈值提为模块常量 `PROGRESS_INTERVAL_SEC` / `PROGRESS_PERCENT_DELTA`（契约新增 CLI-012，阈值由既有 `const` 检查锁住）。文案与实现用测试双向锁定。

**验证**　`test_bug37_progress_throttle_is_or_of_interval_and_delta`（四档判据 + 契约文案必须含「或」）。

---

## BUG-38 · 剪贴板监听覆盖用户正在输入的内容（P2，改判后成立）

**现象**　用户点击链接输入框准备手动输入时，剪贴板里残留的旧直链会被自动填入，覆盖输入框内容。用户若未察觉就点「开始下载」，会下载错文件。

**根因**　`_clear_placeholder()` 在 `<FocusIn>` 时删除占位符文本并移除 `ph` 标签，此后输入框内容为空且 `ph` 标签已不存在。而 `_url_box_empty()` 的判据是「有 `ph` 标签 → 空；否则看文本是否为空」，此时两者都为真，返回真。

**复核为何不成立**　此前只验证了「用户已手输内容时不被覆盖」这一情形，遗漏了「已聚焦但尚未输入」的中间态。该状态在用户点击输入框到敲下第一个字符之间存在，窗口虽短（轮询间隔 900ms），但足以命中。

**复现方式**　用 `ast` 从 `gui.pyw` 提取 `_restore_placeholder` / `_clear_placeholder` / `_url_box_empty` 三个方法的真实源码并 `exec` 编译，注入假文本控件后执行：

| 阶段 | 文本 | `ph` 标签 | `_url_box_empty()` |
|---|---|---|---|
| 初始（占位符） | `https://…` | 有 | True |
| **点进输入框后** | 空 | **无** | **True ← 空窗** |
| 已手输 1 个字符 | `h` | 无 | False |

**处置**　引入显式的「用户已接管输入」状态 `App._url_touched`（契约新增 GUI-011）：

| 阶段 | `_url_touched` | 剪贴板可填入 |
|---|---|---|
| 初始（占位符显示中） | `False` | 可 |
| `<FocusIn>` 之后、尚未输入 | `True` | **不可**（空窗窗口在此被堵住） |
| `<FocusIn>` 且已输入 | `True` | 不可（双重保险） |
| `<FocusOut>`，有内容 | `True` | 不可 |
| `<FocusOut>`，无内容 | `False` | 可 |

置位在 `_clear_placeholder()` 的**第一行**（用户点进输入框即视为接管），复位在 `_restore_placeholder()` 的「文本为空」分支（用户离开且没留下内容，视为未接管）。`_watch_clip()` 的填入条件追加 `not self._url_touched`。

**为什么不用焦点判断**　`focus_get()` 在窗口 withdraw、控件未映射时行为不稳定，测试要构造真实焦点；且「焦点在输入框但用户没在输入」与「用户在输入」无法区分，语义不如显式状态清楚。

**验证**　`test_bug38_clipboard_not_filled_in_focus_gap`（覆盖空窗窗口）、`test_bug38_clipboard_fills_again_after_focusout`（防功能退化：用户离开后剪贴板恢复填入）。

---

## BUG-39 · 限速语义只改了一半（P2）

**现象**　「全局限速」改称「每任务限速」时只改了 GUI 侧与面向用户的文档，命令行侧与契约侧仍是旧措辞：

| 位置 | 现措辞 |
|---|---|
| `README.md` GUI 参数表 | 每任务限速 |
| `README.md` CLI 参数表 | **全局限速**（同文件内自相矛盾） |
| `使用说明.txt` | 每任务限速 |
| `src/dl.py` `SCHEMA["args"]` | **全局限速** |
| `src/dl.py` argparse help | **全局限速** |
| `docs/CONTRACT-cli.md` | **全局限速** |
| `docs/CONTRACT-data.md` | **全局限速** |
| `docs/REQ.md` REQ-010 | **全局限速** |

**影响**　`--schema` 是面向脚本与 AI Agent 的机器可读接口，消费方按「全局」理解会得到错误预期；README 同一文件内两种说法并存也会误导读者。

**处置**　统一为「每任务限速」，并注明「并发多任务时合计速率高于设定值」。改动落在 8 处：`README.md` CLI 参数表、`src/dl.py` 的 `SCHEMA["args"]`、argparse help、`docs/CONTRACT-cli.md`、`docs/CONTRACT-data.md`、`docs/REQ.md` REQ-010，以及 `src/downloader.py` 内的注释。`build/便携版/README.md` 是构建产物副本，不手改（重新打包会覆盖）。

**说明**　`--schema` 的描述文本改动会改变接口结构指纹，因此与 BUG-36 的版本递增同轮落地（指纹按最终 SCHEMA 计算）。指纹口径为「SCHEMA 去掉 `version` 后的全部键」，`defaults` 也在其中——它是 `--schema` 输出的一部分，消费方读得到（契约 CLI-011）。

**验证**　`test_bug39_rate_limit_wording_consistent`（`SCHEMA` 描述与 argparse help 都称「每任务限速」，且四份面向用户的文档不再残留「全局限速」）。

---

## BUG-40 · CODE-002 表述与自身矛盾（P3）

**现象**　`CONTRACT-code.md` 第 37 行声明 `diskutil.py` / `resume.py` / `mirrors.py` 是「只被 `downloader` 依赖」的叶子模块，第 39 行却仍写「`downloader.py` 只允许依赖 `netio`」。两句互相矛盾，且与实现不符——`downloader` 实际依赖 `netio` + `diskutil` + `resume` + `mirrors`。

**处置**　改为「`downloader.py` 只允许依赖 `netio` / `diskutil` / `resume` / `mirrors` / `naming` / `httpinfo` 这六个下层模块，不得依赖 `gui.pyw` / `dl.py` / `taskqueue.py`」——与实现一致，也把第一批拆出的 `naming` / `httpinfo` 补进清单。分层图同步修订，叶子模块的依赖关系逐条写明（`httpinfo` 额外依赖 `netio` 与 `naming`）。

**验证**　文档核对：分层图与依赖清单一致，`downloader.py` 的实际导入与清单相符。

---

## BUG-41 · CORE-001 未包含再导出的 `GITHUB_MIRRORS`（P3）

**现象**　`CODE-002` 声明 `downloader` 再导出 `mirrors` 的三个公开符号（`GITHUB_MIRRORS` / `build_mirror_urls` / `is_github_release`），但 CORE-001 的 `public_symbols` 列表只含后两个——`GITHUB_MIRRORS` 不在其中，而 CORE-001 明写「只有下列符号允许被外部引用」。

**处置**　选「从 `downloader` 的再导出中去掉它」：`GITHUB_MIRRORS` 是数据表而非行为 API，不需要经引擎转发，需要它的人直接 `import mirrors`（该模块本身仍可达）。CORE-001 的公开符号表因此与「再导出的函数」严格对应，CODE-002 里关于再导出的表述同步修订。

**验证**　文档与代码核对：`downloader` 不再导出 `GITHUB_MIRRORS`，CORE-001 的列表与之相符。

---

## BUG-42 · 416 未被识别，声称支持分段的服务器完全下不下来（P2）

**现象**　服务器在 `HEAD` 响应里声称 `Accept-Ranges: bytes`，但对实际的 `Range` 请求按 RFC 7233 返回 `416 Range Not Satisfiable`（附 `Content-Range: bytes */<总长>`）。这类服务器对**不带 Range 的完整 GET 完全正常**，文件可以轻松下载——但本工具对这种文件**完全无法完成下载**，最终报「N 个分片失败，已保留进度可重试」。

**对照实验**　同一台本地服务器、同样的 416 响应行为，唯一变量是 `HEAD` 是否声称 `Accept-Ranges`：

| HEAD 响应 | `probe()` 结果 | 下载结果 |
|---|---|---|
| 带 `Accept-Ranges: bytes` | `size=3145728 ranges=True` | **失败**：3 个分片失败，已保留进度可重试 |
| 不带 `Accept-Ranges` | `size=3145728 ranges=False` | **成功**：3145728 字节 |

**根因**　两处叠加：

1. `probe()` 在 `HEAD` 声称支持分段时**不再做确认探测**（`if size is None or not ranges:` 条件不成立），直接采信 `Accept-Ranges`；
2. `_worker` 只对 `r.status == 200` 做了「该源不支持分段」的标记（CORE-011 的 200 保护），**没有覆盖 416**。而 `urllib` 对 4xx 直接抛 `urllib.error.HTTPError`，`r.status` 根本取不到——全代码库无一处 import 或识别 `HTTPError`，worker 层所有 4xx 都退化成了同一种普通错误，一律退避重试到耗尽。

**影响**　真实世界中「HEAD 声称支持 Range 但实际拒绝」的服务器不少见（部分对象存储、CDN、WAF 会如此配置）。这类文件本可单线程下载成功，却因探测误判 + 缺乏 416 判定而彻底失败。影响面限于此，但属于「功能不可用」。

**处置**　新增 `src/httpinfo.py` 承载 HTTP 语义判定，两条路径同时修：

- **`probe()` 阶段做确认探测**：即使 `HEAD` 声称 `Accept-Ranges: bytes`，也用 `Range: bytes=0-0` 再试一次。收到 416 即判定 `ranges=False`，并从 416 的 `Content-Range: bytes */<总长>` 取回文件总长。代价是一次额外请求，换来「下载开始前就知道能不能分段」。契约 CORE-024 记录这条义务。
- **`_worker` 侧按状态码分流**：`urllib` 对 4xx 直接抛 `HTTPError`，上层拿不到 `r.status`，必须按 `code` 分流（实现在 `httpinfo.py`）。**416** 视同「该源不支持分段」，记入 `_no_range_mirrors`（与 CORE-011 的 200 保护同一份名单）；全部源都 416 时置 `_fatal` 结束分片阶段，由 `_fetch` 退化 `_download_single`。**401/403/404 等永久错误**不按退避策略重试同一源，但允许换源再试一次（每个源至多一次）；全部源都永久失败才判定该分片失败。**408/429** 视为暂时性，仍按退避重试。

**验证**　`test_bug42_probe_reports_no_ranges_on_416`、`test_bug42_download_succeeds_when_416`、`test_bug42_worker_416_falls_back_to_single`、`test_bug42_permanent_error_no_full_retry`。

---

## BUG-43 · `schema_defaults` 的参数映射是手工白名单（P2）

**现象**　契约 CLI-013 要求「`defaults` 的每个键都要在 `args` 里有对应参数（归一化后），缺失即错」，但校验器的 `chk_schema_defaults` 遍历的是**契约块里手写的 `map` 清单**，而不是 `SCHEMA["defaults"]` 本身。`map` 与 `defaults` 一旦不同步，那个键就彻底没人看。

**绕过实验**（在副本上做，源码与契约同步改动）：

| 破坏 | 期望 | 实测 |
|---|---|---|
| `defaults` 新增孤儿键 `orphan: 7`（`args` 里无对应参数），不动 `map` | RED（缺失即错） | **GREEN**（`7 个默认值各写一处`） |
| `defaults` 新增 `brandnew: 7`，`args` 文案写「默认 7」，**只更新顶层指纹** | RED（默认值重复） | **GREEN，全套 25 项通过、退出码 0** |

第二条尤其要紧：它同时踩掉了「默认值只写一处」与结构指纹两条约束——指纹照规约更新后，整套校验看不出任何异常。

**根因**　`map` 是冗余的手工白名单。实测这 7 条映射**全部可由归一化反查得到**（`threads → -t/--threads`、`slow_sec → --slow-sec`、`max_speed → --max-speed`……），与 `chk_schema_defaults` 里已有的 `_norm_arg()` 完全吻合。既然 `_norm_arg` 已经能把 args 参数名归一化成 `defaults` 的键名，判据就该以 `SCHEMA["defaults"]` 为准遍历，`map` 至多作为「参数名带别名时的人工覆盖」，而不是决定检查范围的白名单。

**处置**　按建议把遍历对象从 `map` 改为 `SCHEMA["defaults"]`，并**两侧都查**：

| 方向 | 判据 | 不满足时 |
|---|---|---|
| `map` → `defaults` | `map` 的每个键都必须存在于 `defaults` | 报红：默认值被删了，契约没跟上 |
| `defaults` → `map` | `defaults` 的每个键都必须登记进 `map` | 报红：契约声明不完整（该默认值的文案仍按反查受检） |
| `defaults` → `args` | `defaults` 的每个键都要在 `args` 里有对应参数（归一化后） | 报红：缺失即错 |

实现上，遍历以 `SCHEMA["defaults"]` 为准（代码里的事实），参数名先用 `_norm_arg` 从 `args` 反查；`map` 保留为「显式登记」，其存在有两个作用：一是覆盖参数名与默认值键名不一致的情形，二是让「defaults 新增了键却没在契约里登记」这条本身成为可检出的漂移。

**后续（BUG-45）**　本条的修复把遍历对象换成了 `defaults`，但**参数名仍取自 `map`**——`map` 写错时，那条默认值仍能整体逃逸检查（BUG-43 是「键没登记」，BUG-45 是「键登记错了」，同根因）。参数名改为从 `args` 反查，`map` 降为被验证的声明，四个方向的判据见 `CONTRACT-cli.md` §5.2。

**计数一并修正**：PASS 信息里的「N 个默认值各写一处」取的是**实际 `defaults` 键数**，不是 `map` 的条目数——取 `map` 的条目数会在 `map` 少登记时报出偏小的数字，反而掩盖问题。

**验证**　`test_bug43_schema_defaults_detects_unmapped_default_key`（`defaults` 里有键却不在 `map` 里 → 必须报红并点名该键）、`test_bug43_schema_defaults_detects_map_key_absent_from_defaults`（`map` 里有键却不在 `defaults` 里 → 必须报红；且与前者同时失配时两条判据都要报出来，互不吞掉）。前者是本条缺陷的原始证据，修复后转绿；后者补齐反方向，两条合起来才是完整的双向核对。

---

## BUG-44 · `literal_dict` 检查没有自测用例（P3，已修）

**现象**　本轮新增的四类检查里，`const_used` / `no_private_access` / `call_site` / `schema_version` 都配了自测用例，唯独 `literal_dict`（契约 CLI-014）一条没有。它是**唯一一条没有任何用例守护的检查**——改坏了整套校验会静默失去这道防线，而这正是 BUG-31 立下的规矩：「安全网自己不能是纸糊的」。

**处置**　补两条用例：`test_bug44_literal_dict_detects_non_literal`（`SCHEMA` 里出现 f-string → 必须报红并点名 `JoinedStr`）、`test_bug44_literal_dict_accepts_literal`（纯字面量 → 不得误报，零误报是这条检查的前提）。

**验证**　`test_bug44_literal_dict_detects_non_literal`、`test_bug44_literal_dict_accepts_literal`。

---

## BUG-45 · `schema_defaults` 采信契约 map 的参数名，map 错接时该默认值不受检查（P2）

**现象**　契约 `map` 把 `slow_sec` 错接到 `--slow`（该参数存在，但不对应 `slow_sec`）时，`--slow-sec` 的文案即使复述了「默认 12」，检查也**完全不查它**——报的是绿。原因与 BUG-43 同根：**遍历的是手工维护的白名单 `map`**，而 `map` 里写的是哪个参数，就查哪个参数。

**绕过实验**（在副本上做，源码与契约同步改动）：

| 破坏 | 期望 | 实测（修复前） |
|---|---|---|
| `map` 把 `slow_sec` 写成 `--slow`，`--slow-sec` 文案改回「慢速持续秒数，默认 12」 | RED（文案复述了默认值） | **GREEN，全套 25 项通过、退出码 0** |

**根因**　实现的判据是「`map` 声明了什么就查什么」，而**代码里的事实是 `SCHEMA["defaults"]` 与 `SCHEMA["args"]` 两者**，它们的对应关系由归一化规则决定，不需要人工维护。实测这 7 条映射**全部可由 `_norm_arg` 反查得到**（`threads → -t/--threads`、`slow_sec → --slow-sec`、`max_speed → --max-speed`……）且无碰撞——`map` 对「查哪个参数」而言是冗余的。

**影响**　这是 BUG-43 的**另一种形态**：BUG-43 是「键没登记进 map」，本条是「键登记错了」。两者根因相同——手工维护的白名单会与代码漂移。当下无实际影响（现有 7 条经实测与反查结果完全一致），触发条件是维护者把 `map` 写错。但触发条件恰好是本项目最该防的场景。

**处置**　按契约 CLI-013 已写明的口径改实现：**遍历以 `SCHEMA["defaults"]` 为准**，参数名用 `_norm_arg` 从 `args` 反查；契约 `map` 从「事实源」降为「被验证的声明」——它把某个默认值声明到不对应的参数上时同样报红。

四个方向都要查：

| 方向 | 判据 |
|---|---|
| `defaults` → `args` | 每个默认值键都要在 `args` 里有对应参数（反查得到） |
| `map` → `defaults` | `map` 的每个键都必须存在于 `defaults` |
| `map` → 反查结果 | `map` 声明的参数经归一化后必须等于它声明的默认值键 |
| `defaults` → `map` | `defaults` 的每个键都必须登记进 `map` |

**验证**　`test_bug45_schema_defaults_reverse_lookup_from_args`（默认值键在 args 里无对应参数 → 报红）、`test_bug45_schema_defaults_detects_map_mispointing`（map 错接 → 报红并点名）、`test_bug45_schema_defaults_catches_text_under_wrong_map`（回归护栏：map 错接时该默认值的文案复述仍须报红）。

三条用例与实现互为交叉验证：变异测试显示，删掉「从 args 反查」判据则用例报红，删掉「map 与反查结果一致」判据则用例报红。

---

## 处置记录

2026-10-31 的一轮处置按以下次序完成：P0 缺陷（BUG-01、BUG-15、BUG-02）→ P1 缺陷（BUG-16、BUG-06、BUG-10、BUG-17、BUG-07）→ P2 与 P3（BUG-08、BUG-09、BUG-12、BUG-14）→ 工具缺陷（BUG-18）。其中 BUG-13 经复核改判，未修改代码。

随之发生的结构调整：`downloader.py` 因新增预检与指纹逻辑一度增至 921 行，触及 CODE-003 的上限，按规约将错误翻译表拆至 `netio.py`，最终为 875 行。契约同步更新 CORE-006 / 012 / 016 / 020，新增 CORE-021 / 022 / 023；DATA-004 增加 `.part.json`；新增 GUI-010。

测试用例由 32 例增至 51 例，契约校验项由 16 项增至 17 项。

同日第二轮处置来自项目评审（`docs/REVIEW.md`），共 10 条：BUG-19 至 BUG-28，覆盖加速源接入、退出码判定、分段退化判据、文件名截断、私有属性越界、指纹版本校验、构建日志口令、共享状态加锁、死常量与 BaseException。评审提出的其余条目列入「待处理项」（BUG-29 至 BUG-37）。

第三轮处置覆盖评审提出的其余条目与复评发现的问题，共 14 条（BUG-29 至 BUG-42），按主题分四组：

1. **接口收敛**（BUG-29 / BUG-30 / BUG-41）：job 参数优先级改用 `None` 哨兵；删除引擎层的第二套命令行解析器，`dl.py` 成为唯一入口（契约新增 CLI-010）；`GITHUB_MIRRORS` 不再经引擎再导出。
2. **精度修正**（BUG-32 至 BUG-35）：进度与合并校验统一到 `_credited` 单一判据（契约新增 CORE-025）；测速的计时起点移到响应头到达之后；限速改为先取配额再落盘。
3. **契约与校验器**（BUG-31 / BUG-36 / BUG-37）：校验器补四类可执行检查并加强两项既有检查（契约新增 CODE-011 ~ CODE-015）；`SCHEMA.version` 升到 2 并纳入结构指纹约束（契约新增 CLI-011）；progress 节流文案与实现的 OR 语义对齐（契约新增 CLI-012）。
4. **界面与措辞**（BUG-38 / BUG-39 / BUG-40）：剪贴板引入「用户已接管输入」状态机（契约新增 GUI-011）；限速措辞统一为「每任务限速」；CODE-002 的依赖清单与分层图修订，与实现对齐。

第四轮由 QA 的独立验证发现：新增的检查若只会报 PASS 就是没用的。按「故意破坏 → 确认报红」逐项验证，`schema_defaults` 被查出方向反了的漏洞（只遍历契约 `map`，未登记的 `defaults` 键静默逃逸，登记为 BUG-43），已改为两侧都查。

同轮 QA 复验时又查出 `schema_defaults` 的第二个漏洞（BUG-45）：实现采信契约 `map` 里的参数名，而不是从 `args` 反查——`map` 把一个默认值错接到别的参数上时，那条默认值的文案复述就完全不被检查。已改为以 `SCHEMA["defaults"]` 为准遍历、从 `args` 反查参数名，`map` 降为被验证的声明。两条漏洞同根：手工维护的白名单会与代码漂移（BUG-43 是「键没登记」，BUG-45 是「键登记错了」）。

第五轮由 QA 的独立验证与复评共同查出：契约 `map` 被校验器当作**事实源**采信，map 写错时该默认值整体逃逸检查（登记为 BUG-45）。这与 BUG-43 同根因——手工维护的白名单会与代码漂移——但形态不同：BUG-43 是「键没登记」，BUG-45 是「键登记错了」。处置方向是把 `map` 从事实源降为被验证的声明：遍历改以 `SCHEMA["defaults"]` 为准，参数名从 `args` 反查，map 本身也受校验。

契约校验项由 17 项增至 25 项，测试用例由 68 例增至 98 例。

---

作者：shanshuifeng ｜ 项目地址：https://github.com/shanshuifeng/Download-tool ｜ 许可：Apache-2.0（见 `LICENSE`）
