"""The plain data the scanner passes around: modules, findings and the scan result."""

from dataclasses import asdict, dataclass, field
from pathlib import Path

RED, AMBER = "red", "amber"
SEVERITY_ORDER = {RED: 0, AMBER: 1}


@dataclass
class Finding:
    """One thing that will (red) or may (amber) need work on the target version."""
    module: str
    severity: str           # red | amber
    rule: str               # short id, e.g. "views.attrs" or "deprecated.read_group"
    message: str            # plain English: what is wrong
    fix: str                # plain English: what to do
    file: str = ""          # path inside the module
    line: int = 0
    since: int = 0          # the Odoo version that changed it (0 = unknown)
    hours: float = 0.0      # effort estimate for this finding


@dataclass
class Module:
    """One custom module and what the scanner learned about it."""
    name: str
    path: Path
    version: str = ""                       # manifest version, e.g. "17.0.1.0.0"
    odoo_version: int = 0                   # 17
    depends: list[str] = field(default_factory=list)
    summary: str = ""
    lines: dict[str, int] = field(default_factory=dict)   # language -> lines of code
    findings: list[Finding] = field(default_factory=list)

    @property
    def status(self) -> str:
        """green, amber or red: the worst finding, green when there is none."""
        if any(f.severity == RED for f in self.findings):
            return "red"
        return "amber" if self.findings else "green"

    @property
    def total_lines(self) -> int:
        return sum(self.lines.values())


@dataclass
class ScanResult:
    modules: list[Module]
    source_version: int
    target_version: int
    rules_harvested: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_version": self.source_version,
            "target_version": self.target_version,
            "rules_harvested": self.rules_harvested,
            "notes": self.notes,
            "modules": [
                {**{k: v for k, v in asdict(m).items() if k not in ("path", "findings")},
                 "path": str(m.path), "status": m.status,
                 "findings": [asdict(f) for f in m.findings]}
                for m in self.modules
            ],
        }
