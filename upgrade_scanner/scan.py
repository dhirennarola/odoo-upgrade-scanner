"""Run every check on a folder of custom modules and estimate the effort."""

from pathlib import Path

from . import depcheck, rules
from .index import load_index
from .inventory import code_files, find_modules, source_version
from .model import SEVERITY_ORDER, ScanResult

HOURS_PER_DAY = 6          # productive hours in a working day
BASE_HOURS = 1.0           # read, port the manifest and test even a clean module
LINES_PER_TEST_HOUR = 600  # testing time grows with the size of the module


def module_hours(module) -> float:
    return BASE_HOURS + module.total_lines / LINES_PER_TEST_HOUR + sum(f.hours for f in module.findings)


def effort_days(hours: float) -> tuple[float, float]:
    """A range in days (rounded to half days): the low end assumes no surprises."""
    days = hours / HOURS_PER_DAY
    return max(0.5, round(days * 0.8 * 2) / 2), max(0.5, round(days * 1.5 * 2) / 2)


def scan(path: Path, odoo_root: Path, enterprise: Path | None = None, source: int = 0,
         refresh_index: bool = False) -> ScanResult:
    modules = find_modules(path)
    if not modules:
        raise ValueError(f"No Odoo modules (folders with __manifest__.py) found in {path}.")
    index = load_index(odoo_root, enterprise, refresh=refresh_index)
    target = index["version"]
    source = source or source_version(modules)
    result = ScanResult(modules=modules, source_version=source, target_version=target,
                        rules_harvested=len([d for d in index["deprecations"] if source < d["since"] <= target]))
    if not source:
        result.notes.append("The manifests don't say which Odoo version the modules are for, so every rule up to "
                            f"Odoo {target} was applied. Pass --source to narrow it.")
    if source >= target:
        result.notes.append(f"The modules already say Odoo {source}; nothing to upgrade to Odoo {target}.")
    if not enterprise:
        result.notes.append("Scanned against Odoo Community only. Dependencies on Enterprise modules show as missing "
                            "unless you pass --enterprise.")
    ctx = depcheck.Context(index, modules)
    for module in modules:
        for file in code_files(module.path):
            module.findings += rules.scan_file(module.name, module.path, file, source, target)
        module.findings += depcheck.scan_module(module, ctx, source, target)
        module.findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.file, f.line))
    return result
