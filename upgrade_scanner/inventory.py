"""Intake and inventory: find the custom modules in a folder, read their manifests and
count their code. Nothing is imported or run: manifests are read with ast.literal_eval."""

import ast
import re
from pathlib import Path

from .model import Module

LANGUAGES = {".py": "Python", ".xml": "XML", ".js": "JavaScript", ".scss": "SCSS", ".css": "CSS",
             ".csv": "Data (CSV)"}
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "i18n", "static/lib"}
VERSION_RE = re.compile(r"^(\d{1,2})\.0[.\d]*$")


def read_manifest(path: Path) -> dict:
    """The manifest as a dict ({} when it can't be read)."""
    try:
        data = ast.literal_eval(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, SyntaxError):
        return {}
    return data if isinstance(data, dict) else {}


def odoo_major(version: str) -> int:
    """'17.0.1.0.0' -> 17; a version without the Odoo prefix ('1.0') -> 0."""
    match = VERSION_RE.match((version or "").strip())
    return int(match.group(1)) if match and int(match.group(1)) >= 8 else 0


def code_files(module_path: Path):
    """Every file of the module worth scanning, skipping caches, translations and vendored libraries."""
    for path in sorted(module_path.rglob("*")):
        if not path.is_file() or path.suffix not in LANGUAGES:
            continue
        rel = path.relative_to(module_path).as_posix()
        if any(part in SKIP_DIRS for part in path.parts) or "static/lib/" in rel:
            continue
        yield path


def count_lines(path: Path) -> int:
    """Non-empty lines."""
    try:
        return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
    except OSError:
        return 0


def find_modules(root: Path) -> list[Module]:
    """The modules in `root` (a folder of modules, or one module folder), sorted by name."""
    root = Path(root)
    manifests = [root / "__manifest__.py"] if (root / "__manifest__.py").exists() else sorted(
        p for p in root.glob("*/__manifest__.py"))
    modules = []
    for manifest in manifests:
        data = read_manifest(manifest)
        module = Module(name=manifest.parent.name, path=manifest.parent, version=str(data.get("version", "")),
                        depends=list(data.get("depends", []) or []), summary=str(data.get("summary", "") or ""))
        module.odoo_version = odoo_major(module.version)
        for path in code_files(module.path):
            language = LANGUAGES[path.suffix]
            module.lines[language] = module.lines.get(language, 0) + count_lines(path)
        modules.append(module)
    return modules


def source_version(modules: list[Module]) -> int:
    """The Odoo version the modules are written for: the most common manifest version."""
    counts: dict[int, int] = {}
    for module in modules:
        if module.odoo_version:
            counts[module.odoo_version] = counts.get(module.odoo_version, 0) + 1
    return max(counts, key=counts.get) if counts else 0
