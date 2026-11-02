# 修复计划

依据：2026-10-31 对 `BUGS.md` 的逐条核实（14 条：3 条已修、10 条成立、1 条根因错误）
外加 3 条核实中发现的缺陷，本计划中记为 BUG-15/16/17，W0 阶段补入 `BUGS.md`。

本计划说明修复范围、执行次序与逐条做法，不含工时估算，改动量以代码行数计。

---

## 0. 完成定义（DoD）

一条缺陷只有满足下列之一才算关闭，不接受「改完看着没问题」：

| 关闭方式 | 适用 | 证据要求 |
|---|---|---|
| 改代码 | 行为错误 | 新增测试先红后绿，测试体内标注 `BUG-xx` |
| 改契约 | 契约与实现不符且实现合理 | 契约条目改写 + 校验器仍全绿 |
| 改判 | 缺陷本身判错 | 在 `BUGS.md` 写明反例与复现方法 |

整体验收：

1. `python docs/verify_contract.py` 全绿（当前 16 项，检查项数量不变，覆盖面扩大到两个新模块）
2. `python -m unittest discover -s tests` 全绿（计划时 32 例，实际 50 例）
3. 三个入口可启动：`downloader.py --help`、`dl.py --schema`、`gui.pyw`
4. `CODE-003` 行数上限不破；`--json` 字段、退出码、`DownloadTask` 参数、`config.json` 键均无破坏性变化
5. `build_and_sign.py --no-sign` 能出 exe；便携 zip 内是本次新 exe

---

## 1. 修复边界

### 1.1 范围边界（纳入）

| 波次 | 内容 | 性质 |
|---|---|---|
| W1 | BUG-01、BUG-15、BUG-16 | 数据正确性 |
| W2 | BUG-17、BUG-06+10、BUG-08、BUG-02+04 | 稳定性与体验 |
| W3 | BUG-09、BUG-12、BUG-14、BUG-07、BUG-13 | 清理与改判 |
| W4 | 契约、README、变更记录、版本号 | 收口 |

### 1.2 明确不做（划界）

