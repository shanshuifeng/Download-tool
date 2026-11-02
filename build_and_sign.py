# -*- coding: utf-8 -*-
"""
下载工具 —— 重新打包 + 写版本信息 + 签名，一条命令完成。

产物只有一个 exe（gui.pyw 是唯一入口）：有参数走命令行，没参数开界面。
控制台子系统 + GUI 分发，脚本调用的退出码 / 管道 / 重定向都正常；
双击时的控制台窗口由 _hide_own_console 自行隐藏。

为什么不用 Windows API 直接改 exe 的资源段：
    PyInstaller --onefile 的 PE 镜像只占前 ~310KB，其后 10MB+ 是附加的 CArchive。
    UpdateResource / BeginUpdateResource 重写 PE 时会把这部分截断，
    文件从 11MB 变成 310KB，程序彻底损坏。
    所以版本信息必须在「打包时」用 --version-file 写入，不能事后改。

用法：
    python build_and_sign.py            # 全流程
    python build_and_sign.py --no-sign  # 只打包写版本，不签名
    python build_and_sign.py --no-build # 用 dist 里现成的 exe，只签名

前置：
    - Python 3.13（与源 exe 一致，避免字节码版本不符）
    - PyInstaller（脚本会自动在临时 venv 里装）
    - Windows SDK 的 signtool.exe

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
ASSETS = os.path.join(HERE, "assets")
BUILD = os.path.join(HERE, "build")
VENV = os.path.join(tempfile.gettempdir(), "pyi_build_env")
WORK = os.path.join(tempfile.gettempdir(), "pyi_work")
DIST = os.path.join(tempfile.gettempdir(), "pyi_dist")
PFX = os.path.join(BUILD, "signing", "DownloadTool_SelfSigned.pfx")
# 公钥证书入库（不含私钥），随产物分发，便于用户导入受信任根
CER = os.path.join(ASSETS, "DownloadTool.cer")

# 版本资源：模板入库，成品在打包时生成——版本号的唯一来源是 git tag
VERSION_INFO_TEMPLATE = os.path.join(BUILD, "version_info.txt.in")
VERSION_INFO_GENERATED = os.path.join(BUILD, "version_info.generated.txt")
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
# 口令只从环境变量取，仓库里不留任何口令
PFX_PASSWORD = os.environ.get("DLTOOL_PFX_PASSWORD", "")
MIRROR = "https://mirrors.aliyun.com/pypi/simple/"

# 部署目标（相对当前用户）
PORTABLE = os.path.join(BUILD, "便携版")
DEPLOY = [
    os.path.join(os.path.expanduser("~"), "Desktop", "下载工具.exe"),
    os.path.join(PORTABLE, "下载工具.exe"),
]


# ---------------- 版本号：唯一来源是 git tag ----------------
#
# 同一个事实若同时写在 tag、版本资源、README、Release 名里，就一定会有一处
# 忘记改，而且没有机制能发现。所以版本号只在打标签时写一次，其余全部派生。


def _norm_version(raw):
    """把 v1.2.0 / 1.2.0 规范成三段式；不是三段数字就直接失败。"""
    v = raw.strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    if not VERSION_RE.match(v):
        raise SystemExit(
            f"版本号格式不对：{raw!r}。应为 v1.2.3 或 1.2.3（只接受三段数字）")
    return v


def _latest_tag():
    """取最近的 tag；不在 git 仓库里、没有 tag、没有 git 命令都返回 None。"""
    try:
        out = subprocess.run(["git", "describe", "--tags", "--abbrev=0"],
                             cwd=HERE, capture_output=True, text=True,
                             timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def resolve_version(cli_value):
    """按优先级取版本号：--version > DLTOOL_VERSION > 最近的 git tag。

    CI 用环境变量传（tag 的 checkout 默认是浅克隆，`git describe` 未必拿得到），
    本地直接靠 tag 就够了。
    """
    for raw, src in ((cli_value, "--version"),
                     (os.environ.get("DLTOOL_VERSION"), "DLTOOL_VERSION"),
                     (_latest_tag(), "最近的 git tag")):
        if raw:
            v = _norm_version(raw)
            print(f"[3/6] 版本号 {v}（来源：{src}）")
            return v
    raise SystemExit(
        "取不到版本号。请三选一：传 --version v1.2.3、"
        "设 DLTOOL_VERSION=v1.2.3、或在打了 tag 的提交上构建")


def render_version_info(version):
    """按模板渲染版本资源，返回生成文件的路径。

    模板用占位符而非具体数字：这样「当前是哪个版本」只存在于 tag 里。
    """
    if not os.path.isfile(VERSION_INFO_TEMPLATE):
        raise SystemExit("缺少版本资源模板：" + VERSION_INFO_TEMPLATE)
    major, minor, patch = version.split(".")
    with open(VERSION_INFO_TEMPLATE, encoding="utf-8") as f:
        text = f.read()
    text = text.replace("{VERSION_TUPLE}", f"{major}, {minor}, {patch}, 0")
    text = text.replace("{VERSION}", f"{version}.0")
    with open(VERSION_INFO_GENERATED, "w", encoding="utf-8") as f:
        f.write(text)
    return VERSION_INFO_GENERATED


def run(cmd, **kw):
    redact = kw.pop("redact", None)
    shown = [str(c) for c in cmd]
    if redact:
        # 口令等敏感参数不落日志：CI 日志会长期保留
        for i, c in enumerate(shown):
            if c == redact and i + 1 < len(shown):
                shown[i + 1] = "***"
    print("  $", " ".join(shown))
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", **kw)
    if r.stdout.strip():
        for line in r.stdout.strip().splitlines()[-8:]:
            print("    " + line)
    if r.returncode != 0:
        if r.stderr.strip():
            print("  ! " + r.stderr.strip()[:600])
        raise RuntimeError(f"命令失败（{r.returncode}）")
    return r


def find_python313():
    for p in (r"C:\Program Files\Python313\python.exe",
              r"C:\Program Files (x86)\Python313\python.exe"):
        if os.path.isfile(p):
            return p
    return sys.executable


def find_signtool():
    base = r"C:\Program Files (x86)\Windows Kits\10\bin"
    if not os.path.isdir(base):
        return None
    best = None
    for ver in os.listdir(base):
        p = os.path.join(base, ver, "x64", "signtool.exe")
        if os.path.isfile(p):
            if best is None or ver > best[0]:
                best = (ver, p)
    return best[1] if best else None


def ensure_venv():
    if os.environ.get("DLTOOL_USE_SYSTEM_PYTHON") == "1":
        # CI 等已自带 PyInstaller 的环境：直接用当前解释器，不再建虚拟环境
        print("[2/6] 使用当前解释器的 PyInstaller:", sys.executable)
        return sys.executable
    py = os.path.join(VENV, "Scripts", "python.exe")
    if os.path.isfile(py):
        print("[2/6] 复用已有构建环境")
        return py
    print("[2/6] 创建构建环境并安装 PyInstaller")
    base = find_python313()
    print("  基础解释器:", base)
    run([base, "-m", "venv", VENV])
    run([py, "-m", "pip", "install", "--quiet",
         "--disable-pip-version-check", "-i", MIRROR,
         "--trusted-host", "mirrors.aliyun.com", "pyinstaller"])
    return py


def check_all():
    """打包前跑契约校验与测试，坏代码不允许进 exe。"""
    print("[1/6] 契约校验与测试")
    py = find_python313()
    jobs = [
        ("契约校验", [py, os.path.join(HERE, "docs", "verify_contract.py")]),
        ("单元测试", [py, "-m", "unittest", "discover", "-s", "tests"]),
    ]
    for name, cmd in jobs:
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        for line in out[-3:]:
            print("    " + line)
        if r.returncode != 0:
            print(f"  ! {name}失败，已中止打包（--skip-checks 可强行跳过）")
            if (r.stderr or "").strip():
                print("  ! " + r.stderr.strip()[:500])
            raise SystemExit(1)


def build(py, version_info):
    print("[4/6] 打包（含版本资源）")
    for d in (WORK, DIST):
        shutil.rmtree(d, ignore_errors=True)

    # 只出一个 exe：有参数走命令行，没参数开界面（分发逻辑在 gui.pyw 的 main）
    run([py, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console",
         "--name", "DownloadTool",
         "--paths", SRC,
         "--icon", os.path.join(ASSETS, "icon.ico"),
         "--version-file", version_info,
         "--distpath", DIST, "--workpath", WORK, "--specpath", WORK,
         os.path.join(SRC, "gui.pyw")])
    exe = os.path.join(DIST, "DownloadTool.exe")
    if not os.path.isfile(exe):
        raise RuntimeError("打包产物不存在: " + exe)
    return exe


def _file_in_use(path):
    """检测文件是否被进程占用（签名前必须确认，否则 signtool 报错难懂）。"""
    try:
        with open(path, "r+b"):
            return False
    except OSError:
        return True


def kill_running_tool():
    """关掉正在运行的下载工具进程，否则产物被占用无法覆盖/签名。

    部署后文件名是「下载工具.exe」，打包中间产物叫 DownloadTool.exe，
    两个名字都要试——只按一个名字杀是杀不掉的。
    """
    import time

    for name in ("下载工具.exe", "DownloadTool.exe"):
        r = subprocess.run(["taskkill", "/F", "/IM", name],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            print("  已结束正在运行的", name)
            time.sleep(1.5)


def sign(exe, signtool):
    print("[5/6] 签名")
    if not os.path.isfile(PFX):
        raise RuntimeError(f"证书不存在：{PFX}")
    if not PFX_PASSWORD:
        raise RuntimeError(
            "缺少签名口令：请先设置环境变量 DLTOOL_PFX_PASSWORD"
            "（或用 --no-sign 跳过签名）")
    if _file_in_use(exe):
        kill_running_tool()
        if _file_in_use(exe):
            raise RuntimeError(f"文件仍被占用，请手动关闭：{exe}")
    # 注意：/d 描述保持 ASCII——中文经 subprocess 传给 signtool 易乱码。
    # 中文描述已在版本资源 FileDescription 里。
    run([signtool, "sign", "/fd", "SHA256",
         "/f", PFX, "/p", PFX_PASSWORD,
         "/tr", "http://timestamp.digicert.com", "/td", "SHA256",
         "/d", "DownloadTool - Multi-thread Segment Downloader", exe],
        redact="/p")


def prune_backups(keep=3):
    """只留最近 keep 个 _backup_* 目录。

    每次部署都会把旧 exe 备份到当天的目录里，一个目录约 23MB。
    不设上限的话，两个月就能堆出几个 G，所以只保留最近几个。
    """
    dirs = sorted(
        (d for d in os.listdir(BUILD) if d.startswith("_backup_")),
        reverse=True,
    )
    for d in dirs[keep:]:
        p = os.path.join(BUILD, d)
        try:
            shutil.rmtree(p)
            print("  已清理旧备份:", d)
        except OSError as e:
            print("  旧备份清理失败（可忽略）:", d, e)


def pack_portable(exe):
    """把便携版内容归拢到 build/便携版/ 并打成 zip。

    以前这一步靠手工，导致 zip 经常内含旧 exe —— 没人会发现。
    """
    names = ["README.md", "使用说明.txt", "job.example.json"]
    os.makedirs(PORTABLE, exist_ok=True)
    if exe:
        shutil.copy2(exe, os.path.join(PORTABLE, "下载工具.exe"))
    for n in names:
        src = os.path.join(HERE, n)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(PORTABLE, n))
    # 公钥证书一并放进便携包：用户导入后即可验证签名来自同一主体
    if os.path.isfile(CER):
        shutil.copy2(CER, os.path.join(PORTABLE, "DownloadTool.cer"))

    members = [n for n in ["下载工具.exe", "DownloadTool.cer"] + names
               if os.path.isfile(os.path.join(PORTABLE, n))]
    zpath = os.path.join(PORTABLE, "下载工具_便携版.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for n in members:
            z.write(os.path.join(PORTABLE, n), "下载工具/" + n)
    # 便携包顺手放一份到桌面，方便直接取用。这一步是**尽力而为**：
    # CI（GitHub Actions 的 runner）没有 Desktop 目录，早期版本这里直接
    # copy2 会抛 FileNotFoundError，让整个发布流程挂在最后一步。
    desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(desktop_dir):
        try:
            shutil.copy2(zpath, os.path.join(desktop_dir, "下载工具_便携版.zip"))
        except OSError as e:
            print("  桌面副本跳过：", e)
    else:
        print("  桌面副本跳过：无 Desktop 目录（CI 环境属正常）")
    print("  便携包:", zpath, f"({os.path.getsize(zpath)/1048576:.1f} MB)")


def deploy(exe):
    """把 exe 放到桌面 / 便携目录——只在本地跑，CI 不需要（用 --no-deploy 跳过）。"""
    print("[6/6] 部署")
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(PORTABLE, exist_ok=True)   # 便携目录要先建，否则下面的复制会被跳过
    bak = os.path.join(BUILD, "_backup_" + __import__("datetime").date.today().strftime("%Y%m%d"))
    os.makedirs(bak, exist_ok=True)
    kill_running_tool()
    for t in DEPLOY:
        parent = os.path.dirname(t)
        if not os.path.isdir(parent):
            print("  跳过（目录不存在）:", t)
            continue
        if os.path.isfile(t):
            shutil.copy2(t, os.path.join(bak, os.path.basename(parent) + "-bak.exe"))
        shutil.copy2(exe, t)
        print("  已部署:", t)
    print("  备份目录:", bak)
    prune_backups()


def main():
    # 输出统一为 UTF-8；放在 main 内而非模块级，便于被测试导入
    sys.stdout = __import__("io").TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sign", action="store_true")
    ap.add_argument("--sign-if-available", action="store_true",
                    help="有证书就签名，没有则跳过（CI 用：未配置 Secret 时照常出包）")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--no-deploy", action="store_true",
                    help="不往桌面/便携目录复制（CI 用；便携包仍会生成）")
    ap.add_argument("--version", metavar="vX.Y.Z",
                    help="版本号；缺省读 DLTOOL_VERSION，再缺省用最近的 git tag")
    ap.add_argument("--skip-checks", action="store_true",
                    help="跳过打包前的契约校验与测试")
    args = ap.parse_args()

    if not args.skip_checks:
        check_all()

    py = ensure_venv()

    version = resolve_version(args.version)
    version_info = render_version_info(version)

    if args.no_build:
        exe = os.path.join(DIST, "DownloadTool.exe")
        if not os.path.isfile(exe):
            raise SystemExit("dist 中没有现成 exe，请去掉 --no-build")
        print("[4/6] 跳过打包，使用:", exe)
    else:
        exe = build(py, version_info)

    # 证书齐备才谈得上签名；--sign-if-available 用于 CI：未配置 Secret 时跳过而非失败
    have_cert = os.path.isfile(PFX) and bool(PFX_PASSWORD)
    if args.no_sign:
        print("[5/6] 跳过签名")
    elif args.sign_if_available and not have_cert:
        print("[5/6] 未配置签名证书，跳过签名（产物将显示「未知发布者」）")
    else:
        st = find_signtool()
        if not st:
            raise SystemExit("未找到 signtool.exe")
        print("  signtool:", st)
        try:
            sign(exe, st)
        except RuntimeError as e:
            raise SystemExit(f"签名失败：{e}")

    # 便携包是发布必需的产物，与「要不要放到桌面」无关，所以先无条件打出来
    pack_portable(exe)

    if args.no_deploy:
        print("[6/6] 跳过部署，产物在:", exe)
    else:
        deploy(exe)

    print("\n完成。")
    if args.no_sign or not have_cert:
        print("提示：本次未签名，Windows 会提示「未知发布者」。")
    else:
        print("提示：已用自签名证书签名，但证书未受信任根背书，")
        print("      其他电脑上仍显示「未知发布者」。导入以下证书后才会显示发布者：", CER)


if __name__ == "__main__":
    main()
