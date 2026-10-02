#!/usr/bin/env python3
"""code-graph indexer: parse every own code root into graph facts, incrementally.

For each root in projects.yml it walks the tree, and for every source file whose
(mtime, size) changed since the last run it re-parses:

  Python   ast: modules, classes, functions (qualname, line span, signature,
           first docstring line), imports, best-effort intra-project calls, and
           API surface from decorators/registrations:
             HTTP      @app.get/post/.., @router.*, @app.route, @routes.get, app.router.add_get
             MCP       @mcp.tool / @server.tool / .resource / .prompt
             Telegram  CommandHandler("cmd", fn)
             CLI       add_parser("x"), @click.command, @app.command()
  JS/TS    regex: exported functions/classes/consts, relative imports,
           Express/Hono-style routes, Next.js route files, MCP tool registrations
  Docs     *.md / *.mmd / *.drawio / *.puml: title, headings, last change

Unchanged files are served from a per-root cache, so a re-run after a one-line
commit parses one file. Output: <out>/<root>.json for load-code.cypher.

Usage: index.py [--root NAME ...] [--out DIR] [--config projects.yml]
Exit 0 when every requested root indexed; 2 if any failed (others still written).
Stdlib + PyYAML only.
"""
import argparse
import ast
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
# Any change to this file invalidates the per-file parse cache.
PARSER_VERSION = hashlib.sha1(open(os.path.abspath(__file__), "rb").read()).hexdigest()[:8]
LANG = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
        ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript", ".sh": "shell",
        ".go": "go", ".md": "doc", ".mmd": "diagram", ".drawio": "diagram", ".puml": "diagram",
        ".yml": "yaml", ".yaml": "yaml", ".j2": "template", ".sql": "sql", ".cypher": "cypher",
        ".html": "html", ".css": "css", ".toml": "toml", ".json": "json"}
PARSE = {"python", "typescript", "javascript", "shell"}
COMPONENT_MARKERS = ("Dockerfile", "pyproject.toml", "package.json", "requirements.txt", "go.mod")
HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options", "websocket", "api_route", "route", "all"}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def short(s, n=200):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


# ───────────────────────────── Python ─────────────────────────────
def _const_str(n):
    return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None


def _dotted(n):
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        base = _dotted(n.value)
        return f"{base}.{n.attr}" if base else n.attr
    return None


def _kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def endpoints_from_decorator(dec, fname):
    """-> list of endpoint dicts derived from one decorator."""
    call = dec if isinstance(dec, ast.Call) else None
    func = call.func if call else dec
    dotted = _dotted(func) or ""
    attr = dotted.rsplit(".", 1)[-1]
    first = _const_str(call.args[0]) if call and call.args else None
    out = []
    if attr in HTTP_VERBS and first and first.startswith("/"):
        methods = [attr.upper()] if attr not in ("route", "api_route", "all") else []
        m = _kw(call, "methods") if call else None
        if isinstance(m, (ast.List, ast.Tuple)):
            methods = [s for s in (_const_str(e) for e in m.elts) if s] or methods
        kind = "websocket" if attr == "websocket" else "http"
        for meth in methods or ["ANY"]:
            out.append({"kind": kind, "method": meth, "name": f"{meth} {first}", "path": first})
    elif attr in ("tool", "resource", "prompt") and ("." in dotted or call is not None):
        name = (_const_str(_kw(call, "name")) if call else None) or (first if attr == "tool" else None) or fname
        if attr == "resource" and first:
            name = first
        out.append({"kind": f"mcp-{attr}", "method": "", "name": name, "path": ""})
    elif attr == "command" and dotted.split(".")[0] in ("click", "app", "cli", "typer"):
        out.append({"kind": "cli-command", "method": "", "name": first or fname.replace("_", "-"), "path": ""})
    return out