| 项 | 理由 |
|---|---|
| REQ-008b 动态切分片 | 已在 REQ 中定案不做，改动会破坏 `meta.json` 续传稳定性 |
| 全局 `\\?\` 长路径支持 | 会改变所有路径语义、污染界面显示；改为提前拒绝（BUG-08） |
| 强制镜像下载必须带哈希 | 代码层无法验证；只能文档 + 运行时 warn（BUG-07） |
| FAT32 下超 4GB 分卷输出 | 属于新功能，不是修缺陷；只做提前拒绝 |
| `_PATH_LOCKS` 引用计数回收 | 收益（每路径约 100B）小于风险（会改动互斥语义、破坏 `test_same_path_conflict` 的直接加锁用法）；改为契约写明「进程内按路径缓存」 |
| 单线程路径补重试/慢链判定 | 契约未承诺，属新需求；另开 REQ |
| 引入任何第三方库、改异步模型、换 UI 框架 | 触碰项目立身之本 |
| 已发布 exe 的签名流程 | 与本次修复无关 |

### 1.3 接口红线（不许动）

- `dl.exe --json` 的 `progress/done/error` 字段：只增不改
- 退出码 0/1/2/3/130 的语义
- `DownloadTask.__init__` 既有参数的名字、顺序、默认值
- `config.json` 既有键的语义；新增键必须有默认值
- `meta.json` 既有字段；新增字段必须可缺失
- `DownloadQueue.add/cancel/stats/state_of` 的签名（只新增 `forget`）

### 1.4 改动边界（每项只碰这些地方）

| 缺陷 | 允许改动的范围 | 禁止波及的内容 |
|---|---|---|
| BUG-01 | `probe()` 的 `if not size`、`_measure_mirror()` 的同类判断 | 不动 `rank_mirrors` 排序 |
| BUG-15 | 新增 `src/resume.py`、`_download_single` | 不动分片路径的 `meta.json` 逻辑 |
| BUG-16 | `DownloadQueue.add`、`_run_one` 的取任务处 | 不动 `cancel` 语义 |
| BUG-17 | `_measure_mirror` 的读取循环 | 不改测速窗口大小与排序 |
| BUG-06/10 | 新增 `src/diskutil.py`、`run()` 预检、两条写入路径、合并 | 不改分片大小与线程模型 |
| BUG-08 | `diskutil.check_target`、`run()` 中 `out` 确定后一处 | 不改 `_safe_name` 的 120 字符上限 |
| BUG-02/04 | `taskqueue.forget`、GUI `_task_action` + 清除入口 | 不改队列并发语义、不改状态机 |
| BUG-09 | `_verify` 记录结果、`dl.main` 复用 | 不改 `done` 事件字段名 |
| BUG-12/14 | 导入行、两处折行 | 不重排其他代码 |

### 1.5 规模预算（`CODE-003` 硬约束）

当前余量：

| 文件 | 现有 | 上限 | 余量 |
|---|---|---|---|
| `downloader.py` | 842 | 900 | **58** |
| `netio.py` | 162 | 260 | 98 |
| `taskqueue.py` | 125 | 220 | 95 |
| `dl.py` | 262 | 400 | 138 |
| `gui.pyw` | 896 | 1100 | 204 |

本轮 `downloader.py` 预计净增 85～95 行，**必然超限**。因此先拆两个叶子模块，再改主逻辑：

- `src/diskutil.py`（≤160 行）：剩余空间、文件系统类型、路径长度预检、ENOSPC 判定
- `src/resume.py`（≤90 行）：`<out>.part.json` 的读写与比对

拆完 `downloader.py` 净增约 45 行（887 行）。**硬规则**：每波结束若 `downloader.py` 超过 895 行，先拆模块再继续，不允许改上限。

---

## 2. 修复路线

### 2.1 波次与依赖

```
W0 基线（把 15/16/17 写成失败测试）
 └─ W1 正确性：01 ─┬─ 15 ─┬─ 16
                  └───────┘（三项互不依赖，按此顺序提交）
      └─ W2 稳定性：17 → 06+10（同一条写入路径）→ 08 → 02+04
           └─ W3 清理：09、12、14、07、13（13 只改文档）
                └─ W4 收口：契约、README、版本、出包
