"""The readiness report: a one-file HTML page (prints cleanly to PDF) and a short text summary.

Colours and fonts follow the live dhirennarola.com (repo: Downloads/Dhiren Business/Branding/Website/
portfolio-main, src/styles/tokens.css): navy surfaces, blue accent #2f7df6 with a blue-to-teal
gradient, Space Grotesk for headings and Inter for text. Red is the one colour the site has no token for.
"""

from datetime import date
from html import escape

from . import __version__
from .model import RED
from .scan import effort_days, module_hours

STATUS_LABEL = {"red": "Breaks", "amber": "Needs care", "green": "Ready"}


def short(text: str, limit: int = 140) -> str:
    """The first sentence of a manifest summary (App Store summaries are often keyword lists)."""
    text = " ".join((text or "").split())
    first = text.split(". ")[0].split(" | ")[0]
    return first if len(first) <= limit else first[:limit].rsplit(" ", 1)[0] + "…"


def _totals(result) -> dict:
    hours = sum(module_hours(m) for m in result.modules)
    low, high = effort_days(hours)
    count = lambda s: sum(1 for m in result.modules if m.status == s)  # noqa: E731
    return {"modules": len(result.modules), "red": count("red"), "amber": count("amber"), "green": count("green"),
            "findings": sum(len(m.findings) for m in result.modules), "low": low, "high": high}


def summary_lines(result) -> list[str]:
    t = _totals(result)
    lines = [f"Odoo {result.source_version or '?'} -> {result.target_version}: {t['modules']} modules, "
             f"{t['red']} break, {t['amber']} need care, {t['green']} ready; {t['findings']} findings; "
             f"effort about {t['low']:g}-{t['high']:g} days."]
    for module in result.modules:
        lines.append(f"  [{module.status:5}] {module.name} ({module.total_lines} lines, {len(module.findings)} findings)")
        for f in module.findings:
            lines.append(f"      {f.severity:5} {f.file}:{f.line}  {f.rule}")
    lines += [f"Note: {n}" for n in result.notes]
    return lines


CSS = """
:root{--bg:#f5f8fc;--raised:#fff;--subtle:#eaf1f9;--ink:#17273d;--soft:#46586f;--faint:#53698a;--line:#dce5f0;
--navy:#0a1a33;--navy-line:#1e3556;--td:#e9eff8;--td-soft:#a9bbd4;--accent:#2f7df6;--accent-strong:#1e63d6;
--accent-ink:#14448f;--accent-tint:#e8f0fe;--accent-ondark:#5b9bff;--teal:#12b5c9;
--grad:linear-gradient(135deg,#2f7df6,#12b5c9);--ok:#14794e;--ok-tint:#e5f6ee;--amber:#b04506;
--amber-tint:#fdeee2;--red:#c62828;--red-tint:#fdecec;--radius:12px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 'Inter',ui-sans-serif,system-ui,'Segoe UI',Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:48px 24px 64px}
h1,h2{font-family:'Space Grotesk','Segoe UI',ui-sans-serif,sans-serif;font-weight:600;line-height:1.2;margin:0}
.hero{background:var(--navy);color:var(--td);border-radius:var(--radius);padding:32px 28px;position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;left:0;right:0;bottom:0;height:4px;background:var(--grad)}
.hero .eyebrow{color:var(--accent-ondark)}.hero .lead{color:var(--td-soft)}
h1{font-size:2.3rem}h2{font-size:1.45rem;margin:40px 0 12px}
.eyebrow{color:var(--accent);font-weight:600;font-size:.82rem;letter-spacing:.08em;text-transform:uppercase}
.lead{color:var(--soft);font-size:1.08rem;max-width:720px;margin:12px 0 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:28px}
.card{background:var(--raised);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px}
.card b{display:block;font-family:'Space Grotesk','Segoe UI',ui-sans-serif,sans-serif;font-size:1.9rem;line-height:1.1}
.card span{color:var(--faint);font-size:.85rem}
table{width:100%;border-collapse:collapse;background:var(--raised);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;font-size:.93rem}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--subtle);color:var(--soft);font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:0}.num{text-align:right;white-space:nowrap}
.table-wrap{overflow-x:auto;border-radius:var(--radius)}.table-wrap table{min-width:560px}
.pill{display:inline-block;border-radius:999px;padding:2px 10px;font-size:.78rem;font-weight:600;white-space:nowrap}
.red{background:var(--red-tint);color:var(--red)}.amber{background:var(--amber-tint);color:var(--amber)}
.green{background:var(--ok-tint);color:var(--ok)}
.module{background:var(--raised);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px;margin-top:14px;break-inside:avoid}
.module h3{margin:0;font-size:1.08rem}.meta{color:var(--faint);font-size:.85rem}
.finding{border-top:1px solid var(--line);padding:12px 0 2px;display:grid;grid-template-columns:96px 1fr;gap:12px}
.finding>div{min-width:0;overflow-wrap:anywhere}
.where{font-family:ui-monospace,Consolas,monospace;font-size:.8rem;color:var(--accent-ink);word-break:break-all}
.fix{color:var(--soft);font-size:.9rem;margin-top:4px}.fix::before{content:"Fix: ";font-weight:600;color:var(--ink)}
.note{background:var(--accent-tint);border-radius:var(--radius);padding:12px 16px;color:var(--accent-ink);font-size:.92rem;margin-top:10px}
footer{margin-top:48px;color:var(--faint);font-size:.85rem;border-top:1px solid var(--line);padding-top:16px}
a{color:var(--accent)}
@media (max-width:640px){main{padding:28px 16px}.finding{grid-template-columns:1fr;gap:4px}h1{font-size:1.8rem}}
@media print{body{background:#fff}main{padding:0}.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}.module,.card,table{box-shadow:none}}
"""