class PyVisitor(ast.NodeVisitor):
    def __init__(self):
        self.symbols, self.endpoints, self.imports, self.calls = [], [], [], []
        self.stack = []

    def _sig(self, n):
        a = n.args
        names = [x.arg for x in a.posonlyargs + a.args]
        if a.vararg:
            names.append("*" + a.vararg.arg)
        names += [x.arg for x in a.kwonlyargs]
        if a.kwarg:
            names.append("**" + a.kwarg.arg)
        return "(" + ", ".join(names) + ")"

    def _def(self, n, kind):
        qn = ".".join(self.stack + [n.name])
        sym = {"qname": qn, "name": n.name, "kind": kind, "line": n.lineno,
               "end": getattr(n, "end_lineno", n.lineno),
               "doc": short((ast.get_docstring(n) or "").split("\n\n")[0]),
               "sig": self._sig(n) if kind != "class" else "",
               "decorators": [short(ast.unparse(d), 120) for d in n.decorator_list]}
        self.symbols.append(sym)
        for d in n.decorator_list:
            for ep in endpoints_from_decorator(d, n.name):
                ep["handler"] = qn
                ep["line"] = n.lineno
                self.endpoints.append(ep)
        self.stack.append(n.name)
        if kind != "class":
            for c in ast.walk(n):
                if isinstance(c, ast.Call):
                    d = _dotted(c.func)
                    if d:
                        self.calls.append({"from": qn, "callee": d})
        self.generic_visit(n)
        self.stack.pop()

    def visit_FunctionDef(self, n):
        self._def(n, "method" if self.stack and self._in_class else "function")

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, n):
        prev = getattr(self, "_in_class", False)
        self._in_class = True
        self._def(n, "class")
        self._in_class = prev

    _in_class = False

    def visit_Import(self, n):
        for a in n.names:
            self.imports.append({"module": a.name, "level": 0, "names": []})

    def visit_ImportFrom(self, n):
        self.imports.append({"module": n.module or "", "level": n.level, "names": [a.name for a in n.names]})

    def visit_Call(self, n):
        d = _dotted(n.func) or ""
        attr = d.rsplit(".", 1)[-1]
        first = _const_str(n.args[0]) if n.args else None
        if attr == "CommandHandler" and first:
            h = _dotted(n.args[1]) if len(n.args) > 1 else None
            self.endpoints.append({"kind": "telegram-command", "method": "", "name": "/" + first,
                                   "path": "", "handler": h, "line": n.lineno})
        elif attr == "add_parser" and first and "." in d:
            self.endpoints.append({"kind": "cli-command", "method": "", "name": first, "path": "",
                                   "handler": None, "line": n.lineno})
        elif attr in ("add_get", "add_post", "add_put", "add_delete", "add_patch") and first and first.startswith("/"):
            h = _dotted(n.args[1]) if len(n.args) > 1 else None
            meth = attr[4:].upper()
            self.endpoints.append({"kind": "http", "method": meth, "name": f"{meth} {first}", "path": first,
                                   "handler": h, "line": n.lineno})
        elif attr == "add_route" and len(n.args) >= 2 and _const_str(n.args[1]) and str(_const_str(n.args[1])).startswith("/"):
            meth = (_const_str(n.args[0]) or "ANY").upper()
            p = _const_str(n.args[1])
            h = _dotted(n.args[2]) if len(n.args) > 2 else None
            self.endpoints.append({"kind": "http", "method": meth, "name": f"{meth} {p}", "path": p,
                                   "handler": h, "line": n.lineno})
        self.generic_visit(n)


def parse_python(text):
    tree = ast.parse(text)
    v = PyVisitor()
    v.visit(tree)
    doc = short((ast.get_docstring(tree) or "").split("\n\n")[0])
    return {"symbols": v.symbols, "endpoints": v.endpoints, "imports": v.imports, "calls": v.calls, "doc": doc}