```

串行而非并行：15、06/10、08 都要改 `_download_single`/`run()`，并行必冲突。

**契约先行**：每波第一件事是改 `CONTRACT-*.md` 并跑校验器确认「按预期失败」，再改代码。这是项目既有协议（`docs/README.md` 变更协议第 1 条）。

### 2.2 每波门禁

| 门禁 | 命令/动作 |
|---|---|
| 契约 | `python docs/verify_contract.py`（预期：新条目失败 → 改完转绿） |
| 单测 | `python -m unittest discover -s tests` |
| 规模 | `verify_contract.py` 的 `max_lines` 项 |
| 入口 | 三个入口各启一次；GUI 改动需人工点一遍 |
| 提交 | 一项一 commit，消息带编号：`fix(BUG-01): 0 字节文件...` |

### 2.3 提交粒度

一项一个 commit，便于单独回滚。W4 单独一个 `docs:` commit。版本号只在 W4 改，避免中间态。

---

## 3. 修复方法

### W0 · 基线

1. 记录当前 32 例测试、16 项契约全绿。
2. 把核实阶段的三个复现脚本转成 `tests/test_bugs.py` 的失败用例（BUG-15/16/17），确认在当前代码上确实红。
3. `BUGS.md` 总览表加「验证方式」列（取值：测试 / 静态 / 文档 / 人工 / 改判），并补 BUG-15/16/17 三行。

### W1 · 数据正确性

#### BUG-01 · 0 字节文件（P0，约 4 行）

- `probe()`：`if not size:` → `if size is None:`
- `_measure_mirror()`：`if not info["size"]:` → `if info["size"] is None:`；`size == 0` 时直接返回 `speed=0.0, failed=False`，省掉一次无意义的 256KB 请求（0 字节不会走分片，权重无影响）
- 契约：`CORE-006` 补一句「`size=0` 是合法值，`error` 仅在 `size is None` 时非空」

**测试**：`test_bug01_zero_byte` —— 0 字节源，`probe()["error"] is None`；`run()` 产出 0 字节文件；带 `sha256("")` 时校验通过。

**验收**：不再出现「所有下载源都不可用」；`.parts` 不产生。

#### BUG-15 · 单线程续传无指纹（P0，新增，约 45 行 + 新模块）

**事实**：`.part` 只按大小续传，远端换成同长度内容后，产物既非旧也非新，`run()` 正常返回、不隔离。

**改法**：

1. 新增 `src/resume.py`：

```python
def meta_path(out):        return out + ".part.json"
def load(out):             ...  # 读不到/坏 JSON 一律返回 None
def save(out, *, size, etag, url):  ...  # 先写 .tmp 再 os.replace
def matches(meta, size, etag): ...      # size 必比；当前 etag 与 meta 里都有值时必比
def clear(out):            ...  # 成功或放弃时删除
```

2. `_download_single` 开头：
   - `have > 0` 时读 sidecar；`matches` 为假 → 删 `.part`、`have = 0`、日志「服务器文件已变化，重新下载」
   - sidecar 缺失（旧版本遗留）→ 同样删除重下，一次性代价
   - `etag is None` → 允许续传，但打一条 `warn`「服务器未提供 ETag，续传无法检测同长度变更」
   - 开始下载前 `save(...)`；成功后 `clear(...)`；取消/失败保留双方
3. 契约：`CORE-012` 增加指纹规则；`DATA-004` 增加 `<out>.part.json` 一行（何时出现/消失）；`.gitignore` 加 `*.part.json`

**测试**（两条，缺一不可）：

- `test_bug15_single_resume_detects_change`：300KB 源 → 预置 100KB `.part` + 旧 etag → 换同长度新内容 → 产物必须等于新内容
- `test_bug15_single_resume_when_unchanged`：内容不变 → 产物正确，且服务端收到 `Range: bytes=102400-`（证明真的续传，没退化成全量重下）

**风险**：升级瞬间正在下载的旧任务会重下一次（sidecar 不存在）。在变更记录里写明。

#### BUG-16 · `add()` 与 `_pump()` 竞态（P1，新增，约 12 行）

**事实**：`add()` 释放锁后才写 `_tasks`，此时别的任务结束触发 `_pump()` 会把新 tid 取走启动 → `KeyError`，状态永久 `running`，`_running` 泄漏一个并发槽；`concurrent=1` 时队列彻底不动。

**改法**：先构造 task，再在同一把锁里一次性登记。

```python
def add(self, urls, out_path=None, **kw):
    box = {"tid": 0}
    def log(msg, level="info"): self._event("log", box["tid"], msg=msg, level=level)
    def progress(d): self._event("progress", box["tid"], data=d)
    task = DownloadTask(urls, out_path, log=log, progress=progress, **kw)
    with self._lock:
        self._seq += 1
        tid = box["tid"] = self._seq
        self._tasks[tid] = task
        self._state[tid] = "queued"
        self._pending.append(tid)
    ...
```

另加防御：`_run_one` 用 `self._tasks.get(tid)`，取不到就置 `failed` 并清 `_running`，不让异常线程吞掉槽位。

**测试**：`test_bug16_add_pump_race` —— 假任务 `__init__` 用 `threading.Event` 卡住第二个任务，等第一个任务结束；断言无 `KeyError`、第二个任务最终 `done`、`_running` 为空。

### W2 · 稳定性

#### BUG-17 · 测速无界读取（P1，新增，约 6 行）

`_measure_mirror` 的 `r.read()` 会把忽略 Range 的源整个响应读进内存（32MB 源实测峰值 48MB）。

```python
got, limit = 0, 256 * 1024
while got < limit:
    buf = r.read(min(BLOCK, limit - got))
    if not buf: break
    got += len(buf)
```

**测试**：`test_bug17_measure_bounded` —— 32MB 忽略 Range 的源，`tracemalloc` 峰值 < 8MB，且 `speed > 0`。

#### BUG-06 + 10 · 磁盘预检与 ENOSPC（P1/P2，约 100 行 + 新模块）

新增 `src/diskutil.py`：

```python
FAT32_MAX = 4 * 1024**3 - 1
MAX_PATH_SAFE = 259

