# 下载工具

多线程分段下载器。界面与命令行共用同一个可执行文件：双击打开界面，带参数即进入命令行模式。

纯 Python 标准库实现，无第三方依赖；打包为单个 exe，解压即用。

[![CI](https://github.com/shanshuifeng/Download-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/shanshuifeng/Download-tool/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

---

## 特性

- **多线程分段**：按字节区间切分，多个连接并行拉取，合并后校验总长度与哈希
- **镜像择优**：同一文件的多个 URL 视为镜像，按实测速度加权分配分片，慢源自动降权
- **断点续传**：分片落盘为 `.parts`，中断后按已有长度续传；续传指纹不符则作废重下
- **完整性校验**：`--sha256` 支持 sha256 / sha1 / md5，自动按长度识别算法
- **限速**：令牌桶控制每任务速率，写盘前取令牌，保证限速真实生效
- **机器可读**：`--json` 输出 JSON Lines 事件流，`--schema` 导出接口描述，退出码区分失败原因
- **健壮性**：服务器声称支持分段却回 416 时退化为单线程；401/403/404 等永久错误不浪费重试

## 安装

### 使用发布版

从 [Releases](https://github.com/shanshuifeng/Download-tool/releases) 下载：

| 资产 | 说明 |
|---|---|
| `DownloadTool.exe` | 单文件，双击运行；带参数即命令行模式 |
| `DownloadTool-portable.zip` | 便携包，解压到任意目录使用，内含 `下载工具/` |

资产名使用 ASCII 是为绕开 CI 环境的代码页限制；程序本身与便携包内部仍是中文名「下载工具」。

### 从源码运行

需要 Python 3.10 及以上（仅用标准库）：

```bash
python src/dl.py https://example.com/file.zip -o D:/downloads
python src/gui.pyw        # 打开界面
```

## 使用

### 界面

双击 `下载工具.exe`，粘贴链接、选择保存位置即可。界面支持并发数、限速、镜像前缀与代理设置，参数含义与命令行一致。

### 命令行

唯一的命令行入口是 `src/dl.py`（打包后即同一个 exe）：

```bash
python src/dl.py <url...> -o <目录|文件> [选项]
python src/dl.py --job <文件> [--json]
```

常用示例：

```bash
# 保存到目录，沿用服务端文件名
python src/dl.py "https://example.com/a.zip" -o "D:/下载"

# 指定文件名与线程数
python src/dl.py "https://example.com/a.zip" -o "D:/a.zip" -t 32

# 下载后校验哈希
python src/dl.py "https://example.com/a.zip" -o "D:/dl" --sha256 <哈希>

# 追加镜像前缀（可重复）
python src/dl.py "https://github.com/u/r/releases/download/v1/a.zip" \
  -o "D:/dl" --mirror https://ghfast.top/

# 从任务文件读取参数，输出事件流
python src/dl.py --job job.json --json

# 导出机器可读的接口描述
python src/dl.py --schema
```

#### 参数

| 参数 | 说明 |
|---|---|
| `url` | 下载链接，可传多个（视为同一文件的镜像） |
| `-o, --out` | 保存目录或完整文件路径（必填，除非任务文件里给了） |
| `-t, --threads` | 并发分片数，1–64 |
| `--sha256` | 期望哈希，sha256 / sha1 / md5 自动识别 |
| `--chunk` | 每片大小 MB，`0` 自动 |
| `--slow` | 慢速阈值 KB/s，`0` 关闭 |
| `--slow-sec` | 慢速需持续的秒数 |
| `--retries` | 单片重试次数 |
| `--timeout` | 连接超时秒数 |
| `--proxy` | HTTP/HTTPS 代理；`direct` 强制直连；省略则读环境变量 |
| `--max-speed` | 每任务限速 KB/s，`0` 不限 |
| `--mirror` | 额外镜像前缀，可重复 |
| `--hash` | 下载后计算并输出文件 sha256 |
| `--json` | 输出 JSON Lines 事件流 |
| `--quiet` | 不输出进度，只在结束时给结果 |
| `--job` | 从 JSON 文件读取任务参数 |
| `--schema` | 打印接口的机器可读描述后退出 |

#### 退出码

| 码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 下载或校验失败 |
| `2` | 参数错误 |
| `3` | 无可用镜像 |
| `130` | 被中断 |

#### 事件流

`--json` 下每行一个 JSON 对象：

```json
{"event":"progress","percent":42.5,"done":44564480,"total":104857600,"speed":5242880.0,"eta":11}
{"event":"done","path":"D:/a.zip","size":104857600,"sha256":"…","sha256_expected":null,"verified":null,"elapsed":20.1,"avg_speed":5210000.0}
{"event":"error","code":3,"message":"所有源都不支持分段"}
```

进度事件按「距上次 ≥1.5 秒」或「百分比变化 ≥1」节流，两者满足其一即输出——避免大文件刷屏，也避免慢速时长时间无输出。

#### 任务文件

```json
{
  "url": ["https://example.com/a.zip"],
  "out": "D:/下载",
  "threads": 16,
  "sha256": "…"
}
```

命令行显式给出的参数优先于任务文件；未显式给出时（即使取值恰好等于默认值）才使用文件中的值。

## 构建

需要 Python 3.13 与 PyInstaller；Windows SDK 的 `signtool.exe` 仅在签名时需要。

```bash
python build_and_sign.py --no-sign        # 打包，不签名
python build_and_sign.py --version v1.3.0 # 指定版本号（缺省取最近的 git tag）
```

打包前会自动跑契约校验与全部测试，坏代码无法进入 exe。产物位于 `%TEMP%\pyi_dist\DownloadTool.exe`，并生成 `build/便携版/下载工具_便携版.zip`。

**版本号的唯一来源是 git tag。** `build/version_info.txt.in` 只是模板，打包时按 `--version` > `DLTOOL_VERSION` > 最近 tag 的顺序取值渲染，不在仓库里存具体版本号。

## 发版

```bash
git tag -a v1.3.0 -m "v1.3.0"
git push origin master
git push origin v1.3.0
```

推送标签即触发 GitHub Actions：打包、上传、发布 Release。CI 亦在每次推送与合并请求时执行契约校验与单元测试。

## 代码签名与完整性校验

当前发布的产物**未签名**，Windows 会显示「未知发布者」，这属预期现象。自签名证书对公开分发没有实际帮助：SmartScreen 仍会拦截，除非用户手动把证书导入受信任根。仓库不保存任何证书与私钥。

若需要真实签名，可行路径见下（私钥按 CA/B 论坛要求须存放在硬件或云 HSM 中，因此无法直接把 `.pfx` 放进 CI）：

| 方案 | 成本 | 说明 |
|---|---|---|
| OV 证书 | 约 $150–300/年 | 全球可申请，需身份审核；CI 签名需配套云签名服务 |
| EV 证书 | 约 $400+/年 | 2024 年起与 OV 在 SmartScreen 上无差别，不再值得为此多付 |
| SignPath Foundation | 免费（开源项目） | 由基金会持证并代签，发布者显示为 SignPath Foundation |
| Azure Artifact Signing | 约 $10/月 | 个人开发者仅限美国与加拿大 |

**校验下载文件**：GitHub 会为每个资产计算 SHA-256，可在 Release 页面或 API 的 `digest` 字段查看：

```bash
certutil -hashfile DownloadTool.exe SHA256
```

## 项目结构

```
下载工具/
├── README.md                 本文件
├── LICENSE                   Apache-2.0
├── 使用说明.txt               面向最终用户的一页纸说明
├── job.example.json          任务文件示例
├── src/                      源码（仅标准库）
│   ├── downloader.py         下载引擎：分段、调度、合并、进度
│   ├── dl.py                 唯一的命令行入口，含机器可读接口描述
│   ├── gui.pyw              界面；带参数时转交给命令行
│   ├── netio.py              HTTP 传输、代理、SOCKS5、重试
│   ├── httpinfo.py          HTTP 语义判定：分段能力、永久错误
│   ├── mirrors.py           镜像前缀生成与择优
│   ├── taskqueue.py         任务队列
│   ├── resume.py            续传指纹
│   ├── diskutil.py          磁盘预检与预留
│   └── naming.py            文件名规整
├── tests/                    100 个用例（本地假服务器，不访问外网）
├── docs/                     契约、需求、缺陷记录与校验器
├── tools/                   发布辅助脚本
└── build/                    构建配置与产物（大部分不入库）
```

## 设计约束

本项目把「接口契约」写成机器可读的声明，再用校验器逐条核对代码是否真的满足：

```bash
python docs/verify_contract.py    # 25 项检查
python -m unittest discover -s tests
```

契约覆盖公开符号、退出版本、SCHEMA 的结构指纹、默认值只写一处、跨模块私有访问、调用点存在性等。其中「结构指纹」把接口形状与版本号绑定：内容变了必须升版本，版本升了必须内容有变，两者同真同假。

这套机制的出发点是同一个事实只允许写一处——重复的事实没有机制能发现不一致，而机器可验的声明会。

## 许可

[Apache-2.0](LICENSE)
