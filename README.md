# 下载工具

不依赖任何第三方库的多线程分段下载器。已打包成单文件 exe，放 U 盘随身用，插到任何 Windows 10/11 上双击就能跑。

> 改代码前先看 `docs/`：那里是接口契约与需求拆分，改完跑 `python docs/verify_contract.py` 确认没漂。本 README 面向使用，`docs/` 面向维护。

```
桌面/
├── 下载工具.exe            # 双击即用
├── 下载工具_便携版.zip      # 打包好的压缩包，解压到 U 盘即可
└── 下载工具/               # 源码（构建产物 dist/ 打完即删，需要时按文末步骤重新生成）
    ├── gui.pyw             # 界面（源码版，需 Python 3.11+）
    ├── dl.py               # 命令行 / 自动化接口
    ├── downloader.py       # 下载引擎（单文件：探测/分片/校验）+ CLI 入口
    ├── taskqueue.py        # 多任务调度（并发上限、排队、取消）
    ├── netio.py            # 传输层：UA、代理（HTTP/SOCKS5）、_request
    ├── tests/              # 引擎 + 界面测试（本地假服务器，无需外网）
    ├── docs/               # 契约文档 + 校验器，改代码前先看这里
    ├── .git/               # 版本控制（构建产物与证书不入库）
    ├── 使用说明.txt
    ├── 便携版/             # zip 的内容
    └── icon.ico / icon.png
```

## 界面

极简单页：粘贴链接 → 选位置 → 开始。参数全部收在「高级设置」里，默认折叠，不打扰。

右上角「参数说明」按钮，逐条解释每个调节项的作用和适用场景——不确定某项该设多少，点它。

| 可调项 | 范围 | 默认 | 什么时候动它 |
|---|---|---|---|
| 线程数 | 1–32 | 16 | 家宽 8–16 合适；开太高会被服务端限速 |
| 分片大小 | 自动 / 1–32MB | 自动 | 超大文件可固定 8–16MB，重试成本更低 |
| 慢速断开 | 0–200 KB/s | 15 | 0 = 关闭；跨境线路可调低 |
| 慢速时长 | 3–60 秒 | 12 | 设太短会频繁重连 |
| 重试次数 | 0–20 | 6 | 镜像多、网络差时调大 |
| 连接超时 | 5–120 秒 | 30 | 慢线路调到 45–60 |
| 全局限速 | 0–10240 KB/s | 0（不限） | 边下边看视频时压一下；开了限速就不再判慢链 |
| 代理 | — | 空 | 留空跟随系统代理；`direct` 强制直连；也可填 `http://127.0.0.1:7890` 或 `socks5://127.0.0.1:7891` |
| 并发任务 | 1–4 | 2 | 同时下几个文件，多了抢带宽 |
| SHA256 | — | 空 | 填了就在下载后校验（md5/sha1/sha256/sha512 按长度自动识别） |
| 额外镜像 | — | 空 | 逗号分隔的镜像前缀，拼在链接前 |

设置自动保存。窗口高度随「高级设置」展开/收起自适应，按内容实际需要的高度撑开，不会把按钮挤出去。

程序声明了 per-monitor DPI 感知，并按系统缩放比例（125% / 150% / 200%）重新计算所有尺寸和线宽。所以高分屏上文字、1px 分隔线、滑杆都是清晰的原生像素，不会被 Windows 当位图拉伸而发虚。

## 命令行（需 Python）

```bash
python downloader.py "<URL>" -o "D:\下载" -t 16
python downloader.py "<URL>" -o "D:\a.zip" --sha256 <哈希>
python downloader.py "<URL>" --chunk 8 --slow 10 --retries 10 --timeout 45
```

## 自动化接口（dl.exe）

两个可执行文件，同一套引擎：

| 文件 | 形态 | 用途 |
|---|---|---|
| `下载工具.exe` | GUI | 手动下载 |
| `dl.exe` | 控制台 | 脚本、批处理、CI、AI Agent |

`dl.exe` 不弹窗、不需要交互，参数进、事件出、退出码说话。

### 基本调用

```bash
dl.exe "<URL>" -o "D://下载"                 # 存到目录，沿用服务器文件名
dl.exe "<URL>" -o "D://a.zip" -t 32          # 指定文件名与线程数
dl.exe "<URL>" -o "D://dl" --sha256 <哈希>    # 下完自动校验
dl.exe "<URL>" --mirror https://ghfast.top/  # 追加镜像前缀
dl.exe --job job.json --json                 # 从任务文件读参数
dl.exe --schema                              # 打印机器可读的接口描述
```

