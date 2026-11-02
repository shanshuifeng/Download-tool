"""把构建产物按发布用的名字收拢到 dist/。

**发布用的资产名一律用 ASCII。** 这不是审美选择，是 Windows runner 的硬约束：

release 工作流早期用 PowerShell 的 Copy-Item 复制带中文名的文件，上传后资产变成
`default.exe` 与 `_.zip`——中文被整体丢弃（`下载工具_便携版.zip` → `_.zip`，正是
按 cp1252 编码并忽略不可映射字符的结果）。改成 Python 收集后文件名在磁盘上是
对的，但上传环节仍会丢中文，两个层面都在 Windows 的代码页上栽跟头。

与其和编码反复拉扯，不如让进出的文件名都落在 ASCII 里：程序本身、便携包内部的
目录名与 exe 名、Release 页面的说明文字，仍然是中文——只有**下载链接上的文件名**
是 ASCII。这条边界划清楚，发布链路就再也不会因为代码页而坏。

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

# 构建产物（PyInstaller 输出，已是 ASCII 名）→ 发布资产名（同样 ASCII）
EXE_SRC = os.path.join(tempfile.gettempdir(), "pyi_dist", "DownloadTool.exe")
EXE_DST = os.path.join(DIST, "DownloadTool.exe")

# 便携包由 build_and_sign.py 生成，源路径含中文（Python 读写没问题，只是不进资产名）
ZIP_SRC = os.path.join(ROOT, "build", "便携版", "下载工具_便携版.zip")
ZIP_DST = os.path.join(DIST, "DownloadTool-portable.zip")

# 公钥证书随产物分发：用户导入后即可验证签名来自同一主体
CER_SRC = os.path.join(ROOT, "build", "signing", "DownloadTool_SelfSigned.cer")
CER_DST = os.path.join(DIST, "DownloadTool.cer")


def main() -> int:
    # 即便资产名是 ASCII，日志里仍会打印中文（如「便携包不存在」）。CI 的
    # Windows 控制台默认不是 UTF-8（cp1252/cp936 视镜像而定），不显式指定的话
    # print 会抛 UnicodeEncodeError 让整步以 101 退出——文件已复制好，只是
    # 「报个结果」这一步炸了。build_and_sign.py 里用的是同一套办法。
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

    # 证书缺失不致命：未配置签名的构建本来就没有它
    if os.path.isfile(CER_SRC):
        shutil.copy2(CER_SRC, CER_DST)
    else:
        print("公钥证书不存在，跳过:", CER_SRC, file=sys.stderr)

    print("dist/ 内容：")
    for name in sorted(os.listdir(DIST)):
        p = os.path.join(DIST, name)
        print(f"  {name:26} {os.path.getsize(p) / 1048576:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