def existing_parent(path): ...        # 目标目录还不存在时向上找已存在的祖先
def fs_type(root): ...                # ctypes.GetVolumeInformationW，非 Windows/失败返回 None
def check_target(path, size):
    """路径长度 → FAT32 → 剩余空间。任何探测失败都放行，不能因预检阻断下载。"""
def is_disk_full(exc): ...            # errno.ENOSPC 或 winerror in (39, 112)
```

`run()` 在 `out` 确定后、`os.makedirs` 之前调用 `check_target`。拒绝阈值：

- 路径：`len(abspath) + 18 > MAX_PATH_SAFE`（18 = `.parts\part0000` 的最长后缀）→「保存路径过长（当前 N 字符），请换浅一点的目录」
- FAT32 且 `size > FAT32_MAX` →「目标盘是 FAT32，单文件上限 4GB；请换 exFAT/NTFS 或改存本地」
- 空间：`free < size * 1.05 + 64MB` →「空间不足：需要 X，可用 Y」
- `size < free < size * 2` 且会走分片：打 `warn`「余量偏紧，合并阶段可能失败」（合并时 parts 与新文件并存）

ENOSPC 快速失败：

- 抽 `_write(f, buf)` 供两条路径使用（同时给测试一个注入点）
- `_worker` 捕获后设 `self._fatal = DownloadError("磁盘空间不足…")` 并 `return`；`pump` 每轮检查 `_fatal` 提前退出；主线程 join 后优先抛 `_fatal`
- `_download_single` 直接抛
- 合并阶段的 `truncate/copyfileobj` 包一层；失败时删掉半成品输出、保留 `.parts`

**测试**：

- `test_bug06_space_precheck`：`shutil.disk_usage` 打桩返回 1MB，10MB 文件 → 立刻报「空间不足」，不产生 `.parts`
- `test_bug06_fat32_reject`：`diskutil.fs_type` 打桩返回 `FAT32`，5GB → 报 FAT32；3GB → 放行
- `test_bug08_long_path`：352 字符路径 → 报「保存路径过长」，不建 `.parts`
- `test_bug10_enospc_fast_fail`：`_write` 打桩抛 `OSError(ENOSPC)` → 2 秒内失败、消息含「空间不足」、`.parts` 保留

**风险**：UNC/网络盘上 `disk_usage` 可能抛异常 → 一律放行（只记 debug，不阻断）。

#### BUG-02 + 04 · 队列统计与清理（P0/P1，约 30 行）

**事实**：`_state` 只增不减，GUI 删行只 `rows.pop`，队列无感知；完成行没有移除入口。

**改法**：

1. `DownloadQueue.forget(tid)`：
   - 仅终态（done/failed/cancelled）可移除，返回 `True`；`queued/running` 返回 `False`（不静默丢任务）
   - 删 `_state[tid]`，`_tasks`/`_running` 兜底 pop
   - 契约 `CORE-016` 同步：`_tasks` 终态释放、`_state` 保留到 `forget`、`_PATH_LOCKS` 进程内按路径缓存（已知限制，不回收）
2. GUI：
   - `_task_action` 删除行时调用 `queue.forget(tid)`
   - 底部汇总条加「清除已完成」文本按钮（仅当存在终态任务时显示）→ 遍历终态行 `forget` + `destroy` + 隐藏列表 + 刷新
   - 修正「打开」按钮：文件不存在时不再静默删行，改为提示「文件已被移动或删除」，按钮切到「移除」
   - 契约：`CONTRACT-gui.md` §5 状态表加一行、新增 `GUI-010`

**测试**：

- `test_bug02_forget_resets_stats`：3 个任务完成 → `forget` 一个 → `total=2`；对 running 的 `forget` 返回 `False`
- `test_bug02_clear_finished_gui`：注入两个终态行 → 调 `_clear_finished` → `rows` 空、列表隐藏、`stats()["total"]==0`

### W3 · 清理

#### BUG-09 · 重复哈希（P2，约 16 行）

- `_verify` 算出哈希时记 `self.actual_hash` / `self.hash_algo`
- `dl.main`：`expected` 存在且 `hash_algo == "sha256"` → 直接复用；否则（如期望值是 md5）单独算一次 sha256 填 `done.sha256`
- `--hash` 且未校验过 → 算一次

**测试**：`test_bug09_hash_single_pass` —— 统计传入 `update()` 的字节数，3MB 文件只能等于 3MB（当前是 6MB）。

#### BUG-12 · 死导入（P2，-2 行）

删除 `deque`、`UA`；保留 `_opener` 并注明「测试用再导出」，沿用行尾 `# noqa: F401`。

