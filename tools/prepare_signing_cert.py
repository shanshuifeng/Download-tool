"""从环境变量还原代码签名证书。

CI 里不保存证书文件，PFX 以 base64 存在仓库 Secret `DLTOOL_PFX_BASE64` 中，
本脚本把它还原到 `build/signing/DownloadTool_SelfSigned.pfx`，供
`build_and_sign.py` 调用 signtool 使用。口令由另一个 Secret 提供，只在
需要签名的那一步以环境变量传入，不落盘。

没有配置 Secret 时什么都不做并以 0 退出——发布流程照常进行，只是产物未签名。
这样 fork 或未配置证书的仓库不会因为缺 Secret 而构建失败。

用法::

    python tools/prepare_signing_cert.py
"""

from __future__ import annotations

import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SIGN_DIR = os.path.join(ROOT, "build", "signing")
PFX = os.path.join(SIGN_DIR, "DownloadTool_SelfSigned.pfx")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    blob = os.environ.get("DLTOOL_PFX_BASE64", "").strip()
    if not blob:
        print("未配置 DLTOOL_PFX_BASE64，跳过证书准备（产物将不签名）")
        return 0

    try:
        raw = base64.b64decode(blob, validate=True)
    except (ValueError, TypeError) as e:
        print("DLTOOL_PFX_BASE64 不是合法的 base64：", e, file=sys.stderr)
        return 1

    os.makedirs(SIGN_DIR, exist_ok=True)
    with open(PFX, "wb") as f:
        f.write(raw)
    # 只报大小与路径，不打印任何证书内容
    print(f"已还原签名证书：{PFX}（{len(raw)} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
