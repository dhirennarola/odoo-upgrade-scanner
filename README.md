# Odoo Upgrade Readiness Scanner

Reads a folder of custom Odoo modules and the source of the **target** Odoo version, and
reports, per module, what will break, what Odoo itself has deprecated, and the effort.
It powers the fixed-scope *Odoo Upgrade Readiness Check* by Dhiren Narola
([dhirennarola.com](https://dhirennarola.com)).

Nothing is installed, imported, run or sent anywhere: the code is only read.

## Run

```bash
python -m upgrade_scanner path/to/custom_addons --odoo path/to/odoo20/odoo --enterprise path/to/odoo20/enterprise --html report.html --json report.json --client "Acme Ltd"
```

- `path/to/custom_addons`: a folder of modules (or one module).
- `--odoo`: the target version's source (the folder with `odoo-bin`).
- `--enterprise`: optional; without it, dependencies on Enterprise modules show as missing.
- `--source 16`: optional; by default the version is read from the manifests.

The first run reads the whole target source (about 2 minutes) and caches an index in
`%LOCALAPPDATA%\odoo-upgrade-scanner` (Windows) or `~/.cache/odoo-upgrade-scanner`
(macOS and Linux). Later runs take seconds.

Python 3.11 or newer, standard library only: nothing to install.

## What it checks

| Check | Catches |
| --- | --- |
| Hand-checked rules (`rules.py`) | `attrs` / `states` in views (17), `odoo.define` (17), `name_get`, `tree` views and `view_mode` (18), `group_operator` (18), `type='json'` routes, `request.uid/cr/context`, `<>` / `==` domains (19) |
| Odoo's own deprecations (`index.py`) | Every `@deprecated("Since X")`, `@api.deprecated` and `warnings.warn("Since X...")` in the target core, matched against calls and overrides |
| Dependencies (`depcheck.py`) | Manifest modules that no longer exist; overridden methods that are gone; changed method arguments (checked against the modules you depend on); fields in `@api.depends` and view XPaths; parent views (`inherit_id`); `env.ref` xml ids |
| XPath anchors | Every hook of an inherited view or Owl template (`t-inherit`) must still exist in the parent |
| JavaScript | `@module/path` imports whose file moved, names a file no longer exports, `@odoo/owl` names the new Owl lacks, patched methods (that call `super`) that are gone |

Each finding has a file, a line, a severity (**Breaks** / **Needs care**), a plain-English
message, a fix and an hours estimate. Effort per module = 1 hour + 1 hour per 600 lines of
testing + the findings, shown as a range in working days.

## Validation

Tested on Dhiren's three App Store apps (Chatter Access Control, Chatter Panel Control,
POS Product Quick Favourites), each ported by hand from 18 to 19 to 20:

- 18 → 19: 6 findings, all real (POS files that moved in 19 and a POS template anchor that is gone).
- 19 → 20: 5 findings, all real, matching every code change of the real port (the Chatter
  path move, `ui_service` → `ui_utils`, Owl's `useState` → `proxy`).
- Not caught yet: renamed JavaScript properties (`thread.canPostMessage`) and changed JS
  method arguments. A real install test on the target version (planned) covers these.

## Tests

```bash
python -m pytest -q tests
```

## Contributing

Issues and pull requests are welcome. Most useful: a real upgrade where the scanner missed
something or flagged something that was fine. Please include the Odoo versions, the module
(or a small piece of it) and what you expected. New rules go in `rules.py` with a test in
`tests/test_scanner.py`.

## Licence

LGPL-3.0, the same licence as Odoo Community. See [LICENSE](LICENSE).