**测试**：`test_contract.py` 加 AST 静态检查（允许 `_opener` 白名单）。

#### BUG-14 · 超 100 列（P3，+1 行）

`downloader.py:138`、`gui.pyw:351` 折行。

**测试**：`test_contract.py` 加行宽检查（全 `src/` ≤100），让 `CODE-009` 从口头约定变成可执行。

#### BUG-07 · 镜像哈希（P1，文档 + 一行 warn）

- `run()` 在 `len(self.mirrors) > 1` 且未提供哈希时打一条 `warn`：「正在经镜像下载且未提供哈希，内容无法验证」
- README 新增「注意」条目；GUI `HELP_ROWS` 的 SHA256 说明补「经镜像下载强烈建议填」；`使用说明.txt` 同步
- 不改校验逻辑，不强制

#### BUG-13 · 改判（P3，无代码改动）

- `_distribute` 不动。穷举 1–40 片 × 10 组权重，0 权重源被分配 0 次；`max(0, w)` 已保证配额为 0，报告建议的「配额强制 0」是空操作
- `BUGS.md` 该条改为「不成立」，附反例方法与实测结论
- 真实存在的小问题（speed=0 的源仍留在 `mirrors`，重试轮换会打到它）写进「已知行为」，不当作缺陷修

### W4 · 收口

1. `BUGS.md`：总览状态全部更新；15/16/17 标为已修并挂验证方式；「修复顺序建议」改为指向本文件；03/05/11 正文补「已修 + 验证方式」
2. 契约：`CORE-006/012/016/020`、新增 `CORE-021/022/023`、`DATA-004`、`GUI-010`、`CODE-003`、分层图
3. `docs/verify_contract.py`：`stdlib_only` 与 `max_lines` 加入两个新模块
4. `README.md`：版本表 1.1.0.0、镜像哈希注意项、续传 sidecar 说明
5. `docs/README.md`：变更记录补 v1.7、修正 v1.5/v1.6 顺序、把「反向检查锚点」改为与实现一致的措辞
6. 版本资源：`build/version_info*.txt` → 1.1.0.0
7. 出包：`python build_and_sign.py --no-sign --no-deploy`，检查产物；便携 zip 内 exe 时间戳为本次构建

---

## 4. 契约与文档同步清单

| 文件 | 改什么 |
|---|---|
| `CONTRACT-engine.md` | CORE-006（size=0）、CORE-012（单线程指纹）、CORE-016（forget/_state/_PATH_LOCKS）、CORE-020（体积上限 + 空间预检）、新增 CORE-021/022/023 |
| `CONTRACT-data.md` | §2 删除「待实现 concurrent/clipboard_watch」；§4 增加 `<out>.part.json` |
| `CONTRACT-gui.md` | §5 状态表加「清除已完成」；新增 GUI-010；done 行文件缺失的行为 |
| `CONTRACT-code.md` | §2 分层图加 `diskutil`/`resume`；§3 上限加两模块 |
| `REQ.md` | 不动（本轮是缺陷，不新增需求） |
| `BUGS.md` | 状态、验证方式列、13 改判、15/16/17 新增 |
| `README.md` | 版本号、镜像哈希注意、续传中间文件 |
| `docs/README.md` | 变更记录、锚点检查措辞、版本顺序 |
| `.gitignore` | `*.part.json` |

新增契约编号与实现的对应：