### 参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `<url>...` | 位置参数，可多个（视为同一文件的镜像） | 必填 |
| `-o, --out` | 保存目录或完整文件路径 | 必填 |
| `-t, --threads` | 并发分片数 1–64 | 16 |
| `--sha256` | 期望哈希，sha1/md5 自动识别 | — |
| `--chunk` | 每片 MB，0=自动 | 0 |
| `--slow` | 慢速阈值 KB/s，0=关闭 | 15 |
| `--slow-sec` | 慢速持续秒数 | 12 |
| `--retries` | 单片重试次数 | 6 |
| `--timeout` | 连接超时秒数 | 30 |
| `--proxy` | HTTP/HTTPS 代理；`direct`=直连；省略跟随环境变量 | — |
| `--max-speed` | 全局限速 KB/s，0=不限 | 0 |
| `--mirror` | 镜像前缀，可重复 | — |
| `--hash` | 下载后计算并输出 sha256 | 关 |
| `--json` | JSON Lines 事件流 | 关 |
| `--quiet` | 不输出进度，只给最终结果 | 关 |
| `--job` | 从 JSON 文件读参数 | — |
| `--schema` | 打印接口描述后退出 | — |

### JSON 事件流

`--json` 时 stdout 每行一个 JSON 对象，直接可被程序解析：

```json
{"event":"progress","percent":82.5,"done":3699710,"total":4486142,"speed":61549,"eta":12}
{"event":"done","path":"D:////dl////a.zip","size":4486142,"sha256":"d31f...","sha256_expected":"d31f...","verified":true,"elapsed":77.9,"avg_speed":57585}
{"event":"error","code":3,"message":"所有下载源都不可用..."}
```

- `progress` 最多每 1.5 秒一条，且百分比变化 ≥1% 才发，不会刷屏
- `eta` 在速度过低时为 `null`
- `sha256` 是实际算出的值，`sha256_expected` 是传入的期望值，`verified` 为比对结果

### 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 下载或校验失败 |
| 2 | 参数错误 |
| 3 | 所有镜像都不可用（链接失效/需登录/网络不通） |
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

### 给 AI Agent 的建议

1. 优先用 `--json`，解析 `done` / `error` 事件，不要正则匹配人类可读输出
2. 用绝对路径调用，避免依赖工作目录：`C://Users//<你>//Desktop//dl.exe`
3. 大文件加 `--quiet`，只在结束时读最后一行
4. 判断结果看退出码，`0` 之外都要当失败处理
5. 批量任务写 job 文件，逐个调用，便于重试单条

## 它做了什么

1. **先探测再动手**：HEAD 拿不到信息就退一步发 `Range: bytes=0-0`，确认服务器是否支持分段。不支持就自动退化成单线程。
2. **镜像自动测速**：GitHub 链接自动补 `gh-proxy.com` / `ghfast.top` / `ghproxy.net`，各拉 256KB 测吞吐，按速度排序。
3. **分片并发 + 失败换源**：按大小切片，每片独立重试，重试时换下一个镜像。
4. **慢链主动断开**：某片持续低于阈值就掐掉重连。
5. **断点续传**：分片落在 `<文件名>.parts/`，中断后重跑接着下。
6. **下载后校验**：核对大小；给了哈希再算一遍（md5/sha1/sha256/sha512）。
7. **任务队列**：默认同时下 2 个，可排队、单条取消、完成可定位文件。
8. **代理与限速**：HTTP/HTTPS/SOCKS5 代理，全局限速；开着限速时不再判慢链。

## 为什么这么设计：从 PCL2 里挖出来的

反查 `Plain Craft Launcher 2.exe`（桌面 `PCL` 文件夹，5.75MB .NET）的字符串表，它内部确实是这套机制：

| PCL 里的原话（二进制字符串） | 对应实现 |
|---|---|
| `无法确定是否支持分段下载` / `该下载源不支持分段下载` / `获取到的分段大小不一致` | 先探测 Range 支持，再决定分不分段 |
| `第一下载源` / `下载源连接超时` / `但已从其他下载源获取` / `下载源被禁用` / `已无可用下载源` | 多源容错，失败源自动降级 |
| `由于速度过慢断开链接` / `速度下限已提升到 {0}` | 慢链主动断开，阈值动态提升 |
| `即将进行第 {0} 次重试` / `将在删除文件后重试` | 分片重试与脏文件清理 |
| `任务校验要求为 {0}` / `{0} 文件校验失败` / `{0} (SHA1: {1})` | 下完做哈希校验 |
| `设置过多的下载线程` / `否则不建议设置更多的线程数` | 线程数有上限，不是越多越好 |
| `SliderDownloadThread`（界面控件名） | 线程数是用户可调参数 |