def render_html(result, client: str = "") -> str:
    t = _totals(result)
    source = f"Odoo {result.source_version}" if result.source_version else "your current version"
    rows = []
    for m in result.modules:
        low, high = effort_days(module_hours(m))
        rows.append(f"<tr><td><b>{escape(m.name)}</b><div class='meta'>{escape(short(m.summary))}</div></td>"
                    f"<td><span class='pill {m.status}'>{STATUS_LABEL[m.status]}</span></td>"
                    f"<td class='num'>{m.total_lines}</td><td class='num'>{len(m.findings)}</td>"
                    f"<td class='num'>{low:g}-{high:g} d</td></tr>")
    details = []
    for m in result.modules:
        items = []
        for f in m.findings:
            where = f"{f.file}:{f.line}" if f.line else f.file
            items.append(f"<div class='finding'><div><span class='pill {f.severity}'>"
                         f"{'Breaks' if f.severity == RED else 'Needs care'}</span></div><div>"
                         f"<div>{escape(f.message)}</div><div class='where'>{escape(where)}"
                         f"{f' · since Odoo {f.since}' if f.since else ''}</div>"
                         f"<div class='fix'>{escape(f.fix)}</div></div></div>")
        langs = ", ".join(f"{n} {lang}" for lang, n in sorted(m.lines.items(), key=lambda x: -x[1]))
        details.append(f"<div class='module'><h3>{escape(m.name)} <span class='pill {m.status}'>"
                       f"{STATUS_LABEL[m.status]}</span></h3><div class='meta'>Version {escape(m.version)} · "
                       f"{escape(langs) or 'no code'}</div>"
                       + ("".join(items) or "<p class='meta'>Nothing found that breaks or is deprecated.</p>")
                       + "</div>")
    notes = "".join(f"<div class='note'>{escape(n)}</div>" for n in result.notes)
    title = f"Odoo upgrade readiness{(' · ' + escape(client)) if client else ''}"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main>
<header class="hero"><div class="eyebrow">Upgrade Readiness Report{(' · ' + escape(client)) if client else ''}</div>
<h1>{source} to Odoo {result.target_version}</h1>
<p class="lead">{t['modules']} custom modules checked against the Odoo {result.target_version} source:
what will break, what Odoo itself has deprecated, and the effort. Generated {date.today():%d %b %Y}.</p></header>
<div class="cards">
<div class="card"><b>{t['red']}</b><span>modules that break</span></div>
<div class="card"><b>{t['amber']}</b><span>modules that need care</span></div>
<div class="card"><b>{t['green']}</b><span>modules ready</span></div>
<div class="card"><b>{t['low']:g}–{t['high']:g}</b><span>working days, estimate</span></div>
</div>{notes}
<h2>Modules</h2>
<div class="table-wrap"><table><thead><tr><th>Module</th><th>Status</th><th class="num">Lines</th><th class="num">Findings</th><th class="num">Effort</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<h2>Findings, module by module</h2>{''.join(details)}
<h2>How to read this</h2>
<p class="meta"><b>Breaks</b>: the module will fail to install or a feature stops working on Odoo {result.target_version}.
<b>Needs care</b>: still works, but Odoo has deprecated it or it needs a check. The effort range covers porting, the
fixes listed and testing; it is confirmed in the fixed quote after a walkthrough. {t['findings']} findings in total;
{result.rules_harvested} of the rules applied were read from Odoo {result.target_version}'s own deprecation notes.</p>
<footer>Odoo Upgrade Readiness Check by Dhiren Narola · <a href="https://dhirennarola.com">dhirennarola.com</a> ·
hello@dhirennarola.com · scanner {__version__}</footer>
</main></body></html>"""