| 编号 | 内容 | 锚点位置 |
|---|---|---|
| CORE-021 | 单线程续传必须核对 `size` 与 `etag`，不符即丢弃 `.part` | `_download_single` |
| CORE-022 | 写入遇 ENOSPC 立即中止，不进退避重试 | `_write` / `_worker` |
| CORE-023 | 下载前检查路径长度与 FAT32 单文件上限 | `run()` 的 `check_target` 调用处 |

---

## 5. 回归与发布

**回归四件套**（每波都跑）：

1. 契约校验
2. 全量单测
3. 三条真实链路：小文件单线程、大文件分段、服务器忽略 Range 退化
4. GUI 手工：并发 1 连开 3 个任务、取消→移除→汇总归零、清空已完成

**发布前额外**：

- 0 字节、FAT32 拒绝、磁盘满、352 字符路径四个场景各手工走一遍（测试里是打桩，真机再确认）
- 用 350MB 的真实镜像链接重跑 README「实测」那一节，确认测速有界读没有把速度测低
- `--no-deploy` 出包，确认 exe 能起、`dl.exe --schema` 正常

**回滚**：按波次 revert commit 即可。新增的 `.part.json` 是附加文件，回滚后旧代码会忽略它并按大小续传（即旧行为），不会产生坏文件之外的额外风险。

---

## 6. 风险登记

| 风险 | 影响 | 处置 |
|---|---|---|
| sidecar 让在途任务重下一次 | 一次性流量 | 变更记录写明；日志说明原因 |
| 预检在 UNC/网络盘误判 | 下载被挡 | 探测异常一律放行 |
| 空间阈值 1.05 偏乐观 | 合并阶段仍可能满 | 余量 < 2× 时 warn；ENOSPC 快速失败兜底 |
| `forget` 与事件竞争 | GUI 找不到行 | `_on_task` 已有 `rows.get` 空判断；只允许终态 forget |
| 竞态测试依赖时序 | 偶发不红 | 用 `threading.Event` 而非 sleep，事件驱动 |
| 拆模块触碰分层契约 | 校验器报错 | 先改 `CONTRACT-code` 再动代码 |
| `downloader.py` 再次超限 | 打包前检查失败 | 895 行预警线，超了先拆 |

---

## 7. 执行结果（2026-10-31，第一轮）

- 测试：32 → **50 例**全绿；契约校验 **16 项全绿**
- 行数：`downloader.py` 842 → 875（本轮峰值 921，按 `CODE-003` 把错误翻译表拆到 `netio.py` 后回落）；
  `netio.py` 216；新增 `diskutil.py` 114、`resume.py` 73，均在新的上限内
- 出包：`build_and_sign.py --no-sign --no-deploy` 成功，版本 1.1.0.0；
  打包后的 `dl.exe` 端到端冒烟 4 项通过（5MB+sha256、5MB+md5、0 字节、退出码 3）
- 偏差：BUG-09 顺带修了 `done.verified` 在 md5 期望值下误报 `false`（与原缺陷同段代码，已补测试）
- 新增：BUG-18 —— 收口时发现校验器 `check_anchors` 只扫根目录，v1.6 目录重组后「0 处锚点」空转；
  补扫 `src/` 后 21 处锚点重新生效，并加测试守住
- BUG-13 按计划改判，未改代码；`_distribute` 保持原样
- 后续（v1.8）：打包合并为单个 `下载工具.exe`，`dl.exe` 不再单独出包；本文件里提到 `dl.exe` 的地方是当时的真实产物

---

## 8. 执行结果（2026-10-31，复评整改轮）

- **处置范围**：BUG-29 ~ BUG-44 共 16 条（其中 BUG-42 由第一轮完成、本轮补登记）。
  缺陷总数 44 条：43 条已修，1 条经复核改判不成立（BUG-13）
- **测试**：50 → 62 → **98 例**全绿；契约校验 **16 → 17 → 25 项**全绿，零 SKIP
- **行数**：`downloader.py` 875 → 818（删掉引擎层第二套命令行解析器）；
  `dl.py` 316 → 330；`gui.pyw` 1003 → 1011；`netio.py` 219；`taskqueue.py` 154；
  `diskutil.py` 117；`resume.py` 79；`mirrors.py` 62；新增 `naming.py` 77、`httpinfo.py` 128，均在 `CODE-003` 上限内
