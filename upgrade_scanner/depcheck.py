"""Does everything the custom modules lean on still exist in the target version?

- manifest dependencies (a module renamed or dropped)
- methods overridden on standard models (super() would call nothing)
- fields named in @api.depends and in view XPath expressions
- views patched with inherit_id, and xml ids used with env.ref / ref="..."
- deprecations the target announces itself (from the index), when the code uses them
"""

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .inventory import code_files
from .model import AMBER, RED, Finding, Module

# Harvested names too common to match on a call alone (they would flag most modules).
GENERIC_NAMES = {"check", "route", "context", "uid", "cr", "get", "write", "create", "search", "read", "update",
                 "copy", "concat", "union", "browse", "name", "_check", "init", "run", "send"}
FIELD_IN_XPATH = re.compile(r"""//field\[@name=['"](\w+)['"]\]""")
STANDARD_FIELDS = {"id", "display_name", "create_uid", "create_date", "write_uid", "write_date", "__last_update"}


class Context:
    """What the scan knows besides the target: the custom modules' own fields, methods and xml ids."""

    def __init__(self, index: dict, modules: list[Module]):
        self.index = index
        self.base_methods = set(index.get("base_methods", []))
        self.target_modules = set(index["modules"])
        self.target_xmlids = set(index["xmlids"])
        self.custom_names = {m.name for m in modules}
        self.custom_fields: dict[str, set] = {}
        self.custom_methods: dict[str, dict[str, set]] = {}   # model -> method -> modules defining it
        self.custom_xmlids: set[str] = set()
        for module in modules:
            for path in code_files(module.path):
                text = path.read_text(encoding="utf-8", errors="replace")
                if path.suffix == ".py":
                    for model, fields, methods in _classes(text):
                        self.custom_fields.setdefault(model, set()).update(fields)
                        for method in methods:
                            self.custom_methods.setdefault(model, {}).setdefault(method, set()).add(module.name)
                elif path.suffix == ".xml":
                    for xmlid in re.findall(r"<(?:record|template|menuitem)\b[^>]*?\bid=\"([\w.]+)\"", text):
                        self.custom_xmlids.add(xmlid if "." in xmlid else f"{module.name}.{xmlid}")

        self.target_paths = {name: Path(p) for name, p in index.get("module_paths", {}).items()}
        self._texts: dict[tuple, list] = {}

    def module_texts(self, module: str, suffix: str) -> list[tuple[Path, str]]:
        """(path, text) of a TARGET module's files with this suffix ([] when the module is unknown)."""
        key = (module, suffix)
        if key not in self._texts:
            root = self.target_paths.get(module)
            self._texts[key] = [] if root is None else [
                (p, p.read_text(encoding="utf-8", errors="replace"))
                for p in root.rglob(f"*{suffix}") if "tests" not in p.parts and "static/lib" not in p.as_posix()]
        return self._texts[key]

    def parent_text(self, ref: str, owl: bool) -> tuple[str, str] | None:
        """(text of the parent view or template, all XML text of its module) in the target, or None
        when it can't be found there (custom parent, or a module the scan was not given)."""
        module = ref.split(".")[0]
        if module in self.custom_names or module not in self.target_paths:
            return None
        files = self.module_texts(module, ".xml")
        needle = f't-name="{ref}"' if owl else f'id="{ref.split(".", 1)[1]}"'
        for _path, text in files:
            if needle in text:
                return _element_text(text, needle), "\n".join(t for _p, t in files)
        return None

    def target_model(self, model: str) -> dict | None:
        return self.index["models"].get(model)

    def has_field(self, model: str, field: str) -> bool:
        target = self.target_model(model) or {}
        return field in STANDARD_FIELDS or field in target.get("fields", []) or field in self.custom_fields.get(model, set())

    def has_method(self, model: str, method: str, module: str = "") -> bool:
        """Defined in the target, or by ANOTHER custom module (a module's own override doesn't count)."""
        target = self.target_model(model) or {}
        others = self.custom_methods.get(model, {}).get(method, set()) - {module}
        return method in target.get("methods", []) or method in self.base_methods or bool(others)

    def has_xmlid(self, xmlid: str) -> bool:
        return xmlid in self.target_xmlids or xmlid in self.custom_xmlids