# ───────────────────────────── JS / TS ─────────────────────────────
RE_EXPORT_FN = re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)", re.M)
RE_EXPORT_CLS = re.compile(r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", re.M)
RE_EXPORT_CONST = re.compile(r"^\s*export\s+(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(async\s*)?(\(|function|[A-Za-z_$][\w$]*\s*=>)?", re.M)
RE_TOP_FN = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)", re.M)
RE_IMPORT = re.compile(r"""(?:import\s[^'"]*?from\s*|import\s*\(\s*|require\(\s*)['"](\.{1,2}/[^'"]+)['"]""")
RE_ROUTE = re.compile(r"""\b(?:app|router|server|api|routes|hono)\.(get|post|put|delete|patch|all|options|head)\(\s*['"`](/[^'"`]*)['"`]""")
RE_MCP_TOOL = re.compile(r"""\.(?:tool|registerTool)\(\s*['"]([\w.\-]+)['"]""")
# Tool tables built through a local helper, e.g. mailkit's entry('list_contacts', {...})
RE_TOOL_HELPER = re.compile(r"""\b(?:entry|defineTool|addTool|tool)\(\s*['"]([a-z][\w\-]*)['"]\s*,\s*\{""")
RE_TOOL_OBJ = re.compile(r"""\bname\s*:\s*['"]([a-z][\w\-]*)['"]\s*,\s*(?:title\s*:[^,]+,\s*)?description\s*:""")
RE_NEXT_METHOD = re.compile(r"^\s*export\s+(?:async\s+)?(?:function|const)\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b", re.M)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def parse_js(text, relpath):
    syms, eps, imps = [], [], []
    for m in RE_EXPORT_FN.finditer(text):
        syms.append({"qname": m[1], "name": m[1], "kind": "function", "line": line_of(text, m.start()),
                     "end": None, "doc": "", "sig": "(" + short(m[2], 80) + ")", "decorators": [], "exported": True})
    for m in RE_EXPORT_CLS.finditer(text):
        syms.append({"qname": m[1], "name": m[1], "kind": "class", "line": line_of(text, m.start()),
                     "end": None, "doc": "", "sig": "", "decorators": [], "exported": True})
    for m in RE_EXPORT_CONST.finditer(text):
        kind = "function" if m[3] else "const"
        syms.append({"qname": m[1], "name": m[1], "kind": kind, "line": line_of(text, m.start()),
                     "end": None, "doc": "", "sig": "", "decorators": [], "exported": True})
    seen = {s["name"] for s in syms}
    for m in RE_TOP_FN.finditer(text):
        if m[1] not in seen:
            syms.append({"qname": m[1], "name": m[1], "kind": "function", "line": line_of(text, m.start()),
                         "end": None, "doc": "", "sig": "(" + short(m[2], 80) + ")", "decorators": [], "exported": False})
    for m in RE_IMPORT.finditer(text):
        imps.append({"module": m[1], "level": -1, "names": []})
    for m in RE_ROUTE.finditer(text):
        meth = m[1].upper()
        eps.append({"kind": "http", "method": meth, "name": f"{meth} {m[2]}", "path": m[2],
                    "handler": None, "line": line_of(text, m.start())})
    is_mcp = "modelcontextprotocol" in text or "McpServer" in text or "tools/list" in text
    for m in RE_MCP_TOOL.finditer(text):
        eps.append({"kind": "mcp-tool", "method": "", "name": m[1], "path": "", "handler": None,
                    "line": line_of(text, m.start())})
    if is_mcp or re.search(r"(^|/)tools\.(m?js|ts)$", relpath):
        for m in RE_TOOL_HELPER.finditer(text):
            eps.append({"kind": "mcp-tool", "method": "", "name": m[1], "path": "", "handler": None,
                        "line": line_of(text, m.start())})
        for m in RE_TOOL_OBJ.finditer(text):
            eps.append({"kind": "mcp-tool", "method": "", "name": m[1], "path": "", "handler": None,
                        "line": line_of(text, m.start())})
    # Next.js app router: app/**/route.ts exports GET/POST...
    nm = re.search(r"(?:^|/)app/(.*?)/?route\.(?:t|j)sx?$", relpath)
    if nm:
        p = "/" + re.sub(r"\(([^)]*)\)/?", "", nm[1]).strip("/")
        for m in RE_NEXT_METHOD.finditer(text):
            eps.append({"kind": "http", "method": m[1], "name": f"{m[1]} {p}", "path": p,
                        "handler": m[1], "line": line_of(text, m.start())})
    pm = re.search(r"(?:^|/)pages/api/(.*)\.(?:t|j)sx?$", relpath)
    if pm:
        p = "/api/" + re.sub(r"/index$", "", pm[1])
        eps.append({"kind": "http", "method": "ANY", "name": f"ANY {p}", "path": p, "handler": "default", "line": 1})
    return {"symbols": syms, "endpoints": eps, "imports": imps, "calls": [], "doc": ""}


