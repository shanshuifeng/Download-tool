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

作者：shanshuifeng
项目：https://github.com/shanshuifeng/Download-tool
"""

from __future__ import annotations

import argparse
import ast
import hashlib
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


def _module_ast(module: str) -> ast.Module:
    """取模块的语法树。按「模块名 → 文件名」的约定解析。"""
    src = resolve(f"{module}.py")
    if not src.exists():
        src = resolve(f"{module}.pyw")
    return ast.parse(src.read_text(encoding="utf-8", errors="replace"))


def _module_level_names(module: str) -> set[str]:
    """模块级定义的名字（赋值 / 函数 / 类）。

    走 AST 而非 import：校验器不该为了确认「常量存不存在」就把模块导进来
    ——那会给校验器引入导入副作用，也让临时模块无法参与自测。
    """
    names: set[str] = set()
    for node in _module_ast(module).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return names


def _load_sites(module: str, files: list[str], name: str) -> list[tuple[str, int]]:
    """常量名在指定范围内被**读取**的位置（文件, 行号）。

    判定必须是 AST 的 Name + Load 语境 —— 裸文本匹配会让常量**定义行自身**
    命中，恒为「已使用」，检查等于空转。这正是 `check_anchors` 空转过一轮的
    同类陷阱，不能重犯。定义行上的自引用（X = X + 1）也不计。
    """
    sites: list[tuple[str, int]] = []
    for f in files:
        src = resolve(f)
        if not src.exists():
            continue
        tree = ast.parse(src.read_text(encoding="utf-8", errors="replace"))
        def_lines = _module_def_lines(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
                continue
            if node.id != name:
                continue
            if node.lineno in def_lines.get(name, ()):
                continue
            sites.append((f, node.lineno))
    return sites


def _module_def_lines(tree: ast.Module) -> dict[str, set[int]]:
    """模块级赋值语句的行号：name → 行号集合。用于排除定义行上的自引用。"""
    defs: dict[str, set[int]] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                defs.setdefault(tgt.id, set()).add(node.lineno)
    return defs


def chk_const_used(doc, chk):
    """常量必须真被使用：只定义不读取的常量等于契约里的谎言（CODE-015）。

    匹配是第一级（精确）：常量名本身作为 `ast.Name` 且处于 Load 语境。
    `aliases` 是留给将来的第二级（构造参数别名）——当前**留空**，因为它会
    遮蔽第一级：有人把默认值改成硬编码时，第一级正确判「未使用」，第二级
    却因别名仍被读取而判「已使用」，漏过。低精度规则吞掉高精度规则的判定
    是净负收益。
    """
    module = chk["module"]
    constants = chk["constants"]
    files = chk["files"]
    declared = _module_level_names(module)
    bad = []
    for name in constants:
        if name not in declared:
            bad.append(f"{name} 不在 {module} 的模块级定义里")
            continue
        sites = _load_sites(module, files, name)
        if not sites:
            bad.append(f"{name} 从未被读取（扫过 {' / '.join(files)}）")
    record(doc, "const_used", module, C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(constants)} 个常量均被读取")


def _private_symbols(module: str) -> set[str]:
    """某模块的私有符号集合。

    三处来源：
    - 模块级以下划线开头的名字（赋值、函数、类）
    - 类里以下划线开头的成员（方法与属性）
    - 类里 `self._xxx` 形式的属性名
    """
    names: set[str] = set()
    tree = _module_ast(module)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id.startswith("_"):
                    names.add(tgt.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id.startswith("_"):
                names.add(node.target.id)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for sub in node.body:
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if sub.name.startswith("_"):
                    names.add(sub.name)
            elif isinstance(sub, ast.Assign):
                for tgt in sub.targets:
                    if isinstance(tgt, ast.Name) and tgt.id.startswith("_"):
                        names.add(tgt.id)
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                    and sub.value.id == "self" and sub.attr.startswith("_")):
                names.add(sub.attr)
    return names


def chk_no_private_access(doc, chk):
    """公共符号不得被越界访问：别模块的私有符号不许出现在别的文件里（CODE-012）。"""
    files = chk["files"]
    modules = chk["modules"]
    allow = set(chk.get("allow", []))
    private = {m: _private_symbols(m) for m in modules}
    bad = []
    for f in files:
        src = resolve(f)
        if not src.exists():
            bad.append(f"{f} 不存在")
            continue
        own = Path(f).stem
        tree = ast.parse(src.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            attr = node.attr
            if not attr.startswith("_") or attr.startswith("__"):
                continue
            # self 豁免：对象访问自己的私有成员是正常的
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                continue
            for m, names in private.items():
                if m == own or attr not in names:
                    continue
                key = f"{m}.{attr}"
                if key in allow or attr in allow:
                    continue
                bad.append(f"{f}:{node.lineno} 访问了 {key}")
    record(doc, "no_private_access", "私有符号越界", C_BAD if bad else C_OK,
           "；".join(bad) if bad else "无越界访问")


def _find_func(tree: ast.Module, dotted: str):
    """按 "Class.method" 或 "function" 定位函数节点。找不到返回 None。"""
    if "." in dotted:
        cls_name, meth = dotted.split(".", 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls_name:
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if sub.name == meth:
                            return sub
        return None
    for node in tree.body:
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == dotted):
            return node
    return None


def _module_aliases(module: str) -> set[str]:
    """模块里被 `import X` 引入的模块别名。

    用来区分「`diskutil.check_target(...)` 是模块限定调用」与
    「某个对象上的同名方法」——契约的 `call` 两档匹配靠它判定。
    """
    aliases: set[str] = set()
    for node in _module_ast(module).body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases.add(alias.asname or alias.name.split(".")[0])
    return aliases


def _attr_chain(node: ast.AST) -> tuple[str, str] | None:
    """属性访问链还原成 (根名字, 完整点号名)。

    `diskutil.check_target` → ("diskutil", "diskutil.check_target")
    `os.path.join` → ("os", "os.path.join")
    """
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return cur.id, ".".join(reversed(parts))


def _called_names(func, aliases: set[str]) -> tuple[set[str], set[str]]:
    """函数体内被调用者的两类名字。

    返回 (裸名, 点号全名)：
    - 裸名：`Name(id=S)`，以及**根不是模块别名**的 `Attribute(attr=S)`
    - 点号全名：`Attribute` 链的完整形式（`diskutil.check_target`）
    """
    simple: set[str] = set()
    dotted: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name):
            simple.add(fn.id)
        elif isinstance(fn, ast.Attribute):
            chain = _attr_chain(fn)
            if chain is None:
                simple.add(fn.attr)
                continue
            root, full = chain
            dotted.add(full)
            if root in aliases:
                # 模块限定调用：只能靠点号名精确匹配，裸名不算
                continue
            simple.add(fn.attr)
            if "." not in full:
                dotted.add(full)
    return simple, dotted


def chk_call_site(doc, chk):
    """契约声明的行为必须在代码里真的发生：调用点必须存在（CODE-013）。

    `call` 的匹配分两档（契约 §10.1）：
    - 裸名 `S`：命中 `Name(id=S)` 或基对象不是模块别名的 `Attribute(attr=S)`
    - 点号名 `M.S`：必须精确命中 `Attribute(value=Name("M"), attr="S")`

    不采用「末段名近似」——那会让 `downloader` 作用域里的同名裸调用
    误判为命中，边界就没法判定了。
    """
    module = chk["module"]
    tree = _module_ast(module)
    aliases = _module_aliases(module)
    bad = []
    for spec in chk["calls"]:
        where, call = spec["in"], spec["call"]
        func = _find_func(tree, where)
        if func is None:
            bad.append(f"{where}：契约声明的调用点不存在")
            continue
        simple, dotted = _called_names(func, aliases)
        if "." in call:
            hit = call in dotted
        else:
            hit = call in simple
        if not hit:
            bad.append(f"{where}：没有调用 {call}")
    record(doc, "call_site", module, C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(chk['calls'])} 个调用点全部存在")


def _schema_fingerprint(schema: dict) -> str:
    """SCHEMA 除版本号外的一切的稳定摘要。

    口径以 CONTRACT-cli.md 的 CLI-011 正文为准：
      payload = SCHEMA 去掉 "version" 键后的全部键
      序列化 = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
      摘要   = sha256(...).hexdigest()
    逐键列举会漏掉将来新增的顶层键（`defaults` 就是这样漏过一次）。
    """
    payload = {k: v for k, v in schema.items() if k != "version"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def chk_schema_version(doc, chk):
    """接口版本与指纹的同步性检查（四级判定 + 形态硬失败）。

    形态不合法一律记 RED 并说明缺什么 —— 不允许因「字段缺失所以跳过这项
    检查」而 PASS（CODE-010：SKIP 也算失败，静默跳过的检查等于没有检查）。

    形态校验排在模块导入**之前**：契约块自身不合法时应当直接硬失败，
    不该依赖模块能不能被导入——那会让「形状写错」与「模块装不上」
    两种故障混成同一个报错。

    报红信息自带诊断线索：**payload 键集与实算指纹都由实际 payload 派生，
    不得硬编码**。口径若变了，报错里能直接看出「键集不一样」，维护者立刻
    知道是口径变了而非内容变了——诊断信息本身也是契约的一部分，必须与实现
    同源，否则它会在说谎。
    """
    hexre = re.compile(r"^[0-9a-f]{64}$")

    # ---- 形态校验：缺键 / 异形一律硬失败（收集全部问题，不早退）----
    shape: list[str] = []
    missing = [k for k in ("version", "fingerprint", "previous") if k not in chk]
    if missing:
        shape.append(f"契约块缺必需字段 {missing}")
    prev = chk.get("previous")
    if "previous" in chk:
        if not isinstance(prev, dict) or set(prev) != {"version", "fingerprint"}:
            got = sorted(prev) if isinstance(prev, dict) else prev
            shape.append(f"previous 形状不对：须恰好含 version 与 fingerprint，实际 {got}")
    if "version" in chk and not isinstance(chk["version"], int):
        shape.append("version 必须是整数")
    if "fingerprint" in chk and not (
            isinstance(chk["fingerprint"], str) and hexre.match(chk["fingerprint"])):
        shape.append("fingerprint 必须是 64 位小写十六进制")
    if isinstance(prev, dict) and "fingerprint" in prev and not (
            isinstance(prev["fingerprint"], str) and hexre.match(prev["fingerprint"])):
        shape.append("previous.fingerprint 必须是 64 位小写十六进制")

    # ---- 取实际 payload 的键集与指纹（派生，不硬编码）----
    keys: list[str] = []
    actual_fp = ""
    try:
        schema = _module(chk["module"]).SCHEMA
        payload = {k: v for k, v in schema.items() if k != "version"}
        keys = sorted(payload)
        actual_fp = _schema_fingerprint(schema)
    except Exception:  # noqa: BLE001 —— 形状不对时模块也可能有问题，一并报
        pass

    def fp_hint() -> str:
        """指纹比对线索：能算就给出声明值与实算值，算不了就说明原因。"""
        if not actual_fp:
            return "（无法比对指纹：模块不可读）"
        declared = chk.get("fingerprint")
        if not isinstance(declared, str):
            return f"（无法比对指纹：声明字段缺失；实算 {actual_fp}）"
        return f"（声明 {declared}，实算 {actual_fp}）"

    if shape:
        record(doc, "schema_version", chk["module"], C_BAD,
               "；".join(shape) + f"；payload 键集：{keys}" + fp_hint())
        return

    schema = _module(chk["module"]).SCHEMA
    version = schema.get("version")
    fp = _schema_fingerprint(schema)
    prev_ver = prev["version"]
    prev_fp = prev["fingerprint"]
    bad = []
    # 1 版本号漂移
    if version != chk["version"]:
        bad.append(f"SCHEMA.version={version}（契约声明 {chk['version']}）")
    # 2 内容漂移
    if fp != chk["fingerprint"]:
        bad.append(f"指纹不符：声明 {chk['fingerprint']}，实算 {fp}"
                   f"（当前实现的 payload 键集：{keys}）")
    # 3 版本降级
    if version < prev_ver:
        bad.append(f"版本降级：{version} < 上一版 {prev_ver}")
    # 4 递增与内容变化不同步（必须同真同假）
    up = version > prev_ver
    changed = fp != prev_fp
    if up != changed:
        bad.append("版本递增与内容变化不同步："
                   + ("升了版本但内容没变" if up else "内容变了但版本没升"))
    record(doc, "schema_version", chk["module"], C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"version={version} 指纹 {fp[:12]}…")


def _norm_arg(key: str) -> str:
    """args 参数名归一化：取 "/" 后半段 → 去掉 "--" 前缀 → 连字符转下划线。

    `--slow-sec` → `slow_sec`、`--max-speed` → `max_speed`、
    `-t/--threads` → `threads`。不换下划线会漏掉这两条。
    """
    tail = key.split("/")[-1]
    tail = re.sub(r"^--?", "", tail)
    return tail.replace("-", "_")


def chk_schema_defaults(doc, chk):
    """默认值只写一处：args 文案不得复述默认值，但哨兵语义（「0=」）不受影响。

    判据是**句式**，不是「文案里出现了某个数字」——
    `--chunk` 的「0=自动」是哨兵语义（取 0 会怎样），
    `--slow` 的「0=关闭」是阈值语义，两者都不是默认值重复。

    判定分三态：
    - 含「默认 N」句式且 N == defaults 的值 → 重复，报红
    - 含「默认 N」句式且 N != defaults 的值 → 漂移，报红
    - 含「0=」句式 → 哨兵语义，豁免（但与「默认 N」同现时报红）

    **事实源是 `SCHEMA["defaults"]` 与 `SCHEMA["args"]`**（BUG-45）：
    主循环遍历 `defaults`，参数名用 `_norm_arg` 从 `args` **反查**得到。
    契约 `map` 只是**显式声明**，不是事实源——它把某个默认值声明到不对应的
    参数上时同样报红。

    为什么不能采信 `map` 里的参数名：`map` 是手工维护的白名单，写错一个键，
    那条默认值就完全不受检查——`--slow-sec` 的文案即使复述了「默认 12」，
    只要 `map` 把它错接到 `--slow` 上就抓不到。这与 BUG-43（键没登记）
    同根因：手工维护的白名单会与代码漂移。

    **契约 `map` 与反查结果必须一致**，不一致即报红——`map` 从「事实源」
    降为「被验证的声明」，这才是契约该有的地位。

    `args` 侧是**单向**的：`defaults` 的每个键都要在 `args` 里有对应参数
    （归一化后），反过来不查——`url` / `-o` / `--sha256` 等十个参数本来
    就没有默认值。
    """
    m = _module(chk["module"])
    schema = m.SCHEMA
    args, defaults = schema.get("args", {}), schema.get("defaults", {})
    pat = re.compile(chk["pattern"])
    # 归一化反查表：defaults 的键 → args 里的参数名
    norm = {_norm_arg(k): k for k in args}
    bad = []

    # ---- 主循环：以代码里的事实 defaults 为准，参数名从 args 反查 ----
    for dkey, dval in defaults.items():
        akey = norm.get(dkey)
        if akey is None:
            bad.append(f"defaults 的 {dkey} 在 args 里没有对应参数")
            continue
        text = args[akey]
        hit = pat.search(text)
        if hit and int(hit.group(1)) != dval:
            bad.append(f"{akey} 文案写「默认 {hit.group(1)}」"
                       f"而 defaults 是 {dval}（漂移）")
        elif hit:
            bad.append(f"{akey} 文案复述了默认值（默认 {hit.group(1)}），应删除")
        need = chk.get("must_contain", {}).get(dkey)
        if need and need not in text:
            bad.append(f"{akey} 文案缺「{need}」（哨兵语义不可丢）")

    # ---- 契约 map 是显式声明，必须与反查结果一致 ----
    declared = chk.get("map", {})
    for dkey, akey in declared.items():
        if dkey not in defaults:
            bad.append(f"defaults 缺键 {dkey}")
            continue
        if _norm_arg(akey) != dkey:
            bad.append(f"契约 map 把 {dkey} 声明为 {akey}，"
                       f"但归一化后对应的是 {norm.get(dkey)}")
    # 声明漏了事实：契约声明不完整。该默认值本身仍按反查受检——
    # 漏登记不再让检查失效，但读者会看不到完整的默认值→参数映射。
    for dkey in defaults:
        if dkey not in declared:
            bad.append(f"defaults 的 {dkey} 未登记进契约 map"
                       f"（该默认值的文案仍按反查受检，但契约声明不完整）")

    # 计数取实际检查到的 defaults 键数：取 map 的条目数会在 map 少登记时
    # 报出偏小的数字，反而掩盖问题
    record(doc, "schema_defaults", chk["module"], C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(defaults)} 个默认值各写一处")


def chk_literal_dict(doc, chk):
    """指定的模块级常量必须是纯字面量字典。

    作用域只限 chk["name"] 指向的那一个常量，不扫全模块的字典 ——
    dl.py 里的 DEFAULTS = dict(SCHEMA["defaults"]) 不是字面量，而它恰恰是
    「运行期以 schema 为唯一来源」那条关系，扫到它就误报了。
    """
    path = resolve(chk["file"])
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    value = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == chk["name"] for t in node.targets):
            value = node.value
    if not isinstance(value, ast.Dict):
        record(doc, "literal_dict", chk["name"], C_BAD,
               f"{chk['file']} 中找不到字面量字典 {chk['name']}")
        return
    bad: list[str] = []

    def walk(node, path):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                walk(v, path)
        elif isinstance(node, ast.List):
            for i, v in enumerate(node.values):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, ast.Constant):
            return
        else:
            bad.append(f"{path} 用了 {type(node).__name__}")

    for k, v in zip(value.keys, value.values):
        walk(v, f"{chk['name']}[{k.value if isinstance(k, ast.Constant) else '?'}]")
    record(doc, "literal_dict", chk["name"], C_BAD if bad else C_OK,
           "；".join(bad) if bad else "全部为字面量")


def chk_max_lines(doc, chk):
    """规模上限：既查「超了」，也查「没定义」（CODE-011）。"""
    bad, info = [], []
    limits = chk["limits"]
    declared: set[Path] = set()
    for f, limit in limits.items():
        src = resolve(f)
        if not src.exists():
            bad.append(f"{f} 声明了上限但文件不存在")
            continue
        declared.add(src.resolve())
        n = len(src.read_text(encoding="utf-8", errors="replace").splitlines())
        info.append(f"{f}={n}")
        if n > limit:
            bad.append(f"{f} {n} 行 > 上限 {limit}")
    # src/ 下每个模块都必须登记上限：漏登记的新模块否则完全不受约束
    for src in sorted(SRC.glob("*.py")) + sorted(SRC.glob("*.pyw")):
        if src.resolve() not in declared:
            bad.append(f"{src.name} 未定义规模上限")
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


def _test_funcs(files) -> dict[str, ast.FunctionDef]:
    """按 AST 取测试方法：docstring 与断言统计都要从语法树来，不能靠正则。"""
    funcs: dict[str, ast.FunctionDef] = {}
    for f in files:
        src = resolve(f)
        if not src.exists():
            continue
        tree = ast.parse(src.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test_")):
                funcs[node.name] = node
    return funcs


def _has_assert(func: ast.FunctionDef) -> bool:
    """测试体里至少有一条断言调用，且不是整体只有 skipTest。"""
    asserts = 0
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr.startswith("assert"):
            asserts += 1
    return asserts > 0


def chk_req_tests(doc, chk):
    """凡标「已完成」的需求，必须挂一个真实存在、且自己声明了 REQ 编号的测试。

    标记必须写在 docstring 里（写在注释里不算），且用例本身必须有效
    （至少一条断言）——否则「挂上了」也可能是空的（CODE-014）。
    """
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
    funcs = _test_funcs(chk["tests"])
    defined = set(blocks)
    no_test = sorted(done - set(mapping))
    missing = sorted({mapping[r] for r in done if r in mapping} - defined)
    # 交叉核对：REQ 编号必须写在测试的 docstring 里
    unmarked, invalid = [], []
    for r in sorted(done):
        name = mapping.get(r)
        if not name or name not in defined:
            continue
        marker = ast.get_docstring(funcs.get(name)) if name in funcs else None
        if not marker or r not in marker:
            unmarked.append(f"{r}→{name}")
        if name in funcs and not _has_assert(funcs[name]):
            invalid.append(f"{r}→{name}")
    bad = []
    if no_test:
        bad.append(f"标已完成但没挂测试 {no_test}")
    if missing:
        bad.append(f"测试函数不存在 {missing}")
    if unmarked:
        bad.append(f"测试的 docstring 里没有声明对应 REQ 编号 {unmarked}")
    if invalid:
        bad.append(f"测试体里没有有效断言 {invalid}")
    record(doc, "req_tests", "需求↔测试", C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(done)} 条已完成需求均有带标记的测试")


def chk_bug_tests(doc, chk):
    """凡标「已修」的缺陷，必须挂一个真实存在、且体内写明缺陷编号的测试。

    报告里的状态不是靠嘴说的：改了代码忘了改报告，或报告说修了其实没修，
    这里都会报红。编号必须写在 docstring 里（写在注释里不算，注释极易
    在后续改动中被删掉）。
    """
    text = (DOCS / chk["bugs"]).read_text(encoding="utf-8", errors="replace")
    blocks = _test_blocks(chk["tests"])
    funcs = _test_funcs(chk["tests"])
    bad = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not cells[0].startswith("BUG-"):
            continue
        bid, status, way, tests = cells[0], cells[3], cells[4], cells[5]
        names = [t.strip() for t in re.split(r"[,、]", tests.replace("`", ""))
                 if t.strip() and t.strip() not in ("—", "-", "无")]
        if way.startswith("测试") and not names:
            bad.append(f"{bid} 标为测试验证但没有挂测试")
        for name in names:
            if name not in blocks:
                bad.append(f"{bid} 挂的测试不存在 {name}")
            elif name in funcs:
                marker = ast.get_docstring(funcs[name])
                if not marker or bid not in marker:
                    bad.append(f"{bid} 的测试 docstring 里没有声明编号 {name}")
            elif bid not in blocks[name]:
                bad.append(f"{bid} 的测试体内没有声明编号 {name}")
    record(doc, "bug_tests", "缺陷↔测试", C_BAD if bad else C_OK,
           "；".join(bad) if bad else f"{len(blocks)} 个用例，编号双向对齐")


DISPATCH = {
    "public_symbols": chk_public_symbols,
    "signature": chk_signature,
    "const": chk_const,
    "const_used": chk_const_used,
    "no_private_access": chk_no_private_access,
    "call_site": chk_call_site,
    "schema_version": chk_schema_version,
    "schema_defaults": chk_schema_defaults,
    "literal_dict": chk_literal_dict,
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
    "bug_tests": chk_bug_tests,
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