- **契约新增的检查类型**：`schema_version`（接口版本与指纹同步性）、`schema_defaults`（默认值只写一处）、
  `literal_dict`（`SCHEMA` 保持纯字面量）、`const_used`（常量必须真被使用）、
  `no_private_access`（不得越界访问私有符号）、`call_site`（契约行为落地）
  —— 加上对 `max_lines`（未定义即失败）与 `req_tests`（标记必须在 docstring 且用例须有效）的原地加强
- **契约新增条目**：CLI-010（唯一命令行入口）、CLI-011（`SCHEMA.version` 递增义务）、
  CLI-013（默认值只写一处）、CLI-014（`SCHEMA` 保持纯字面量）、
  CODE-011 ~ CODE-017（校验器自身的检查项与其语义）
- **本轮修掉的实现级缺陷**：进度与合并校验统一到 `_credited` 单一判据（BUG-32/33）、
  测速计时起点移到响应头之后（BUG-34）、限速改为先取配额再落盘（BUG-35）、
  剪贴板「用户接管输入」状态机（BUG-38）、限速措辞统一为「每任务限速」（BUG-39）、
  引擎层删除 `main()` 使 `dl.py` 成为唯一命令行入口（BUG-30）、
  `GITHUB_MIRRORS` 不再经引擎再导出（BUG-41）

### 8.1 两条方法论教训

**教训一：「报红信息本身也是契约的一部分，必须与实现同源」**

实施过程中，`schema_version` 的报红信息一度把 payload 键集**硬编码**成旧的三键
（`args` / `events` / `exit_codes`），而实现已改成全键口径。于是报错信息在**说谎**：
它会让维护者以为「内容变了」，而实际上可能是「口径变了」——排查方向从第一步就偏了。

诊断信息看着只是多打几个字，实际救过一次误判。**契约对诊断信息的要求与对判据的要求同等严格**：
键集与实算指纹必须由实际 payload 派生，不得硬编码。这条已写进 `CONTRACT-code.md` §11.2 与
`CONTRACT-cli.md` §5.1。

**教训二：「新增的检查若只会报 PASS 就是没用的」**

QA 按「故意破坏 → 确认报红」的清单逐项独立验证时，查出 BUG-43：
`schema_defaults` 的实现只遍历**契约 `map` 里手写登记的键**，于是 `SCHEMA["defaults"]` 里
多出来、却没登记进 `map` 的键**整体逃逸检查**——它的文案有没有复述默认值、有没有对应的 args
参数，全都没查，而校验器还报着「N 个默认值各写一处」的绿。

工程师自带的用例之所以全绿，是因为它们只覆盖了「按 map 登记的内容」这一个方向。
**检查本身也需要被反向验证**，否则它可能一直在空转——这与此前 `check_anchors` 空转一轮
（BUG-18）是同一类陷阱的第二次发生。写检查时必须同时问两个问题：
「该红的时候红了吗」与「不该红的时候红了吗」，缺一不可。

**教训三：「反向验证会连着挖出第二个漏洞」**

QA 复验 BUG-43 的修复时，按同一套手法又挖出 BUG-45：`schema_defaults` 虽已补上
「漏登记」的检查，却仍在**采信契约 `map` 里声明的参数名**——`map` 把一个默认值错接到别的
参数上时，那条默认值的文案复述就完全不被检查，旧实现照样报绿。

两条漏洞同根：**手工维护的白名单会与代码漂移**，只是一个是「键没登记」，一个是「键登记错了」。
修法也不是补一条检查就了事——事实源必须是代码里的 `defaults` 与 `args`（对应关系由归一化
规则决定），契约 `map` 降为「被验证的声明」。**只要白名单还在决定「查哪个」，它就还会漂移。**

---

作者：shanshuifeng ｜ 项目地址：https://github.com/shanshuifeng/Download-tool ｜ 许可：Apache-2.0（见 `LICENSE`）