def _strings(node) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _model_info(cls: ast.ClassDef) -> tuple[str, list[str]]:
    """(_name, _inherit list) of a model class."""
    name, inherits = "", []
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            if stmt.targets[0].id == "_name":
                name = (_strings(stmt.value) or [""])[0]
            elif stmt.targets[0].id == "_inherit":
                inherits = _strings(stmt.value)
    return name, inherits


def _classes(text: str):
    """(model, field names, method names) for every model class in a Python file."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            name, inherits = _model_info(node)
            fields = [t.id for s in node.body if isinstance(s, ast.Assign) for t in s.targets if isinstance(t, ast.Name)
                      and isinstance(s.value, ast.Call) and isinstance(s.value.func, ast.Attribute)
                      and getattr(s.value.func.value, "id", "") == "fields"]
            methods = [s.name for s in node.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for model in ([name] if name else []) + inherits:
                yield model, fields, methods


def _calls_super(func: ast.FunctionDef) -> bool:
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "super" for n in ast.walk(func))


def _element_text(text: str, needle: str) -> str:
    """The element that contains `needle` (a <record> or a <t t-name=...> template), else the whole file."""
    start = text.find(needle)
    for opener, closer in (("<record", "</record>"), ("<template", "</template>"), ("<t ", "</templates>")):
        begin = text.rfind(opener, 0, start)
        end = text.find(closer, start)
        if begin >= 0 and end > 0:
            if opener == "<t ":
                following = text.find(' t-name="', start + len(needle))
                end = following if 0 < following < end else end
            return text[begin:end]
    return text


ANCHOR_RE = re.compile(r"""@([\w:-]+)\s*=\s*['"]([^'"]+)['"]""")
HASCLASS_RE = re.compile(r"""hasclass\(\s*['"]([^'"]+)['"]""")
SKIP_ANCHOR_ATTRS = {"position", "expr"}


def anchors(node: ET.Element) -> list[tuple[str, str]]:
    """What an extension hooks on: (attribute, value) pairs, or ("class", name) for hasclass()."""
    if node.tag == "xpath":
        expr = node.get("expr", "")
        return ANCHOR_RE.findall(expr) + [("class", c) for c in HASCLASS_RE.findall(expr)]
    return [(k, v) for k, v in node.attrib.items() if k not in SKIP_ANCHOR_ATTRS]


def anchor_found(attr: str, value: str, text: str) -> bool:
    if attr == "class":
        return value in text
    return bool(re.search(rf"""\b{re.escape(attr)}\s*=\s*["']{re.escape(value)}["']""", text))


def check_anchors(module: Module, rel: str, text: str, ctx: "Context", parent: str, owl: bool,
                  root: ET.Element, label: str) -> list[Finding]:
    """Every XPath / position hook of an extension must still exist in the parent in the target."""
    found = ctx.parent_text(parent, owl)
    if found is None:
        return []
    parent_text, module_text = found
    findings = []
    for node in root.iter():
        if not node.get("position"):
            continue
        for attr, value in anchors(node):
            if anchor_found(attr, value, parent_text):
                continue
            hint = node.get("expr") or f'{attr}="{value}"'
            elsewhere = anchor_found(attr, value, module_text)
            findings.append(Finding(
                module.name, AMBER if elsewhere else RED, "anchor.missing",
                f"{label} hooks on {attr}=\"{value}\", which is no longer in {parent} in the target version"
                + (" (it still appears elsewhere in that module: check it is the same element)." if elsewhere
                   else ", so this change is not applied (or the view fails to load)."),
                "Open the new parent and attach the change to the element that replaced it.",
                rel, _line_of(text, hint) or _line_of(text, value), 0, 1.0))
    return findings


IMPORT_RE = re.compile(r"""import\s+(?:\{([^}]*)\}|(\w+))\s+from\s+["']@(\w+)/([^"']+)["']""")
PATCH_RE = re.compile(r"""patch\(\s*(\w+)(?:\.prototype)?\s*,\s*\{""")
JS_METHOD_RE = re.compile(r"""^\s{4}(?:async\s+|get\s+|set\s+)?(\w+)\s*\(""", re.MULTILINE)


def check_js(module: Module, rel: str, text: str, ctx: "Context") -> list[Finding]:
    """Imports from standard modules must still resolve, and patched methods must still exist."""
    findings = []
    imported: dict[str, str] = {}   # class or function name -> target file text
    for match in IMPORT_RE.finditer(text):
        names = [n.split(" as ")[-1].strip() for n in (match.group(1) or match.group(2) or "").split(",") if n.strip()]
        addon, path = match.group(3), match.group(4)
        line = text.count("\n", 0, match.start()) + 1
        if (addon, path) == ("odoo", "owl"):
            findings += _check_owl(module, rel, line, names, ctx)
            continue
        if addon in ctx.custom_names or addon not in ctx.target_paths:
            continue
        base = ctx.target_paths[addon] / "static" / "src" / path
        target = next((p for p in (base.with_suffix(".js"), base / "index.js", base) if p.is_file()), None)
        if target is None:
            findings.append(Finding(module.name, RED, "js.import_missing",
                                    f"Imports @{addon}/{path}, which no longer exists in the target version "
                                    "(the file moved or was removed), so the asset bundle fails to load.",
                                    "Find the new location of what you import and update the path.",
                                    rel, line, 0, 1.0))
            continue
        target_text = target.read_text(encoding="utf-8", errors="replace")
        for name in names:
            if not re.search(rf"\b{re.escape(name)}\b", target_text):
                findings.append(Finding(module.name, RED, "js.export_missing",
                                        f"Imports {name} from @{addon}/{path}, which no longer provides it.",
                                        "Find where it moved, or what replaced it.", rel, line, 0, 1.0))
            imported[name] = target_text
    for match in PATCH_RE.finditer(text):
        owner = match.group(1)
        if owner not in imported:
            continue
        end = text.find("\n});", match.end())
        body = text[match.end():end if end > 0 else len(text)]
        addon = next((m.group(3) for m in IMPORT_RE.finditer(text) if owner in (m.group(1) or m.group(2) or "")), "")
        addon_js = "\n".join(t for _p, t in ctx.module_texts(addon, ".js")) if addon else imported[owner]
        for method in dict.fromkeys(JS_METHOD_RE.findall(body)):
            # Only an override (it calls super.method) needs the method to exist; new methods are fine.
            if method in ("setup", "constructor") or not re.search(rf"super\.{re.escape(method)}\b", body):
                continue
            if re.search(rf"\b{re.escape(method)}\s*\(", imported[owner]) or re.search(
                    rf"\b{re.escape(method)}\s*\(", addon_js):
                continue
            findings.append(Finding(module.name, AMBER, "js.patch_missing",
                                    f"Patches {owner}.{method}(), which is not in {owner} in the target version: "
                                    "the patch may never run.",
                                    f"Check what replaced {method} in the new {owner} and patch that instead.",
                                    rel, _line_of(text[match.end():], f"{method}(") + text.count("\n", 0, match.end()),
                                    0, 1.0))
    return findings


def _check_owl(module: Module, rel: str, line: int, names: list[str], ctx: "Context") -> list[Finding]:
    """Names imported from @odoo/owl must still be exported by the Owl the target ships
    (Odoo 19: "exports.useState = ..."; Odoo 20: "useState: () => useState")."""
    web = ctx.target_paths.get("web")
    owl = web / "static" / "lib" / "owl" / "owl.js" if web else None
    if owl is None or not owl.is_file():
        return []
    source = owl.read_text(encoding="utf-8", errors="replace")
    return [Finding(module.name, RED, "js.owl_export_missing",
                    f"Imports {name} from @odoo/owl, but the Owl version in the target no longer has it.",
                    "Use the new Owl API (for example, Odoo 20's Owl replaced useState with proxy).",
                    rel, line, 0, 0.5)
            for name in names
            if not re.search(rf"exports\.{re.escape(name)}\s*=|\b{re.escape(name)}:\s*\(\)\s*=>", source)]


def _line_of(text: str, needle: str) -> int:
    index = text.find(needle)
    return text.count("\n", 0, index) + 1 if index >= 0 else 0


def check_manifest(module: Module, ctx: Context) -> list[Finding]:
    findings = []
    for dep in module.depends:
        if dep not in ctx.target_modules and dep not in ctx.custom_names:
            findings.append(Finding(module.name, RED, "depends.missing",
                                    f"Depends on module '{dep}', which does not exist in the target version "
                                    "(renamed, merged or removed; or an Enterprise / third-party module not given to the scan).",
                                    "Find the module that replaces it, or bring the third-party module along.",
                                    "__manifest__.py", 0, 0, 2.0))
    return findings


def check_python(module: Module, rel: str, text: str, ctx: Context, source: int, target: int) -> list[Finding]:
    findings = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return findings
    deprecations = [d for d in ctx.index.get("deprecations", [])
                    if (source < d["since"] <= target if source else d["since"] <= target)]
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            name, inherits = _model_info(node)
            extended = [m for m in inherits if m != name and ctx.target_model(m) is not None]
            for stmt in node.body:
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for model in extended:
                    if _calls_super(stmt) and ctx.has_method(model, stmt.name, module.name):
                        if finding := _signature_finding(module, model, stmt, ctx, rel):
                            findings.append(finding)
                    if _calls_super(stmt) and not ctx.has_method(model, stmt.name, module.name):
                        findings.append(Finding(
                            module.name, RED, "override.missing",
                            f"{stmt.name}() overrides a method of {model} that no longer exists, so super() fails "
                            "and the custom logic never runs.",
                            f"Find where {model} moved this logic in the new version and hook in there.",
                            rel, stmt.lineno, 0, 2.0))
                    for dep in deprecations:
                        if stmt.name == dep["name"] and model in dep.get("models", []):
                            findings.append(_deprecation_finding(module, dep, rel, stmt.lineno, override=True))
                for decorator in stmt.decorator_list:
                    if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                            and decorator.func.attr == "depends"):
                        for arg in decorator.args:
                            for path in _strings(arg):
                                first = path.split(".")[0]
                                for model in ([name] if name else []) + extended:
                                    if ctx.target_model(model) is not None and not ctx.has_field(model, first):
                                        findings.append(Finding(
                                            module.name, RED, "field.missing",
                                            f"@api.depends('{path}') names field '{first}', which {model} no longer has.",
                                            "Find the renamed field in the new version and update the dependency.",
                                            rel, decorator.lineno, 0, 1.0))
        elif isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name == "ref" and node.args and (xmlid := (_strings(node.args[0]) or [""])[0]):
                if "." in xmlid and xmlid.split(".")[0] not in ctx.custom_names and not ctx.has_xmlid(xmlid):
                    findings.append(Finding(module.name, AMBER, "xmlid.missing",
                                            f"env.ref('{xmlid}') points to a record the target version does not define.",
                                            "Find the new xml id (it was renamed or removed).", rel, node.lineno, 0, 0.5))
            elif name and name not in GENERIC_NAMES and not name.startswith("__"):
                for dep in deprecations:
                    if dep["name"] == name and dep["kind"] != "property":
                        findings.append(_deprecation_finding(module, dep, rel, node.lineno))
                        break
    return findings


def _signature_finding(module: Module, model: str, func: ast.FunctionDef, ctx: "Context", rel: str) -> Finding | None:
    """An override whose arguments no longer match the target method's (e.g. config_id became config)."""
    defined = ((ctx.target_model(model) or {}).get("sigs") or {}).get(func.name)
    if not defined or func.args.vararg or func.args.kwarg:
        return None
    # Compare with the modules this one depends on directly; Odoo itself is not always consistent.
    direct = [args for addon, args in defined if addon in module.depends]
    sigs = direct or [args for _addon, args in defined]
    mine = [a.arg for a in func.args.posonlyargs + func.args.args][1:]
    if mine in sigs:
        return None
    theirs = min(sigs, key=lambda s: abs(len(s) - len(mine)))
    severity = RED if len(theirs) != len(mine) else AMBER
    return Finding(module.name, severity, "override.signature",
                   f"{func.name}({', '.join(mine)}) overrides {model}.{func.name}, which takes "
                   f"({', '.join(theirs)}) in the target version. The arguments changed: check what each one now means.",
                   f"Match the new arguments ({', '.join(theirs)}) and adapt the code that uses them.",
                   rel, func.lineno, 0, 1.0)


def _deprecation_finding(module: Module, dep: dict, rel: str, line: int, override: bool = False) -> Finding:
    where = f"{dep['owner']}.{dep['name']}" if dep["owner"] else dep["name"]
    verb = "overrides" if override else "uses"
    return Finding(module.name, AMBER, f"deprecated.{dep['name']}",
                   f"The code {verb} {where}(). Odoo {dep['since']} says: \"{dep['message']}\"",
                   "Follow Odoo's message above; it still works for now but will be removed.",
                   rel, line, dep["since"], 0.5)


def check_xml(module: Module, rel: str, text: str, ctx: Context) -> list[Finding]:
    findings = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [Finding(module.name, RED, "xml.parse", f"XML file does not parse: {exc}.", "Fix the XML first.",
                        rel, exc.position[0] if exc.position else 0, 0, 0.5)]
    for record in root.iter("record"):
        if record.get("model") != "ir.ui.view":
            continue
        values = {f.get("name"): f for f in record.findall("field")}
        inherit = values.get("inherit_id")
        model_field = values.get("model")
        model = (model_field.text or "").strip() if model_field is not None else ""
        record_line = _line_of(text, f'id="{record.get("id")}"')
        if inherit is not None and (ref := inherit.get("ref", "")):
            xmlid = ref if "." in ref else f"{module.name}.{ref}"
            if xmlid.split(".")[0] not in ctx.custom_names and not ctx.has_xmlid(xmlid):
                findings.append(Finding(module.name, RED, "view.parent_missing",
                                        f"View {record.get('id')} extends {xmlid}, which the target version no longer has.",
                                        "Find the view that replaced it and move the changes there.",
                                        rel, record_line, 0, 1.5))
        arch = values.get("arch")
        if arch is not None and inherit is not None and (ref := inherit.get("ref", "")):
            parent = ref if "." in ref else f"{module.name}.{ref}"
            findings += check_anchors(module, rel, text, ctx, parent, False, arch, f"View {record.get('id')}")
        if arch is None or not model or ctx.target_model(model) is None:
            continue
        for node in arch.iter():
            expr = node.get("expr", "")
            for field in FIELD_IN_XPATH.findall(expr):
                if not ctx.has_field(model, field):
                    findings.append(Finding(module.name, RED, "view.field_missing",
                                            f"View {record.get('id')} targets field '{field}' on {model}, which the "
                                            "target version no longer has, so the view will not load.",
                                            "Point the XPath at the field's new name or a nearby element.",
                                            rel, _line_of(text, expr) or record_line, 0, 1.0))
            if node.tag == "field" and node.get("position") and (field := node.get("name")):
                if not ctx.has_field(model, field):
                    findings.append(Finding(module.name, RED, "view.field_missing",
                                            f"View {record.get('id')} places itself on field '{field}' of {model}, "
                                            "which the target version no longer has.",
                                            "Point the change at the field's new name or a nearby element.",
                                            rel, _line_of(text, f'name="{field}"') or record_line, 0, 1.0))
    # Owl / QWeb templates that extend a standard template (t-inherit).
    for template in root.iter():
        parent = template.get("t-inherit")
        if parent and "." in parent:
            findings += check_anchors(module, rel, text, ctx, parent, True, template,
                                      f"Template {template.get('t-name') or parent}")
    # A missing field is reported once, as a missing field, not also as a missing anchor.
    field_lines = {f.line for f in findings if f.rule == "view.field_missing"}
    return [f for f in findings if not (f.rule == "anchor.missing" and f.line in field_lines)]


def scan_module(module: Module, ctx: Context, source: int, target: int) -> list[Finding]:
    findings = check_manifest(module, ctx)
    for path in code_files(module.path):
        rel = path.relative_to(module.path).as_posix()
        if path.suffix == ".py":
            findings += check_python(module, rel, path.read_text(encoding="utf-8", errors="replace"), ctx, source, target)
        elif path.suffix == ".xml":
            findings += check_xml(module, rel, path.read_text(encoding="utf-8", errors="replace"), ctx)
        elif path.suffix == ".js":
            findings += check_js(module, rel, path.read_text(encoding="utf-8", errors="replace"), ctx)
    return findings
