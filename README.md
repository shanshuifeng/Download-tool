# 下载工具

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/shanshuifeng/Download-tool/blob/master/LICENSE)
[![CI](https://github.com/shanshuifeng/Download-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/shanshuifeng/Download-tool/actions/workflows/ci.yml)

Windows 平台的多线程分段下载器，仅依赖 Python 标准库。打包后为单个可执行文件，可放在移动介质上随身使用。

**项目地址**：https://github.com/shanshuifeng/Download-tool
**作者**：shanshuifeng

本文件面向使用者。接口契约、需求拆分与缺陷记录见 `docs/`，改动代码前请先阅读。

---

## 下载

| 渠道 | 内容 |
|---|---|
| [Releases](https://github.com/shanshuifeng/Download-tool/releases) | 每个版本提供 `DownloadTool.exe` 与 `DownloadTool-portable.zip`，由 GitHub Actions 构建。资产名用 ASCII：CI 在 Windows 上，中文文件名会在上传环节被代码页丢掉；程序本身与便携包内部仍是中文名「下载工具」 |
| 源码自行打包 | 参照下方「打包为单个 exe」，可得到带签名的产物 |

Releases 中的产物由 CI 构建，仓库不保存签名证书，因此**未签名**，Windows 会显示「未知发布者」，属预期现象。对文件完整性有要求的使用者，请以源码自行构建并校验哈希。

## 快速开始

| 目标 | 步骤 |
|---|---|
| 直接使用 | 安装 [Python 3.11+](https://www.python.org/downloads/windows/)（Windows 官方安装包已包含 tkinter，界面依赖它）→ 获取本仓库 → 双击 `src/gui.pyw` |
| 打包为单个 exe | 安装 Python 3.13 → 执行 `python build_and_sign.py --no-sign` → 产物位于 `%TEMP%\pyi_dist\DownloadTool.exe` |
| 供脚本或自动化调用 | 同一个 exe 带参数即进入命令行模式：`下载工具.exe "<URL>" -o "D:/a.zip" --json`，详见「自动化接口」 |
| 修改代码 | 先读 `docs/README.md`，其中说明契约体系与校验方式；完成后执行 `python docs/verify_contract.py` 与 `python -m unittest discover -s tests` |

本仓库只提供源码，不发布预编译产物。使用者需自行打包，或直接以源码方式运行。

使用前请先阅读「注意」与「常见问题」两节：工具仅支持 http/https 直链；经镜像下载的文件建议附带哈希校验值；FAT32 介质不支持大于 4GB 的单个文件。

### 运行条件

- **操作系统**：Windows 10 / 11。工具使用 per-monitor DPI 感知，并针对 FAT32 与长路径做了专门处理，目前仅在 Windows 上验证。
- **源码运行**：Python 3.11 及以上。命令行部分不依赖任何第三方库；界面部分需要 tkinter，官方安装包已包含。
- **打包**：Python 3.13（与已发布产物的字节码版本一致）、PyInstaller（构建脚本会在临时虚拟环境中自动安装）；Windows SDK 的 signtool 仅在签名步骤需要。

### 以源码方式运行

```bash
python src/gui.pyw                     # 界面
python src/dl.py "<URL>" -o "D:/下载"   # 命令行
python src/dl.py --schema              # 导出机器可读的接口描述
```

以源码方式运行时，配置文件写在 `src/config.json`。该文件已被忽略，删除即恢复默认设置。

### 打包为单个 exe

```bash
python build_and_sign.py              # 校验 → 打包 → 签名 → 部署 → 生成便携包
python build_and_sign.py --no-sign    # 仅打包（无 Windows SDK 时使用）
python build_and_sign.py --no-deploy  # 仅出包，不修改桌面与便携目录
```

产物位于 `%TEMP%\pyi_dist\DownloadTool.exe`。执行部署会将其复制到桌面与 `build/便携版/`，并生成 `下载工具_便携版.zip`。

签名需要本机的证书与口令，口令仅从环境变量 `DLTOOL_PFX_PASSWORD` 读取，仓库不保存任何口令。未设置该变量时使用 `--no-sign` 即可完成打包。

---

## 目录结构

以下是本地完成打包后的目录形态，仓库中仅包含源码部分。

```
桌面/
├── 下载工具.exe            # 双击运行
├── 下载工具_便携版.zip      # 解压到移动介质即可使用
└── 下载工具/               # 项目根目录
    ├── README.md
    ├── 使用说明.txt          # 面向最终用户的一页纸说明
    ├── job.example.json      # 命令行任务文件的示例
    ├── LICENSE               # Apache-2.0 许可全文
    ├── build_and_sign.py     # 一条命令完成：校验 → 打包 → 签名 → 部署 → 便携包
    ├── src/                  # 源码（10 个模块，全部为标准库）
    │   ├── downloader.py     #   下载引擎：探测 / 分片 / 校验
    │   ├── taskqueue.py      #   多任务调度：并发上限、排队、取消
    │   ├── netio.py          #   传输层：UA、代理（HTTP/SOCKS5）、_request
    │   ├── httpinfo.py       #   HTTP 语义判定与资源探测（416 / 永久错误）
    │   ├── naming.py         #   文件名规整（穿越、非法字符、扩展名）
    │   ├── mirrors.py        #   GitHub 加速源策略
    │   ├── diskutil.py       #   落盘预检：空间、FAT32、路径长度、ENOSPC
    │   ├── resume.py         #   单线程续传指纹（.part.json）
    │   ├── dl.py             #   唯一的命令行 / 自动化接口
    │   └── gui.pyw           #   唯一入口：带参数走命令行，无参数开界面
    ├── assets/               # icon.ico / icon.png
    ├── tests/                # 98 个用例（本地假服务器，不访问外网）
    ├── docs/                 # 契约文档、需求拆分、缺陷报告、校验器
    └── build/                # 构建配置与产物
        ├── version_info.txt  #   版本资源（入库）
        ├── signing/          #   自签名证书（不入库）
        ├── 便携版/           #   一份 exe 与便携 zip（不入库）
        └── _backup_*/        #   部署前的历史 exe（不入库）
```

## 仓库收录范围

推送到 GitHub 的内容限于：`src/`（源码）、`tests/`（用例）、`docs/`（契约、需求、缺陷报告、校验器）、`assets/`（图标）、`build/version_info.txt`（版本资源）、`README.md` / `使用说明.txt` / `job.example.json` / `LICENSE`。

不收录：可执行文件与压缩包等构建产物、`build/signing/` 中的自签名证书与私钥、运行期产生的 `config.json`、分片与续传指纹、部署历史备份、虚拟环境与编辑器配置。完整规则见 `.gitignore`。

---

## 界面

单窗口结构：链接输入框、保存位置、任务列表、底部汇总。全部调节项收在「高级设置」中，默认折叠。右上角「参数说明」逐条解释每个调节项的作用与适用场景。

| 调节项 | 取值范围 | 默认值 | 调整场景 |
|---|---|---|---|
| 线程数 | 1–32 | 16 | 家庭宽带 8–16 较合适，过高易触发服务端限速 |
| 分片大小 | 自动 / 1–32MB | 自动 | 超大文件可固定为 8–16MB，降低单片重试成本 |
| 慢速断开 | 0–200 KB/s | 15 | 0 表示关闭；跨境线路可适当调低 |
| 慢速时长 | 3–60 秒 | 12 | 过短会频繁重连，过长则等待时间增加 |
| 重试次数 | 0–20 | 6 | 网络质量差或镜像较多时调大 |
| 连接超时 | 5–120 秒 | 30 | 慢速线路可调整至 45–60 |
| 每任务限速 | 0–10240 KB/s | 0（不限） | 0 表示不限速；限速作用于单个任务，并发多个任务时合计速率会更高；启用限速后不再判定慢链路 |
| 代理 | — | 空 | 留空则跟随系统代理；`direct` 强制直连；也可填 `http://127.0.0.1:7890` 或 `socks5://127.0.0.1:7891` |
| 并发任务 | 1–4 | 2 | 同时下载的文件数量，过多会相互抢占带宽 |
| SHA256 | — | 空 | 填写后下载结束立即校验（md5/sha1/sha256/sha512 按长度自动识别） |
| 额外镜像 | — | 空 | 以逗号分隔的镜像前缀，拼接在链接之前 |

设置自动保存。窗口高度随高级设置面板的展开状态调整，按内容所需高度撑开。

程序声明 per-monitor DPI 感知，并按系统缩放比例（125% / 150% / 200%）重新计算全部尺寸与线宽，高分屏上的文字与 1px 分隔线保持清晰。

## 命令行（源码方式）

```bash
python src/dl.py "<URL>" -o "D:\下载" -t 16
python src/dl.py "<URL>" -o "D:\a.zip" --sha256 <哈希>
```

命令行入口只有 `dl.py` 一个（契约 CLI-010）。`src/downloader.py` 是纯引擎，直接运行它只会提示改用 `dl.py`。

## 自动化接口

同一个可执行文件承担界面与命令行两种模式：

| 调用方式 | 模式 | 适用场景 |
|---|---|---|
| 双击 `下载工具.exe` | 界面 | 手动下载 |
| `下载工具.exe "<URL>" -o ...` | 命令行 | 脚本、批处理、CI、自动化调用 |

命令行模式不弹窗、不需要交互，参数进、事件出、以退出码表达结果。该模式为控制台子系统，批处理中的退出码、管道与重定向均正常。双击启动时会自动隐藏随附的控制台窗口；从终端启动时不会影响用户终端，如需在终端中打开界面可使用 `start 下载工具.exe` 或 `下载工具.exe --gui`。

接口名称仍为 `dl`，`--schema` 的输出格式保持不变，既有调用将可执行文件名替换为 `下载工具.exe` 即可。

### 基本调用

```bash
下载工具.exe "<URL>" -o "D:/下载"                 # 保存到目录，沿用服务端文件名
下载工具.exe "<URL>" -o "D:/a.zip" -t 32          # 指定文件名与线程数
下载工具.exe "<URL>" -o "D:/dl" --sha256 <哈希>    # 下载结束后校验
下载工具.exe "<URL>" --mirror https://ghfast.top/  # 追加镜像前缀
下载工具.exe --job job.json --json                 # 从任务文件读取参数
下载工具.exe --schema                              # 导出机器可读的接口描述
```

### 参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `<url>...` | 位置参数，可传多个（视为同一文件的镜像） | 必填 |
| `-o, --out` | 保存目录或完整文件路径 | 必填 |
| `-t, --threads` | 并发分片数，1–64 | 16 |
| `--sha256` | 期望哈希，sha1/md5 自动识别 | — |
| `--chunk` | 每片 MB，0 表示自动 | 0 |
| `--slow` | 慢速阈值 KB/s，0 表示关闭 | 15 |
| `--slow-sec` | 慢速持续秒数 | 12 |
| `--retries` | 单片重试次数 | 6 |
| `--timeout` | 连接超时秒数 | 30 |
| `--proxy` | HTTP/HTTPS 代理；`direct` 强制直连；省略则跟随环境变量 | — |
| `--max-speed` | 每任务限速 KB/s，0 表示不限；并发多任务时合计速率高于设定值 | 0 |
| `--mirror` | 镜像前缀，可重复指定 | — |
| `--hash` | 下载后计算并输出 sha256 | 关闭 |
| `--json` | 输出 JSON Lines 事件流 | 关闭 |
| `--quiet` | 不输出进度，仅给出最终结果 | 关闭 |
| `--job` | 从 JSON 文件读取参数 | — |
| `--schema` | 输出接口描述后退出 | — |

### JSON 事件流

`--json` 时标准输出每行一个 JSON 对象：

```json
{"event":"progress","percent":82.5,"done":3699710,"total":4486142,"speed":61549,"eta":12}
{"event":"done","path":"D:////dl////a.zip","size":4486142,"sha256":"d31f...","sha256_expected":"d31f...","verified":true,"elapsed":77.9,"avg_speed":57585}
{"event":"error","code":3,"message":"所有下载源都不可用..."}
```

- `progress` 距上次输出满 1.5 秒，**或**百分比变化达到 1% 时才输出（OR 关系）
- `eta` 在速度过低时为 `null`
- `sha256` 为实际计算值，`sha256_expected` 为传入的期望值，`verified` 为比对结果

### 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 下载或校验失败 |
| 2 | 参数错误 |
| 3 | 所有镜像均不可用（链接失效、需要鉴权或网络不通） |
| 130 | 被中断 |

### 任务文件

```json
{
  "urls": ["https://example.com/big.iso"],
  "out": "D:////dl",
  "threads": 16,
  "sha256": null,
  "chunk_mb": 0,
  "slow_kb": 15,
  "slow_sec": 12,
  "retries": 6,
  "timeout": 30,
  "mirrors": ["https://ghfast.top/"]
}
```

### 调用建议

1. 优先使用 `--json`，解析 `done` 与 `error` 事件，不要匹配人类可读输出
2. 使用绝对路径调用，避免依赖当前工作目录：`C://Users//<用户名>//Desktop//下载工具.exe`
3. 大文件配合 `--quiet`，只在结束时读取最后一行
4. 以退出码判断结果，除 0 之外一律按失败处理
5. 批量任务写入 job 文件后逐条调用，便于对单条任务重试

---

## 实现要点

1. **先探测再下载**：优先使用 HEAD 获取元信息，不支持时退回 `Range: bytes=0-0`，据此判断服务端是否支持分段，不支持则退化为单线程。
2. **镜像自动测速**：GitHub 链接自动补充三个加速源，各自拉取 256KB 测速后按速度排序。
3. **分片并发与失败换源**：按大小切片，各片独立重试，重试时切换下一个镜像。
4. **慢链路主动断开**：分片速度持续低于阈值时断开重连。
5. **断点续传**：分片保存在 `<文件名>.parts/`，中断后重跑继续；单线程路径通过 `<文件名>.part.json` 记录指纹，服务端文件变更时自动重下。
6. **下载后校验**：核对文件大小；提供哈希时重新计算并比对（md5/sha1/sha256/sha512）。
7. **多任务队列**：默认同时执行 2 个，支持排队、单条取消，完成后可定位文件。
8. **代理与限速**：支持 HTTP/HTTPS 与 SOCKS5 代理，以及每任务限速（限速器随任务创建，多任务并发时合计速率会高于设定值）；启用限速后不再判定慢链路。

## 设计来源

本工具的行为模型取自 PCL2（Plain Craft Launcher 2）——通过分析其二进制字符串表中与下载相关的条目，复现其对外表现，而非复制其代码。涉及的对应关系如下。

| PCL2 二进制字符串 | 本项目对应实现 |
|---|---|
| `无法确定是否支持分段下载` / `该下载源不支持分段下载` / `获取到的分段大小不一致` | 先探测 Range 支持，再决定是否分片 |
| `第一下载源` / `下载源连接超时` / `但已从其他下载源获取` / `下载源被禁用` / `已无可用下载源` | 多源容错，失败源自动降级 |
| `由于速度过慢断开链接` / `速度下限已提升到 {0}` | 慢链路主动断开，阈值动态提升 |
| `即将进行第 {0} 次重试` / `将在删除文件后重试` | 分片重试与脏文件清理 |
| `任务校验要求为 {0}` / `{0} 文件校验失败` / `{0} (SHA1: {1})` | 下载后哈希校验 |
| `设置过多的下载线程` / `否则不建议设置更多的线程数` | 线程数设上限 |
| `SliderDownloadThread` | 线程数作为界面可调参数 |

PCL2 的下载页仅面向 Minecraft 资源，且没有可供外部调用的命令行入口，因此无法直接复用其下载器。

## 实测数据

WSL 3.0.3 x64 MSI（350.5MB）下载结果：

| 方式 | 速度 | 耗时 |
|---|---|---|
| GitHub 直连 | 不可用（`code 000`，DNS 污染） | — |
| 镜像单线程（gh-proxy.com） | 6.7 MB/s | 约 53 秒 |
| **16 线程分段** | 峰值 26 MB/s，均值 12.5 MB/s | **28.4 秒** |

镜像可用性：`gh-proxy.com` 最快，`ghfast.top` 次之，`ghproxy.net` 较慢，`gh.llkk.cc` 与 `hub.gitmirror.com` 不可用。

## 已知限制

- **多线程不一定更快**：小文件切片开销大于收益，2MB 以下自动走单线程。
- **线程数并非越多越好**：64 线程容易触发服务端限速或风控。
- **镜像只保证连通，不保证内容**：第三方加速源可能返回被篡改或截断的文件。
- **Git Bash 调用 msiexec 的路径处理**：`msiexec /i C:\...` 会被转换为正斜杠，导致 MSI 返回码 2；应在目标目录内使用相对文件名。

## 配置位置

- **移动介质**：配置保存在可执行文件同目录，随介质一同移动。
- **本机用户目录**（桌面、文档等）：配置保存在 `%APPDATA%\下载工具\config.json`，不写入桌面。

删除配置文件即可恢复默认设置。

## 注意

- 仅支持 http/https 直链，不支持 BT、磁力与网盘分享页。
- 经镜像（尤其是 GitHub 加速源）下载的文件建议填写 SHA256：镜像只保证连通，不保证内容未被替换。不填写时程序会在开始下载前输出一条告警。
- 目标介质为 FAT32 时，单文件上限为 4GB−1，超限时程序会在开始前拒绝并提示改存 exFAT/NTFS 或本机目录。
- 保存路径过长（约 240 字符以上）时程序会提前报错，请更换层级较浅的目录或缩短文件名。
- 杀毒软件可能误报 PyInstaller 单文件程序，可加入信任列表；如不接受，可直接使用源码版本 `src/gui.pyw`（需 Python 3.11 及以上）。

## 常见问题

**进度停在 0%？**　多数情况下是链接需要鉴权或存在防盗链机制，请使用浏览器复制得到的下载链接而非页面地址。

**支持 BT / 磁力 / 网盘吗？**　不支持，仅处理 http/https 直链。

**杀毒软件报毒？**　PyInstaller 单文件程序的常见误报，加入信任即可。

---

## 许可

本项目采用 [Apache License 2.0](LICENSE)，允许商用、修改与再分发，条件是保留版权与许可声明、标明改动，并传递上游的 NOTICE 文件（本项目无上游 NOTICE，故无需附带）。

条款中包含专利授权：使用者若就本项目提起专利诉讼，其获得的专利授权自此终止。

项目行为参考 PCL2 的公开表现（依据其二进制字符串表反推），未复制其代码，不涉及上游代码的许可证义务。

## 重新打包

```bash
cd /d "C:/Users/Administrator/Desktop/下载工具"
"C:/Program Files/Python313/python.exe" build_and_sign.py
```

常用变体：

```bash
python build_and_sign.py --no-sign     # 仅打包并写入版本信息，不签名
python build_and_sign.py --no-build    # 使用 dist 中已有产物，仅签名
python build_and_sign.py --no-deploy   # 不部署，产物保留在 %TEMP%\pyi_dist
```

### 发布版本

推送版本标签即触发自动发布：

```bash
git tag v1.2.0
git push origin v1.2.0
```

GitHub Actions 会完成打包、校验与发布，产物挂到 Releases 页面。CI 中不执行签名，产物为未签名版本；需要签名版时在本机执行 `build_and_sign.py` 后手动上传。

CI 亦会在每次推送与合并请求时自动执行契约校验与单元测试。

### 版本信息

在 `build/version_info.txt` 中维护，打包时写入：

| 字段 | 当前值 |
|---|---|
| FileVersion / ProductVersion | 1.2.0.0 |
| CompanyName | shanshuifeng |
| FileDescription | 下载工具 - 多线程分段下载器（界面 + 命令行） |
| ProductName | 下载工具 |
| LegalCopyright | Copyright (C) 2026 shanshuifeng |
| OriginalFilename | 下载工具.exe |

### 签名

使用本地自签名证书 `build/signing/DownloadTool_SelfSigned.pfx`（口令取自环境变量 `DLTOOL_PFX_PASSWORD`）。证书与私钥不随仓库分发，需要自行生成。

自签名证书没有受信任根背书，在其他计算机上仍会显示「未知发布者」。如需在本机显示为可信，将 `build\signing\DownloadTool_SelfSigned.cer` 导入「受信任的根证书颁发机构」：

```powershell
Import-Certificate -FilePath "build\signing\DownloadTool_SelfSigned.cer" `
  -CertStoreLocation Cert:\CurrentUser\Root
```

仓库不提供证书，如需自行签名，可用 `New-SelfSignedCertificate` 生成 .pfx 后执行 `signtool sign /f 你的.pfx /p 口令 /fd SHA256 下载工具.exe`。

### 版本信息为何必须在打包时写入

PyInstaller `--onefile` 的 PE 镜像仅占前约 310KB，其后 10MB 以上为附加的 CArchive。事后通过 Windows API（`BeginUpdateResource` / `UpdateResource`）重写资源段会截断附加数据，文件由 11MB 变为 310KB 且无法运行。因此版本信息只能通过 `--version-file` 在打包时嵌入。

### 打包注意事项

- 使用 **Python 3.13**，与已发布产物的字节码版本一致。
- `--onefile` 模式下 `__file__` 指向临时解压目录，因此代码中以 `sys.frozen` 判断运行环境，配置路径必须基于 `sys.executable` 的所在目录。
- 可执行文件采用控制台子系统，以保证命令行模式下的退出码与管道行为正确；界面模式下的控制台窗口由 `_hide_own_console` 自行隐藏。

---

作者：shanshuifeng ｜ 项目地址：https://github.com/shanshuifeng/Download-tool ｜ 许可：Apache-2.0（见 `LICENSE`）
