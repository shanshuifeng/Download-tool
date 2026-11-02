"""把构建产物按发布用的名字收拢到 dist/。

为什么要有这个脚本：release 工作流原先用 PowerShell 的 Copy-Item 复制带中文名
的文件。GitHub Actions 会把 run 块写成临时 .ps1，而 Windows PowerShell 5.1 在
没有 BOM 时按 ANSI 解析脚本，中文文件名在**解析阶段**就被破坏——结果上传的资产
变成 `default.exe` 与 `_.zip`（软链接式地保留了后缀，名字全丢）。

改用 Python 做这件事：源码按 UTF-8 解析，文件 API 全程 Unicode，不经过任何
shell 的编码转换。这也让「收集产物」这一步能在本机复现验证。

用法（在仓库根目录执行）::

    python tools/collect_artifacts.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")

# 构建产物：PyInstaller 的输出（ASCII 名）→ 发布用的中文名
EXE_SRC = os.path.join(tempfile.gettempdir(), "pyi_dist", "DownloadTool.exe")
EXE_DST = os.path.join(DIST, "下载工具.exe")

ZIP_SRC = os.path.join(ROOT, "build", "便携版", "下载工具_便携版.zip")
ZIP_DST = os.path.join(DIST, "下载工具_便携版.zip")


def main() -> int:
    # 产物名是中文，而 CI 的 Windows 控制台默认不是 UTF-8（cp1252/cp936 视镜像而定）。
    # 不显式指定的话，print 会在最后一步抛 UnicodeEncodeError，让整个发布失败——
    # 文件其实已经复制好了，只是「报个结果」这一步炸了。build_and_sign.py 里
    # 用的是同一套办法。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    os.makedirs(DIST, exist_ok=True)

    if not os.path.isfile(EXE_SRC):
        print("找不到构建产物:", EXE_SRC, file=sys.stderr)
        print("请先执行 python build_and_sign.py --no-sign", file=sys.stderr)
        return 1
    shutil.copy2(EXE_SRC, EXE_DST)

    if os.path.isfile(ZIP_SRC):
        shutil.copy2(ZIP_SRC, ZIP_DST)
    else:
        print("便携包不存在，跳过:", ZIP_SRC, file=sys.stderr)

    print("dist/ 内容：")
    for name in sorted(os.listdir(DIST)):
        p = os.path.join(DIST, name)
        print(f"  {name:24} {os.path.getsize(p) / 1048576:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