PCL 的下载器没有可被外部调用的命令行入口，它的「下载」页只面向 Minecraft 资源，所以没法把 URL 直接丢给它。但策略可以完整复刻——本工具就是按它的行为写的。

## 实测

WSL 3.0.3 的 x64 MSI（350.5MB）：

| 方式 | 速度 | 耗时 |
|---|---|---|
| GitHub 直连 | 不通（`code 000`，DNS 污染） | — |
| 镜像单线程（gh-proxy.com） | 6.7 MB/s | ≈53s |
| **16 线程分段** | 峰值 26 MB/s，均值 12.5 MB/s | **28.4s** |

镜像可用性：`gh-proxy.com` 最快，`ghfast.top` 次之，`ghproxy.net` 很慢，`gh.llkk.cc` 和 `hub.gitmirror.com` 不通。

## 踩过的坑

- **多线程不一定快**：小文件切片开销大于收益，2MB 以下自动走单线程。
- **线程数不是越多越好**：64 线程容易被服务端限速或触发风控。
- **Git Bash 调 msiexec 的路径坑**：`msiexec /i C:\...` 会被转成正斜杠，MSI 返回码 2；要 `cd` 到目录用相对文件名。
- **下完先验哈希**：镜像可能返回被篡改或截断的文件。

## 配置文件在哪

- **U 盘 / 移动硬盘**：配置放在 exe 旁边，跟着盘走。
- **装在本机用户目录下**（桌面、文档等）：配置放在 `%APPDATA%\下载工具\config.json`，不弄脏桌面。

删掉配置文件会恢复默认值。

## 常见问题

**进度卡在 0%？** 多半是链接需要登录或防盗链。用浏览器复制「下载链接」而不是页面地址。

**能下 BT / 磁力 / 网盘吗？** 不能，只处理 http/https 直链。

**杀毒软件报毒？** PyInstaller 单文件程序的常见误报，加信任即可。介意可用源码版 `gui.pyw`。

## 改了代码怎么重新打包

一条命令搞定（自动建临时环境、打包、写版本信息、签名、部署到三处）：

```bash
cd /d "C:/Users/Administrator/Desktop/Mystery/下载工具"
"C:/Program Files/Python313/python.exe" build_and_sign.py
```

常用变体：

```bash
python build_and_sign.py --no-sign     # 只打包写版本，不签名
python build_and_sign.py --no-build    # 用 dist 里现成的 exe，只签名
python build_and_sign.py --no-deploy   # 不部署，产物留在 %TEMP%\pyi_dist
```

### 版本信息

在 `version_info.txt` 里改，字段说明：

| 字段 | 当前值 |
|---|---|
| FileVersion / ProductVersion | 0.9.0.0 |
| CompanyName | 个人开发者 |
| FileDescription | 下载工具 - 多线程分段下载器 |
| ProductName | 下载工具 |
| LegalCopyright | Copyright (C) 2026 个人开发者 |
| OriginalFilename | 下载工具.exe |

### 签名

用的是本地自签名证书 `signing\DownloadTool_SelfSigned.pfx`（密码 `dsh-local-sign-2026`，有效期至 2031-10-21，指纹 `FD8DED7E…`）。

**重要**：自签名证书没有受信任根背书，在别人电脑上仍会显示「未知发布者」。要让自己机器上显示为可信，需把 `signing\DownloadTool_SelfSigned.cer` 导入到「受信任的根证书颁发机构」：

```powershell
Import-Certificate -FilePath "signing\DownloadTool_SelfSigned.cer" `
  -CertStoreLocation Cert:\CurrentUser\Root
```

### 为什么版本信息必须在打包时写

`--onefile` 的 PE 镜像只占前 ~310KB，其后 10MB+ 是附加的 CArchive。用 Windows API（`BeginUpdateResource` / `UpdateResource`）事后改资源段会把附加数据截断，文件从 11MB 变成 310KB，程序彻底损坏。所以版本信息只能通过 `--version-file` 在打包时嵌入。

### 打包注意事项

- 必须用 **Python 3.13**，与现有 exe 的字节码版本一致。
- `--onefile` 模式下 `__file__` 指向临时解压目录，所以代码里用 `sys.frozen` 判断，配置路径必须走 `sys.executable` 的目录。