RE_SH_FN = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{", re.M)


def parse_shell(text):
    syms = [{"qname": m[1], "name": m[1], "kind": "function", "line": line_of(text, m.start()), "end": None,
             "doc": "", "sig": "()", "decorators": [], "exported": False} for m in RE_SH_FN.finditer(text)]
    head = []
    for l in text.splitlines()[1:12]:
        if l.startswith("#"):
            head.append(l.lstrip("# ").strip())
        elif head:
            break
    return {"symbols": syms, "endpoints": [], "imports": [], "calls": [], "doc": short(" ".join(head))}


def parse_doc(text, ext):
    title, heads = "", []
    if ext == ".md":
        for l in text.splitlines():
            m = re.match(r"^(#{1,3})\s+(.+?)\s*#*\s*$", l)
            if m:
                if not title and len(m[1]) == 1:
                    title = m[2]
                elif len(heads) < 40:
                    heads.append(m[2])
        if not title and heads:
            title = heads[0]
    elif ext == ".drawio":
        heads = sorted(set(re.findall(r'value="([^"&<]{2,60})"', text)))[:60]
    elif ext in (".mmd", ".puml"):
        heads = sorted(set(re.findall(r"\b([A-Za-z][\w-]{2,40})\b", text)))[:60]
    return {"title": short(title, 160), "headings": [short(h, 120) for h in heads]}


# ───────────────────────────── walking & resolution ─────────────────────────────
def git_last_changed(root):
    """relpath -> last commit date, one git call per root (empty for non-git)."""
    if not os.path.isdir(os.path.join(root, ".git")) and not os.path.isfile(os.path.join(root, ".git")):
        return {}
    try:
        out = subprocess.run(["git", "-C", root, "-c", "safe.directory=*", "log", "--format=@%cs", "--name-only",
                              "--no-renames", "-n", "3000"], capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return {}
    res, cur = {}, None
    for l in out.splitlines():
        if l.startswith("@"):
            cur = l[1:]
        elif l and cur and l not in res:
            res[l] = cur
    return res


def find_components(root, globs, exclude):
    comps = []
    for g in globs or []:
        # Only directories can be components: a glob like roles/*/files/* also
        # matches plain files, whose parent ("files") must not become a project.
        for d in sorted(p for p in __import__("glob").glob(os.path.join(root, g)) if os.path.isdir(p)):
            if not os.path.isdir(d) or d == root:
                continue
            rel = os.path.relpath(d, root)
            if any(part in exclude for part in rel.split(os.sep)):
                continue
            names = set(os.listdir(d))
            has_code = any(m in names for m in COMPONENT_MARKERS) or any(
                n.endswith((".py", ".mjs", ".ts", ".go")) for n in names)
            if has_code and not any(rel.startswith(c + os.sep) or rel == c for c in comps):
                comps.append(rel)
    return comps


def resolve_py_import(imp, file_rel, files_set, pkg_roots):
    """Return the repo-relative file an import refers to, if it is inside the root."""
    if imp["level"] > 0:
        base = os.path.dirname(file_rel)
        for _ in range(imp["level"] - 1):
            base = os.path.dirname(base)
        mod = imp["module"].replace(".", "/") if imp["module"] else ""
        cands = [os.path.join(base, mod)] if mod else [base]
        cands += [os.path.join(base, mod, n) if mod else os.path.join(base, n) for n in imp["names"]]
    else:
        mod = imp["module"].replace(".", "/")
        cands = [os.path.join(pr, mod) if pr else mod for pr in pkg_roots]
        cands += [os.path.join(c, n) for c in list(cands) for n in imp["names"]]
    for c in cands:
        c = os.path.normpath(c)
        for t in (c + ".py", os.path.join(c, "__init__.py")):
            if t in files_set:
                return t
    return None


def resolve_js_import(spec, file_rel, files_set):
    base = os.path.normpath(os.path.join(os.path.dirname(file_rel), spec))
    for t in [base] + [base + e for e in (".ts", ".tsx", ".js", ".mjs", ".jsx", ".cjs")] + \
             [os.path.join(base, "index" + e) for e in (".ts", ".tsx", ".js", ".mjs")]:
        if t in files_set:
            return t
    if base.endswith(".js"):  # TS sources imported with .js extension
        for e in (".ts", ".tsx"):
            if base[:-3] + e in files_set:
                return base[:-3] + e
    return None


def index_root(cfg, defaults, outdir, cachedir):
    root = cfg["path"].rstrip("/")
    name = cfg["name"]
    if not os.path.isdir(root):
        raise RuntimeError(f"path missing: {root}")
    exclude = set(defaults.get("exclude_dirs", [])) | set(cfg.get("exclude_dirs", []))
    maxb = defaults.get("max_file_bytes", 400000)
    cache_path = os.path.join(cachedir, name + ".json")
    try:
        cache = json.load(open(cache_path))
    except Exception:
        cache = {}
    comps = find_components(root, cfg.get("components"), exclude)
    lastchg = git_last_changed(root)

    files, new_cache, parsed_n = [], {}, 0
    for dirpath, dirs, fnames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        dirs[:] = [d for d in dirs if d not in exclude and not d.startswith(".") or d in (".github",)]
        if rel_dir != "." and any(p in exclude for p in rel_dir.split(os.sep)):
            dirs[:] = []
            continue
        for fn in fnames:
            ext = os.path.splitext(fn)[1].lower()
            lang = LANG.get(ext)
            if not lang and fn != "Dockerfile":
                continue
            lang = lang or "dockerfile"
            p = os.path.join(dirpath, fn)
            rel = os.path.normpath(os.path.relpath(p, root))
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size > maxb and lang not in ("doc",):
                continue
            key = f"{PARSER_VERSION}:{int(st.st_mtime)}:{st.st_size}"
            c = cache.get(rel)
            if c and c.get("key") == key:
                entry = c
            else:
                try:
                    raw = open(p, "rb").read()
                except OSError:
                    continue
                text = raw.decode("utf-8", "replace")
                entry = {"key": key, "sha": hashlib.sha1(raw).hexdigest(), "loc": text.count("\n") + 1,
                         "parsed": None, "error": None}
                try:
                    if lang == "python":
                        entry["parsed"] = parse_python(text)
                    elif lang in ("typescript", "javascript"):
                        entry["parsed"] = parse_js(text, rel)
                    elif lang == "shell":
                        entry["parsed"] = parse_shell(text)
                    elif lang in ("doc", "diagram"):
                        entry["parsed"] = parse_doc(text, ext)
                except SyntaxError as e:
                    entry["error"] = f"syntax error line {e.lineno}"
                except Exception as e:
                    entry["error"] = short(str(e), 160)
                parsed_n += 1
            new_cache[rel] = entry
            comp = next((cp for cp in sorted(comps, key=len, reverse=True)
                         if rel == cp or rel.startswith(cp + os.sep)), "")
            files.append({"rel": rel, "lang": lang, "component": comp, "entry": entry})

    files_set = {f["rel"] for f in files}
    py_pkg_roots = [""] + comps + sorted({os.path.dirname(f["rel"]) for f in files
                                         if f["rel"].endswith("pyproject.toml") or f["rel"].endswith("setup.py")})
    proj_of = lambda comp: f"{name}/{comp}" if comp else name

    out = {"root": name, "path": root, "class": cfg.get("class", "unclassified"), "run": now_iso(),
           "projects": [{"key": name, "name": name, "path": root, "parent": None, "class": cfg.get("class", "unclassified"),
                         "superseded_by": cfg.get("superseded_by")}]
                       + [{"key": proj_of(c), "name": os.path.basename(c), "path": os.path.join(root, c),
                           "parent": name, "class": cfg.get("class", "unclassified"), "superseded_by": None} for c in comps],
           "files": [], "symbols": [], "endpoints": [], "imports": [], "calls": [], "docs": [],
           "stats": {"files": len(files), "parsed": parsed_n, "errors": 0}}
    sym_by_file = {}
    for f in files:
        e, rel = f["entry"], f["rel"]
        fkey = f"{name}:{rel}"
        out["files"].append({"key": fkey, "rel": rel, "project": proj_of(f["component"]), "lang": f["lang"],
                             "sha": e["sha"], "loc": e["loc"], "error": e.get("error"),
                             "last_changed": lastchg.get(rel), "doc": (e.get("parsed") or {}).get("doc", "")
                             if f["lang"] not in ("doc", "diagram") else ""})
        if e.get("error"):
            out["stats"]["errors"] += 1
        pr = e.get("parsed") or {}
        if f["lang"] in ("doc", "diagram"):
            out["docs"].append({"key": fkey, "path": os.path.join(root, rel), "rel": rel, "project": proj_of(f["component"]),
                                "kind": doc_kind(rel), "title": pr.get("title", ""), "headings": pr.get("headings", []),
                                "last_changed": lastchg.get(rel)})
            continue
        names = {}
        for s in pr.get("symbols", []):
            skey = f"{fkey}::{s['qname']}"
            names[s["name"]] = skey
            names[s["qname"]] = skey
            out["symbols"].append({**{k: s.get(k) for k in ("qname", "name", "kind", "line", "end", "doc", "sig")},
                                   "key": skey, "file": fkey, "project": proj_of(f["component"]),
                                   "exported": s.get("exported", True), "decorators": s.get("decorators", [])})
        sym_by_file[rel] = names
        for ep in pr.get("endpoints", []):
            ekey = f"{proj_of(f['component'])}|{ep['kind']}|{ep['name']}"
            h = ep.get("handler")
            out["endpoints"].append({"key": ekey, "kind": ep["kind"], "method": ep.get("method", ""), "name": ep["name"],
                                     "path": ep.get("path", ""), "project": proj_of(f["component"]), "file": fkey,
                                     "line": ep.get("line"), "handler": names.get(h) or names.get((h or "").split(".")[-1])})
        for imp in pr.get("imports", []):
            tgt = (resolve_js_import(imp["module"], rel, files_set) if imp["level"] == -1
                   else resolve_py_import(imp, rel, files_set, py_pkg_roots))
            if tgt and tgt != rel:
                out["imports"].append({"from": fkey, "to": f"{name}:{tgt}"})
    # calls: resolve callee by name within the same file, then within imported files
    imp_map = {}
    for i in out["imports"]:
        imp_map.setdefault(i["from"], []).append(i["to"].split(":", 1)[1])
    for f in files:
        pr = f["entry"].get("parsed") or {}
        local = sym_by_file.get(f["rel"], {})
        for c in pr.get("calls", []):
            last = c["callee"].split(".")[-1]
            tgt = local.get(c["callee"]) or local.get(last)
            if not tgt:
                for other in imp_map.get(f"{name}:{f['rel']}", []):
                    tgt = sym_by_file.get(other, {}).get(last)
                    if tgt:
                        break
            src = local.get(c["from"])
            if tgt and src and tgt != src:
                out["calls"].append({"from": src, "to": tgt})
    out["calls"] = [dict(t) for t in {tuple(sorted(d.items())) for d in out["calls"]}]
    out["endpoints"] = list({e["key"]: e for e in out["endpoints"]}.values())

    os.makedirs(cachedir, exist_ok=True)
    with open(cache_path + ".tmp", "w") as fh:
        json.dump(new_cache, fh)
    os.replace(cache_path + ".tmp", cache_path)
    with open(os.path.join(outdir, f"code-{name}.json.tmp"), "w") as fh:
        json.dump(out, fh)
    os.replace(os.path.join(outdir, f"code-{name}.json.tmp"), os.path.join(outdir, f"code-{name}.json"))
    return out["stats"] | {"symbols": len(out["symbols"]), "endpoints": len(out["endpoints"]),
                           "docs": len(out["docs"]), "components": len(comps)}


def doc_kind(rel):
    b = os.path.basename(rel).lower()
    if b.startswith("readme"):
        return "readme"
    if b in ("claude.md", "agents.md"):
        return "claude-md"
    if "architecture" in b or rel.endswith((".mmd", ".drawio", ".puml")):
        return "architecture"
    if "/specs/" in rel:
        return "spec"
    if "/plans/" in rel:
        return "plan"
    if "runbook" in b or "handoff" in b:
        return "runbook"
    return "doc"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=os.path.join(HERE, "projects.yml"))
    ap.add_argument("--out", default="/opt/compose/code-graph/out")
    ap.add_argument("--cache", default="/opt/compose/code-graph/cache")
    ap.add_argument("--root", action="append", help="index only these roots (by name or path)")
    a = ap.parse_args()
    conf = yaml.safe_load(open(a.config))
    os.makedirs(a.out, exist_ok=True)
    want = set(a.root or [])
    status, rc = {}, 0
    for r in conf["roots"]:
        if want and r["name"] not in want and r["path"].rstrip("/") not in {w.rstrip("/") for w in want}:
            continue
        t0 = time.time()
        try:
            st = index_root(r, conf.get("defaults", {}), a.out, a.cache)
            status[r["name"]] = {"ok": True, "secs": round(time.time() - t0, 1), **st}
        except Exception as e:
            status[r["name"]] = {"ok": False, "error": short(str(e), 300)}
            rc = 2
    print(json.dumps(status, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
