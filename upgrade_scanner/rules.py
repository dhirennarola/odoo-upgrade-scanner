"""Hand-checked breaking changes between Odoo versions.

Each rule says which version changed it. A rule applies when the modules are older than
that version and the target is that version or newer. Checked against the Odoo 18, 19 and
20 source on 24 Oct 2026 (where a rule could only be checked as "gone by 18", it says so).
Deprecations Odoo announces itself ("Since 19.0, ...") come from harvest.py instead.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .model import AMBER, RED, Finding


@dataclass(frozen=True)
class LineRule:
    """A rule found by a regular expression on single lines of one kind of file."""
    id: str
    since: int
    severity: str
    suffixes: tuple
    pattern: re.Pattern
    message: str
    fix: str
    hours: float


LINE_RULES = (
    LineRule("views.attrs", 17, RED, (".xml",), re.compile(r"\battrs\s*="),
             'The view uses attrs="...". Since Odoo 17 views read invisible / readonly / required directly; '
             "Odoo 17+ refuses to load a view that still has attrs.",
             'Rewrite attrs="{\'invisible\': [...]}" as invisible="python expression" (same for readonly and required).',
             0.5),
    LineRule("views.states", 17, RED, (".xml",), re.compile(r"<(field|button)\b[^>]*\bstates\s*="),
             'The view uses states="...", which Odoo 17+ no longer accepts.',
             "Use invisible=\"state not in ('draft', 'sent')\" instead.", 0.25),
    LineRule("views.tree", 18, RED, (".xml",), re.compile(r"<tree\b|</tree>"),
             "List views are called <list> since Odoo 18; the view type 'tree' no longer exists.",
             "Rename <tree> to <list>.", 0.25),
    LineRule("actions.view_mode_tree", 18, RED, (".xml", ".py"),
             re.compile(r"""(view_mode['"]?\s*[:=>]\s*['"]?[^'"<]*\btree\b|<field name="view_mode">[^<]*\btree\b)"""),
             "An action opens the 'tree' view mode, which Odoo 18+ calls 'list'.",
             "Replace tree with list in view_mode (and in view_ids / views lists).", 0.25),
    LineRule("fields.group_operator", 18, AMBER, (".py",), re.compile(r"\bgroup_operator\s*="),
             "Field option group_operator was renamed to aggregator in Odoo 18 (still accepted, with a warning).",
             "Rename group_operator= to aggregator=.", 0.1),
    LineRule("js.odoo_define", 17, RED, (".js",), re.compile(r"\bodoo\.define\s*\("),
             "Old-style JavaScript module (odoo.define). The legacy module system is gone in Odoo 18 "
             "(checked in the 18 source; removed with the Odoo 17 front-end rewrite).",
             "Rewrite as an ES module (/** @odoo-module **/ with import / export) and Owl components.", 4.0),
    LineRule("http.route_json", 19, AMBER, (".py",), re.compile(r"""@(http\.)?route\([^)]*type\s*=\s*['"]json['"]"""),
             "Since Odoo 19, @route(type='json') is a deprecated alias of type='jsonrpc'.",
             "Use type='jsonrpc'.", 0.1),
    LineRule("http.request_shortcuts", 19, AMBER, (".py",), re.compile(r"\brequest\.(context|uid|cr)\b"),
             "Since Odoo 19, request.context / request.uid / request.cr are deprecated.",
             "Use request.env.context, request.env.uid and request.env.cr.", 0.1),
    LineRule("domain.old_operators", 19, AMBER, (".py", ".xml"), re.compile(r"""['"](<>|==)['"]"""),
             "Since Odoo 19, the domain operators '<>' and '==' are deprecated.",
             "Use '!=' and '=' instead.", 0.1),
)

# Methods that no longer exist in the target, by the version that removed them.
REMOVED_METHODS = {
    "name_get": (18, RED, "name_get() is gone from the ORM in Odoo 18 (deprecated in 17).",
                 "Override _compute_display_name and read record.display_name instead.", 1.0),
    "user_has_groups": (18, RED, "user_has_groups() is gone in Odoo 18.",
                        "Use self.env.user.has_group('module.group_xmlid').", 0.25),
    "fields_view_get": (16, RED, "fields_view_get() was replaced by get_views() / _get_view().",
                        "Override _get_view() for arch changes, get_views() for the full answer.", 1.5),
}


def applies(since: int, source: int, target: int) -> bool:
    return source < since <= target if source else since <= target


def check_lines(module: str, rel: str, text: str, suffix: str, source: int, target: int) -> list[Finding]:
    findings = []
    rules = [r for r in LINE_RULES if suffix in r.suffixes and applies(r.since, source, target)]
    if not rules:
        return findings
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("#", "//", "<!--")):
            continue
        for rule in rules:
            if rule.pattern.search(line):
                findings.append(Finding(module, rule.severity, rule.id, rule.message, rule.fix, rel, number,
                                        rule.since, rule.hours))
    return findings


def check_python(module: str, rel: str, tree: ast.AST, source: int, target: int) -> list[Finding]:
    """Definitions and calls of removed methods."""
    findings = []
    for node in ast.walk(tree):
        name = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name in REMOVED_METHODS:
            since, severity, message, fix, hours = REMOVED_METHODS[name]
            if applies(since, source, target):
                findings.append(Finding(module, severity, f"removed.{name}", message, fix, rel, node.lineno,
                                        since, hours))
    return findings


def scan_file(module: str, module_path: Path, path: Path, source: int, target: int) -> list[Finding]:
    rel = path.relative_to(module_path).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    findings = check_lines(module, rel, text, path.suffix, source, target)
    if path.suffix == ".py":
        try:
            findings += check_python(module, rel, ast.parse(text), source, target)
        except SyntaxError as exc:
            findings.append(Finding(module, RED, "python.syntax", f"Python file does not parse: {exc.msg}.",
                                    "Fix the syntax error first.", rel, exc.lineno or 0, 0, 0.5))
    return findings
