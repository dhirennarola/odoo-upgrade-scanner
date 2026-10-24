"""Index of a target Odoo version, read from its source (nothing is imported or run):

- modules: every addon name (community, plus enterprise when given)
- models: for each model, the fields and methods any addon defines on it
- xmlids: every record / template / menu id in the addons' XML data ("module.id")
- deprecations: what the target announces itself ("Since 19.0, ..."), harvested from
  @deprecated / @api.deprecated decorators and warnings.warn("Since X...") calls

The index is cached per source folder and version, so the second scan is fast.
"""

import ast
import hashlib
import json
import os
import re
from pathlib import Path

CACHE_VERSION = 5
SINCE_RE = re.compile(r"\b[Ss]ince (?:Odoo )?(\d{2})(?:\.0)?\b")
XML_ID_RE = re.compile(r"<(?:record|template|menuitem|act_window|report)\b[^>]*?\bid=\"([\w.]+)\"")


def release_version(odoo_root: Path) -> int:
    text = (odoo_root / "odoo" / "release.py").read_text(encoding="utf-8")
    match = re.search(r"^version_info = \((\d+),", text, re.MULTILINE)
    if not match:
        raise ValueError(f"No version_info in {odoo_root / 'odoo' / 'release.py'}")
    return int(match.group(1))


def addon_dirs(roots: list[Path]):
    """(name, path) of every addon below the given addons folders, tests left out."""
    for root in roots:
        if not root.is_dir():
            continue
        for manifest in sorted(root.glob("*/__manifest__.py")):
            name = manifest.parent.name
            if name.startswith("test_") or name.startswith("test-"):
                continue
            yield name, manifest.parent


def _strings(node) -> list[str]:
    """A str constant or a list/tuple of them -> list of strings."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _text(node) -> str:
    """The text of a str constant or the literal parts of an f-string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return ""


def _since_message(call: ast.Call) -> str:
    return _text(call.args[0]) if call.args else ""


def _deprecation_of(func: ast.FunctionDef) -> str:
    """The "Since X" message of a deprecated function or property, or ""."""
    for decorator in func.decorator_list:
        if isinstance(decorator, ast.Call):
            name = decorator.func.attr if isinstance(decorator.func, ast.Attribute) else getattr(decorator.func, "id", "")
            if name == "deprecated" and SINCE_RE.search(_since_message(decorator)):
                return _since_message(decorator)
    for node in ast.walk(func):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "warn"
                and SINCE_RE.search(_since_message(node))):
            return _since_message(node)
    return ""


def _is_property(func: ast.FunctionDef) -> bool:
    return any(getattr(d, "id", "") == "property" for d in func.decorator_list)


def _model_names(cls: ast.ClassDef) -> list[str]:
    names = []
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            if stmt.targets[0].id in ("_name", "_inherit"):
                names += _strings(stmt.value)
    return list(dict.fromkeys(names))


def _is_field(value) -> bool:
    return (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name) and value.func.value.id == "fields")


def index_python(path: Path, rel: str, index: dict) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            models = _model_names(node)
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [a.arg for a in stmt.args.posonlyargs + stmt.args.args][1:]
                    for model in models:
                        entry = index["models"].setdefault(model, {"fields": [], "methods": []})
                        entry["methods"].append(stmt.name)
                        sigs = entry.setdefault("sigs", {}).setdefault(stmt.name, [])
                        if [rel.split("/")[0], args] not in sigs:
                            sigs.append([rel.split("/")[0], args])   # [addon, argument names]
                    if message := _deprecation_of(stmt):
                        index["deprecations"].append({
                            "name": stmt.name, "owner": node.name, "models": models,
                            "kind": "property" if _is_property(stmt) else "method",
                            "message": message, "since": int(SINCE_RE.search(message).group(1)), "file": rel})
                elif isinstance(stmt, ast.Assign) and _is_field(stmt.value):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            for model in models:
                                index["models"].setdefault(model, {"fields": [], "methods": []})["fields"].append(target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (message := _deprecation_of(node)):
            index["deprecations"].append({"name": node.name, "owner": "", "models": [], "kind": "function",
                                          "message": message,
                                          "since": int(SINCE_RE.search(message).group(1)), "file": rel})


def build_index(odoo_root: Path, enterprise: Path | None = None) -> dict:
    """Read the target source. `odoo_root` is the folder with odoo/ and addons/ (where odoo-bin is)."""
    odoo_root = Path(odoo_root)
    index = {"version": release_version(odoo_root), "modules": [], "models": {}, "xmlids": [], "deprecations": []}
    roots = [odoo_root / "odoo" / "addons", odoo_root / "addons"] + ([Path(enterprise)] if enterprise else [])
    xmlids = set()
    index["module_paths"] = {}
    for name, path in addon_dirs(roots):
        index["modules"].append(name)
        index["module_paths"][name] = str(path)
        for file in path.rglob("*"):
            if "tests" in file.parts or not file.is_file():
                continue
            if file.suffix == ".py":
                index_python(file, f"{name}/{file.relative_to(path).as_posix()}", index)
            elif file.suffix == ".xml":
                for xmlid in XML_ID_RE.findall(file.read_text(encoding="utf-8", errors="replace")):
                    xmlids.add(xmlid if "." in xmlid else f"{name}.{xmlid}")
    # The ORM itself (odoo/models.py or odoo/orm/) defines the methods every model has.
    for file in (odoo_root / "odoo").rglob("*.py"):
        if "addons" in file.relative_to(odoo_root / "odoo").parts or "tests" in file.parts:
            continue
        index_python(file, f"odoo/{file.relative_to(odoo_root / 'odoo').as_posix()}", index)
    base_methods = set()
    for file in [p for p in (odoo_root / "odoo").rglob("models.py") if "addons" not in p.parts] + list(
            (odoo_root / "odoo" / "orm").glob("*.py") if (odoo_root / "odoo" / "orm").is_dir() else []):
        try:
            tree = ast.parse(file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in ("BaseModel", "Model", "AbstractModel"):
                base_methods |= {s.name for s in node.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))}
    index["base_methods"] = sorted(base_methods)
    index["xmlids"] = sorted(xmlids)
    for model in index["models"].values():
        model["fields"] = sorted(set(model["fields"]))
        model["methods"] = sorted(set(model["methods"]))
    seen = set()
    index["deprecations"] = [d for d in index["deprecations"]
                             if (key := (d["name"], d["owner"], d["message"])) not in seen and not seen.add(key)]
    return index


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
    return Path(base) / "odoo-upgrade-scanner"


def load_index(odoo_root: Path, enterprise: Path | None = None, refresh: bool = False) -> dict:
    """The index from the cache, or built and cached."""
    odoo_root = Path(odoo_root).resolve()
    enterprise = Path(enterprise).resolve() if enterprise else None
    release = odoo_root / "odoo" / "release.py"
    key = hashlib.sha1(f"{CACHE_VERSION}|{odoo_root}|{enterprise}|{release.stat().st_mtime}".encode()).hexdigest()[:16]
    path = cache_dir() / f"index-{key}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    index = build_index(odoo_root, enterprise)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index), encoding="utf-8")
    return index
