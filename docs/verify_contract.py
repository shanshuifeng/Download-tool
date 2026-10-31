#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_contract.py —— 契约校验器

把 docs/CONTRACT-*.md 里的 ```contract 围栏块（JSON）当规格，
逐条比对源码现状。发现漂移即退出码 1，用于保证「文档是事实来源」。

用法：
    python docs/verify_contract.py            # 只看结论
    python docs/verify_contract.py -v         # 打印每条检查的细节
    python docs/verify_contract.py --json     # 机器可读结果

退出码：0 全部通过 / 1 存在漂移 / 2 文档解析失败
"""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
SRC = ROOT / "src"
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def resolve(rel: str) -> Path:
    """源码在 src/，其余（测试、文档）在根目录，按存在性定位。"""
    p = ROOT / rel
    return p if p.exists() else SRC / rel

BLOCK = re.compile(r"```contract\s*\n(.*?)\n```", re.S)
ANCHOR = re.compile(r"#\s*@contract\s+([A-Z]{2,6}-\d{2,3}[a-z]?)")
CONTRACT_ID = re.compile(r"\b([A-Z]{2,6}-\d{2,3}[a-z]?)\b")
REQ_ROW = re.compile(r"^\|\s*(REQ-\d{3}[a-z]?)\s*\|")
REQ_TEST_ROW = re.compile(r"^\|\s*(REQ-\d{3}[a-z]?)\s*\|\s*`?(test_\w+)`?\s*\|")

C_OK, C_BAD, C_SKIP = "ok", "bad", "skip"
_results: list[dict] = []


def record(doc: str, kind: str, name: str, state: str, detail: str = ""):
    _results.append({"doc": doc, "kind": kind, "name": name,
                     "state": state, "detail": detail})


def fail_detail(a, b, label="声明", label2="实际"):
    return f"{label}={a}  {label2}={b}"


# ---------------- 加载 ----------------

def load_checks():
    items, errors = [], []
    for md in sorted(DOCS.glob("CONTRACT-*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        for i, raw in enumerate(BLOCK.findall(text), 1):
            try:
                spec = json.loads(raw)
            except json.JSONDecodeError as e:
                errors.append(f"{md.name} 第 {i} 个 contract 块不是合法 JSON：{e}")
                continue
            for chk in spec.get("checks", []):
                items.append((md.name, chk))
    return items, errors


def defined_ids() -> set[str]:
    ids = set()
    for md in DOCS.glob("*.md"):
        ids.update(CONTRACT_ID.findall(md.read_text(encoding="utf-8", errors="replace")))
    return ids


# ---------------- 单项检查 ----------------

def _module(name):
    return importlib.import_module(name)


def chk_public_symbols(doc, chk):
    m = _module(chk["module"])
    missing = [n for n in chk["names"] if not hasattr(m, n)]
    missing and record(doc, "public_symbols", chk["module"], C_BAD, f"缺少符号 {missing}")
    not missing and record(doc, "public_symbols", chk["module"], C_OK,
                           f"{len(chk['names'])} 个符号齐全")


def chk_signature(doc, chk):
    m = _module(chk["module"])
    obj = getattr(m, chk["target"])
    params = inspect.signature(obj.__init__ if inspect.isclass(obj) else obj).parameters
    want = chk["params"]
    real = {k: v for k, v in params.items() if k != "self"}
    bad = []
    if list(want) != list(real):
        bad.append(fail_detail(list(want), list(real), "参数顺序", "实际顺序"))
    for name, expect in want.items():
        if name not in real:
            continue
        d = real[name].default
        got = "<required>" if d is inspect.Parameter.empty else repr(d)
        if got != expect:
            bad.append(f"{name}: {fail_detail(expect, got)}")
    record(doc, "signature", f"{chk['target']}.__init__", C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(want)} 个参数一致")


def chk_const(doc, chk):
    m = _module(chk["module"])
    bad = [f"{k}: {fail_detail(v, getattr(m, k, '<缺失>'))}"
           for k, v in chk["values"].items() if getattr(m, k, object()) != v]
    record(doc, "const", chk["module"], C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(chk['values'])} 个常量一致")


def chk_error_table(doc, chk):
    src = resolve(f"{chk['module']}.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    codes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == chk["func"]:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict) and sub.keys and all(
                        isinstance(k, ast.Constant) and isinstance(k.value, int)
                        for k in sub.keys):
                    codes = {k.value for k in sub.keys}
    missing = [c for c in chk["codes"] if c not in codes]
    record(doc, "error_table", chk["func"], C_BAD if missing else C_OK,
           f"缺少状态码 {missing}" if missing else f"{len(chk['codes'])} 个状态码齐全")


def chk_schema_vs_argparse(doc, chk):
    m = _module(chk["module"])
    schema = m.SCHEMA
    parser = m.build_parser()
    real = set()
    for a in parser._actions:
        if a.dest == "help":
            continue
        if a.option_strings:
            real.update(a.option_strings)
        else:
            real.add(a.dest)
    declared = set()
    for k in schema["args"]:
        declared.update(p.strip() for p in k.split("/"))
    only_doc, only_code = declared - real, real - declared
    bad = []
    if only_doc:
        bad.append(f"仅文档有 {sorted(only_doc)}")
    if only_code:
        bad.append(f"仅代码有 {sorted(only_code)}")
    record(doc, "schema_vs_argparse", chk["module"], C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(real)} 个参数一致")


def chk_exit_codes(doc, chk):
    m = _module(chk["module"])
    schema = set(m.SCHEMA.get("exit_codes", {}))
    bad = []
    for code, const in chk["codes"].items():
        v = getattr(m, const, None)
        if v != int(code):
            bad.append(f"{const}={v}（期望 {code}）")
        if code not in schema:
            bad.append(f"SCHEMA 缺退出码 {code}")
    for code in schema - set(chk["codes"]):
        bad.append(f"SCHEMA 多出未声明退出码 {code}")
    record(doc, "exit_codes", chk["module"], C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(chk['codes'])} 个退出码一致")


def chk_event_fields(doc, chk):
    m = _module(chk["module"])
    events = m.SCHEMA.get("events", {})
    bad = []
    for name, fields in chk["events"].items():
        got = set(events.get(name, {}))
        want = set(fields)
        if want - got:
            bad.append(f"{name} 缺字段 {sorted(want - got)}")
        if got - want:
            bad.append(f"{name} 多字段 {sorted(got - want)}")
    record(doc, "event_fields", chk["module"], C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(chk['events'])} 个事件一致")


def _dict_keys(path: Path, name: str) -> set[str] | None:
    """取模块级字典字面量的键。

    值可能是函数调用（如 os.path.join(...)），因此不能整体 literal_eval，
    只要求键是字符串常量。
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    for node in tree.body:
        value = None
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                value = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                value = node.value
        if isinstance(value, ast.Dict):
            keys = set()
            for k in value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
                else:
                    return None
            return keys
    return None


def chk_dict_keys(doc, chk):
    got = _dict_keys(resolve(chk["file"]), chk["name"])
    if got is None:
        record(doc, "dict_keys", chk["name"], C_BAD,
               f"{chk['file']} 中找不到字典 {chk['name']}，或其键不是字符串常量")
        return
    want = set(chk["keys"])
    bad = []
    if want - got:
        bad.append(f"文档有代码无 {sorted(want - got)}")
    if got - want:
        bad.append(f"代码有文档无 {sorted(got - want)}")
    record(doc, "dict_keys", f"{chk['file']}:{chk['name']}", C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(want)} 个键一致")


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.append((a.name, None))
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                found.append((node.module or "", a.name))
    return found


def chk_imports_from(doc, chk):
    got = {n for mod, n in _imports(resolve(chk["file"])) if mod == chk["module"]}
    want = set(chk["names"])
    bad = []
    if want - got:
        bad.append(f"缺少 {sorted(want - got)}")
    if got - want:
        bad.append(f"多出 {sorted(got - want)}")
    record(doc, "imports_from", f"{chk['file']}←{chk['module']}", C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(want)} 个符号")


def chk_forbidden_imports(doc, chk):
    got = {m for m, _ in _imports(resolve(chk["file"]))}
    hit = [n for n in chk["names"] if n in got or n.split(".")[0] in got]
    record(doc, "forbidden_imports", chk["file"], C_BAD if hit else C_OK,
           f"出现了禁止的导入 {hit}" if hit else "无违规导入")


def chk_stdlib_only(doc, chk):
    # 本项目自己的模块（同目录 .py）不算第三方，新增文件无需改校验器
    local = {p.stem for p in list(ROOT.glob("*.py")) + list(SRC.glob("*.py"))}
    std = set(sys.stdlib_module_names) | local | {"__future__"}
    bad = []
    for f in chk["files"]:
        for mod, _ in _imports(resolve(f)):
            root = (mod or "").split(".")[0]
            if root and root not in std:
                bad.append(f"{f} → {root}")
    record(doc, "stdlib_only", "第三方依赖", C_BAD if bad else C_OK,
           f"引入非标准库 {sorted(set(bad))}" if bad else "全部标准库")


def chk_max_lines(doc, chk):
    bad, info = [], []
    for f, limit in chk["limits"].items():
        n = len(resolve(f).read_text(encoding="utf-8", errors="replace").splitlines())
        info.append(f"{f}={n}")
        if n > limit:
            bad.append(f"{f} {n} 行 > 上限 {limit}")
    record(doc, "max_lines", "文件规模", C_BAD if bad else C_OK,
           "；".join(bad) if bad else " ".join(info))


def _test_blocks(files) -> dict[str, str]:
    """把 tests/ 下的测试方法按函数名切块，供交叉核对。"""
    blocks = {}
    for f in files:
        text = resolve(f).read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"    def (test_\w+)\b(.*?)(?=\n    def |\nclass |\Z)",
                             text, re.S):
            blocks[m.group(1)] = m.group(0)
    return blocks


def chk_req_tests(doc, chk):
    """凡标「已完成」的需求，必须挂一个真实存在、且自己声明了 REQ 编号的测试。"""
    text = (DOCS / chk["req"]).read_text(encoding="utf-8", errors="replace")
    done, mapping = set(), {}
    for line in text.splitlines():
        m = REQ_ROW.match(line)
        if not m:
            continue
        rid = m.group(1)
        if "已完成" in line:
            done.add(rid)
        t = REQ_TEST_ROW.match(line)
        if t:
            mapping[t.group(1)] = t.group(2)

    blocks = _test_blocks(chk["tests"])
    defined = set(blocks)
    no_test = sorted(done - set(mapping))
    missing = sorted({mapping[r] for r in done if r in mapping} - defined)
    # 交叉核对：测试自己也要写明 REQ 编号，否则「挂到名字像的测试上」也能蒙混过关
    unmarked = sorted(f"{r}→{mapping[r]}" for r in done
                      if r in mapping and mapping[r] in defined
                      and r not in blocks[mapping[r]])
    bad = []
    if no_test:
        bad.append(f"标已完成但没挂测试 {no_test}")
    if missing:
        bad.append(f"测试函数不存在 {missing}")
    if unmarked:
        bad.append(f"测试体内没有声明对应 REQ 编号 {unmarked}")
    record(doc, "req_tests", "需求↔测试", C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(done)} 条已完成需求均有带标记的测试")


DISPATCH = {
    "public_symbols": chk_public_symbols,
    "signature": chk_signature,
    "const": chk_const,
    "error_table": chk_error_table,
    "schema_vs_argparse": chk_schema_vs_argparse,
    "exit_codes": chk_exit_codes,
    "event_fields": chk_event_fields,
    "dict_keys": chk_dict_keys,
    "imports_from": chk_imports_from,
    "forbidden_imports": chk_forbidden_imports,
    "stdlib_only": chk_stdlib_only,
    "max_lines": chk_max_lines,
    "req_tests": chk_req_tests,
}


# ---------------- 锚点检查 ----------------

def check_anchors():
    ids = defined_ids()
    anchors: dict[str, list[str]] = {}
    files = list(ROOT.glob("*.py")) + list(ROOT.glob("*.pyw"))
    # v1.6 把源码收进 src/ 后这里还在扫根目录，锚点检查整整空转了一轮
    files += list((ROOT / "src").glob("*.py")) + list((ROOT / "src").glob("*.pyw"))
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in ANCHOR.finditer(line):
                anchors.setdefault(m.group(1), []).append(f"{f.name}:{i}")
    unknown = {k: v for k, v in anchors.items() if k not in ids}
    record("锚点", "anchors", "代码引用有效性", C_BAD if unknown else C_OK,
           f"引用了不存在的契约编号 {sorted(unknown)}" if unknown
           else f"{len(anchors)} 处锚点全部有效")
    return ids, anchors


# ---------------- 输出 ----------------

def report(as_json: bool, verbose: bool) -> int:
    # SKIP 也算失败：静默跳过的检查等于没有检查
    bad = [r for r in _results if r["state"] in (C_BAD, C_SKIP)]
    if as_json:
        print(json.dumps({"ok": not bad, "total": len(_results),
                          "failed": len(bad), "results": _results},
                         ensure_ascii=False, indent=2))
        return 1 if bad else 0

    last = None
    for r in _results:
        if r["doc"] != last:
            print(f"\n── {r['doc']}")
            last = r["doc"]
        mark = {"ok": "PASS", "bad": "FAIL", "skip": "SKIP"}[r["state"]]
        line = f"  [{mark}] {r['kind']:<20} {r['name']:<28}"
        if r["state"] != C_OK or verbose:
            line += f"  {r['detail']}"
        print(line)

    print(f"\n共 {len(_results)} 项，通过 {len(_results) - len(bad)}，失败 {len(bad)}")
    if bad:
        print("\n漂移清单（改代码或改契约，二选一）：")
        for r in bad:
            print(f"  · {r['doc']} / {r['kind']} / {r['name']}：{r['detail']}")
        return 1
    print("契约与代码一致。")
    return 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="契约校验器")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    checks, errors = load_checks()
    if errors:
        for e in errors:
            print(f"[文档错误] {e}", file=sys.stderr)
        return 2

    for doc, chk in checks:
        fn = DISPATCH.get(chk.get("type"))
        if not fn:
            # 写错类型必须炸出来。记成 SKIP 会让检查静默消失，
            # 而 SKIP 又不计入失败 —— 整套契约就变成了装饰
            record(doc, chk.get("type", "?"), "未知检查类型", C_BAD,
                   "校验器不支持该 type，文档或脚本有笔误")
            continue
        try:
            fn(doc, chk)
        except Exception as e:  # noqa: BLE001
            record(doc, chk.get("type", "?"), "执行异常", C_BAD, f"{type(e).__name__}: {e}")

    check_anchors()
    return report(a.json, a.verbose)


if __name__ == "__main__":
    sys.exit(main())
