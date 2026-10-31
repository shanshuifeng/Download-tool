# -*- coding: utf-8 -*-
"""
下载工具 —— 重新打包 + 写版本信息 + 签名，一条命令完成。

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
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout = __import__("io").TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(tempfile.gettempdir(), "pyi_build_env")
WORK = os.path.join(tempfile.gettempdir(), "pyi_work")
DIST = os.path.join(tempfile.gettempdir(), "pyi_dist")
PFX = os.path.join(HERE, "signing", "DownloadTool_SelfSigned.pfx")
CER = os.path.join(HERE, "signing", "DownloadTool_SelfSigned.cer")
# 优先读环境变量，避免把口令写死在会被分享的脚本里
PFX_PASSWORD = os.environ.get("DLTOOL_PFX_PASSWORD", "dsh-local-sign-2026")
MIRROR = "https://mirrors.aliyun.com/pypi/simple/"

# 部署目标（相对当前用户）
DEPLOY = [
    os.path.join(os.path.expanduser("~"), "Desktop", "下载工具.exe"),
    os.path.join(HERE, "下载工具.exe"),
    os.path.join(HERE, "便携版", "下载工具.exe"),
]

# 命令行/自动化接口：桌面也放一份，Agent 可直接调用
DEPLOY_CLI = [
    os.path.join(os.path.expanduser("~"), "Desktop", "dl.exe"),
    os.path.join(HERE, "dl.exe"),
    os.path.join(HERE, "便携版", "dl.exe"),
]


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
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
    py = os.path.join(VENV, "Scripts", "python.exe")
    if os.path.isfile(py):
        print("[2/5] 复用已有构建环境")
        return py
    print("[2/5] 创建构建环境并安装 PyInstaller")
    base = find_python313()
    print("  基础解释器:", base)
    run([base, "-m", "venv", VENV])
    run([py, "-m", "pip", "install", "--quiet",
         "--disable-pip-version-check", "-i", MIRROR,
         "--trusted-host", "mirrors.aliyun.com", "pyinstaller"])
    return py


def check_all():
    """打包前跑契约校验与测试，坏代码不允许进 exe。"""
    print("[1/5] 契约校验与测试")
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


def build(py):
    print("[3/5] 打包（含版本资源）")
    for d in (WORK, DIST):
        shutil.rmtree(d, ignore_errors=True)

    # GUI
    run([py, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
         "--name", "DownloadTool",
         "--icon", os.path.join(HERE, "icon.ico"),
         "--version-file", os.path.join(HERE, "version_info.txt"),
         "--distpath", DIST, "--workpath", WORK, "--specpath", WORK,
         os.path.join(HERE, "gui.pyw")])
    gui = os.path.join(DIST, "DownloadTool.exe")

    # CLI（控制台，供脚本 / AI 调用）
    run([py, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console",
         "--name", "dl",
         "--icon", os.path.join(HERE, "icon.ico"),
         "--version-file", os.path.join(HERE, "version_info_cli.txt"),
         "--distpath", DIST, "--workpath", os.path.join(WORK, "cli"),
         "--specpath", os.path.join(WORK, "cli"),
         os.path.join(HERE, "dl.py")])
    cli = os.path.join(DIST, "dl.exe")

    for f in (gui, cli):
        if not os.path.isfile(f):
            raise RuntimeError("打包产物不存在: " + f)
    return gui, cli


def _file_in_use(path):
    """检测文件是否被进程占用（签名前必须确认，否则 signtool 报错难懂）。"""
    try:
        with open(path, "r+b"):
            return False
    except OSError:
        return True


def kill_running_tool():
    """关掉正在运行的下载工具进程，否则产物被占用无法覆盖/签名。"""
    r = subprocess.run(["taskkill", "/F", "/IM", "DownloadTool.exe"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode == 0:
        print("  已结束正在运行的 DownloadTool.exe")
        import time
        time.sleep(1.5)


def sign(exe, signtool):
    print("[4/5] 签名")
    if not os.path.isfile(PFX):
        raise RuntimeError(f"证书不存在：{PFX}")
    if _file_in_use(exe):
        kill_running_tool()
        if _file_in_use(exe):
            raise RuntimeError(f"文件仍被占用，请手动关闭：{exe}")
    # 注意：/d 描述保持 ASCII——中文经 subprocess 传给 signtool 易乱码。
    # 中文描述已在版本资源 FileDescription 里。
    run([signtool, "sign", "/fd", "SHA256",
         "/f", PFX, "/p", PFX_PASSWORD,
         "/tr", "http://timestamp.digicert.com", "/td", "SHA256",
         "/d", "DownloadTool - Multi-thread Segment Downloader", exe])


def prune_backups(keep=3):
    """只留最近 keep 个 _backup_* 目录。

    每次部署都会把旧 exe 备份到当天的目录里，一个目录约 23MB。
    不设上限的话，两个月就能堆出几个 G —— 这正是这轮清理掉的东西。
    """
    dirs = sorted(
        (d for d in os.listdir(HERE) if d.startswith("_backup_")),
        reverse=True,
    )
    for d in dirs[keep:]:
        p = os.path.join(HERE, d)
        try:
            shutil.rmtree(p)
            print("  已清理旧备份:", d)
        except OSError as e:
            print("  旧备份清理失败（可忽略）:", d, e)


def deploy(exe, exe_cli=None):
    print("[5/5] 部署")
    bak = os.path.join(HERE, "_backup_" + __import__("datetime").date.today().strftime("%Y%m%d"))
    os.makedirs(bak, exist_ok=True)
    kill_running_tool()
    pairs = [(exe, DEPLOY)]
    if exe_cli:
        pairs.append((exe_cli, DEPLOY_CLI))
    for src, targets in pairs:
        for t in targets:
            parent = os.path.dirname(t)
            if not os.path.isdir(parent):
                print("  跳过（目录不存在）:", t)
                continue
            if os.path.isfile(t):
                shutil.copy2(t, os.path.join(bak, os.path.basename(parent) + "-bak.exe"))
            shutil.copy2(src, t)
            print("  已部署:", t)
    print("  备份目录:", bak)
    prune_backups()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sign", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--no-deploy", action="store_true")
    ap.add_argument("--skip-checks", action="store_true",
                    help="跳过打包前的契约校验与测试")
    args = ap.parse_args()

    if not args.skip_checks:
        check_all()

    py = ensure_venv()

    if args.no_build:
        exe = os.path.join(DIST, "DownloadTool.exe")
        exe_cli = os.path.join(DIST, "dl.exe")
        if not os.path.isfile(exe):
            raise SystemExit("dist 中没有现成 exe，请去掉 --no-build")
        print("[3/5] 跳过打包，使用:", exe, "/", exe_cli)
    else:
        exe, exe_cli = build(py)

    if args.no_sign:
        print("[4/5] 跳过签名")
    else:
        st = find_signtool()
        if not st:
            raise SystemExit("未找到 signtool.exe")
        print("  signtool:", st)
        sign(exe, st)
        sign(exe_cli, st)

    if args.no_deploy:
        print("[5/5] 跳过部署，产物在:", exe, "/", exe_cli)
    else:
        deploy(exe, exe_cli)

    print("\n完成。")
    print("提示：自签名证书未受信任根背书，别人电脑上仍显示「未知发布者」。")
    print("      导入证书到「受信任的根证书颁发机构」后才会变绿：", CER)


if __name__ == "__main__":
    main()
