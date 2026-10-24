# Odoo Upgrade Readiness Scanner: notes for Claude

- Dhiren Narola's own product (not TTS, not a client). Never put client or TTS code in this repo;
  scan client code only with written permission, outside the repo.
- Python 3.11+, standard library only (no install needed). Tests: `python -m pytest -q tests`
  (fake target tree in the test; never needs the real Odoo source).
- Branding of the report follows dhirennarola.com (`Documents\GitHub\portfolio\src\styles\tokens.css`):
  warm neutrals, one indigo accent #4263eb, Fraunces headings, Inter text. Take colours from there.
- Real sources on this PC: Odoo 18/19/20 in `Desktop\odoo\odoo18|19|20\odoo` (+ `enterprise`).
  Odoo 16/17 source is not here yet, so rules for 16→17 are from knowledge and marked so.
- Index cache: `%LOCALAPPDATA%\odoo-upgrade-scanner\index-*.json`; bump `CACHE_VERSION` in
  `index.py` whenever the index shape changes.
- Rules of thumb learned on Dhiren's apps (24 Oct 2026):
  - A module's own definition of a method never counts as "the method still exists" (`has_method(..., module)`).
  - Odoo itself is not consistent on argument names (19: point_of_sale `_load_pos_data_fields(config_id)`,
    other POS addons `(config)`), so signatures are compared with the modules the custom module depends on.
  - JS patches add new methods freely; only a patched method that calls `super.x` must exist in the target.
  - Odoo 20 Owl exports look like `name: () => name`; Odoo 19 like `exports.name = name`.
- Plan and offer: doc "Odoo Upgrade Readiness Offer" https://claude.ai/artifact/5p3ESbFjcK51eaMG8ND4Y9
  (next: Claude summary step, optional install test in Docker, effort model tuned on real migrations).
