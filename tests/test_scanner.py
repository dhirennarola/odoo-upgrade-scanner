"""Every check on a tiny fake Odoo target and a custom module that breaks in each known way."""

from pathlib import Path

import pytest

from upgrade_scanner import index as index_mod
from upgrade_scanner.report import render_html, short
from upgrade_scanner.scan import effort_days, scan


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture(autouse=True)
def own_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(index_mod, "cache_dir", lambda: tmp_path / "cache")


@pytest.fixture
def target(tmp_path) -> Path:
    """A fake Odoo 20 with a framework, a 'sale' addon, a 'web' addon with Owl, and a deprecation."""
    root = tmp_path / "odoo20"
    write(root, "odoo/release.py", "version_info = (20, 0, 0, 'final', 0, '')\n")
    write(root, "odoo/orm/models.py", '''
class BaseModel:
    def write(self, vals): pass
    def _compute_display_name(self): pass
    @deprecated("Since 20.0, use check_field_access()")
    def _check_field_access(self, field, operation): pass
''')
    write(root, "odoo/addons/base/__manifest__.py", "{'name': 'Base', 'version': '1.0'}")
    write(root, "addons/sale/__manifest__.py", "{'name': 'Sales', 'version': '1.0', 'depends': ['base']}")
    write(root, "addons/sale/models/sale.py", '''
from odoo import fields, models
class SaleOrder(models.Model):
    _name = "sale.order"
    partner_id = fields.Many2one("res.partner")
    amount_total = fields.Monetary()
    def action_confirm(self): pass
    def _prepare_invoice(self, config): pass
''')
    write(root, "addons/sale/views/sale_views.xml", '''<odoo>
<record id="view_order_form" model="ir.ui.view"><field name="model">sale.order</field>
<field name="arch" type="xml"><form><group name="sale_header"><field name="partner_id"/></group></form></field></record>
</odoo>''')
    write(root, "addons/sale/static/src/order_line.js", "export class OrderLine { setup() {} getPrice() {} }\n")
    write(root, "addons/sale/static/src/order_line.xml",
          '<templates><t t-name="sale.OrderLine"><div class="o_line"><t t-foreach="this.lines" t-as="l"/></div></t></templates>')
    write(root, "addons/web/__manifest__.py", "{'name': 'Web', 'version': '1.0'}")
    write(root, "addons/web/static/src/core/utils/patch.js", "export function patch(obj, ext) {}\n")
    write(root, "addons/web/static/lib/owl/owl.js", "var owl = { proxy: () => proxy, onMounted: () => onMounted };\n")
    return root


@pytest.fixture
def custom(tmp_path) -> Path:
    """An Odoo 18 module that hits every check once, plus things that must NOT be flagged."""
    root = tmp_path / "custom"
    write(root, "my_sale/__manifest__.py",
          "{'name': 'My Sale', 'version': '18.0.1.0.0', 'summary': 'Better sales. | sales | odoo', "
          "'depends': ['sale', 'sale_old_extra']}")
    write(root, "my_sale/models/sale.py", '''
from odoo import api, fields, models
from odoo.http import request, route
class SaleOrder(models.Model):
    _inherit = "sale.order"
    margin_note = fields.Char(group_operator="sum")
    def name_get(self):
        return []
    def action_cancel_old(self):
        return super().action_cancel_old()
    def _prepare_invoice(self, config_id):
        return super()._prepare_invoice(config_id)
    @api.depends("amount_untaxed", "partner_id.name", "margin_note")
    def _compute_x(self):
        self._check_field_access(None, "read")
        return self.env.ref("sale.view_order_form_gone")
    @route("/x", type="json")
    def x(self):
        return request.uid
''')
    write(root, "my_sale/views/views.xml", '''<odoo>
<record id="view_form" model="ir.ui.view"><field name="model">sale.order</field>
<field name="inherit_id" ref="sale.view_order_form"/>
<field name="arch" type="xml">
  <xpath expr="//group[@name='sale_header']" position="inside"><field name="margin_note" attrs="{'invisible': [('state','=','x')]}"/></xpath>
  <xpath expr="//group[@name='sale_footer']" position="after"><tree/></xpath>
  <field name="client_order_ref" position="after"/>
</field></record>
<record id="view_gone" model="ir.ui.view"><field name="model">sale.order</field>
<field name="inherit_id" ref="sale.view_order_tree_old"/><field name="arch" type="xml"><list/></field></record>
</odoo>''')
    write(root, "my_sale/static/src/line.js", '''/** @odoo-module **/
import { useState, onMounted } from "@odoo/owl";
import { OrderLine } from "@sale/order_line";
import { Gone } from "@sale/old/place";
import { patch } from "@web/core/utils/patch";
patch(OrderLine.prototype, {
    getPrice() {
        return super.getPrice(...arguments);
    },
    getOldTotal() {
        return super.getOldTotal(...arguments);
    },
    myNewHelper() {
        return 1;
    },
});
''')
    write(root, "my_sale/static/src/line.xml", '''<templates>
<t t-name="my_sale.Line" t-inherit="sale.OrderLine" t-inherit-mode="extension">
  <xpath expr="//t[@t-foreach='this.lines']" position="before"><span/></xpath>
  <xpath expr="//t[@t-foreach='props.lines']" position="before"><span/></xpath>
</t></templates>''')
    write(root, "my_sale/static/src/legacy.js", "odoo.define('my_sale.legacy', function (require) {});\n")
    return root


def findings(result) -> dict[str, list]:
    out: dict[str, list] = {}
    for module in result.modules:
        for f in module.findings:
            out.setdefault(f.rule, []).append(f)
    return out


def test_every_check_fires_once_and_new_things_are_not_flagged(target, custom):
    result = scan(custom, target)
    assert result.source_version == 18 and result.target_version == 20
    rules = findings(result)
    # Hand-checked rules
    assert "views.attrs" not in rules  # attrs changed in 17: an 18 module is past it
    assert "views.tree" not in rules  # also an 18 change: not applied from 18
    assert "removed.name_get" not in rules and "js.odoo_define" not in rules  # 18 and 17 changes
    assert rules["http.route_json"][0].line == 17 and rules["http.request_shortcuts"]
    # Dependencies
    assert [f.message for f in rules["depends.missing"]][0].startswith("Depends on module 'sale_old_extra'")
    assert rules["override.missing"][0].message.startswith("action_cancel_old()")
    assert "config_id" in rules["override.signature"][0].message and "(config)" in rules["override.signature"][0].message
    missing_fields = {f.message.split("'")[1] for f in rules["field.missing"]}
    assert missing_fields == {"amount_untaxed"}  # partner_id exists, margin_note is the module's own field
    assert rules["xmlid.missing"][0].message.startswith("env.ref('sale.view_order_form_gone')")
    assert "sale.view_order_tree_old" in rules["view.parent_missing"][0].message
    assert {f.message.split("'")[1] for f in rules["view.field_missing"]} == {"client_order_ref"}
    anchors = [f.message for f in rules["anchor.missing"]]
    assert any('name="sale_footer"' in m for m in anchors) and any('t-foreach="props.lines"' in m for m in anchors)
    assert not any("sale_header" in m or "this.lines" in m for m in anchors)
    # JavaScript
    assert [f.message.split()[1] for f in rules["js.owl_export_missing"]] == ["useState"]
    assert len(rules["js.import_missing"]) == 1 and "@sale/old/place" in rules["js.import_missing"][0].message
    patched = [f.message for f in rules["js.patch_missing"]]
    assert patched == [p for p in patched if "getOldTotal" in p] and len(patched) == 1  # new helper not flagged
    # Deprecations Odoo announces itself
    assert "check_field_access" in rules["deprecated._check_field_access"][0].message


def test_rules_by_version_window(target, custom):
    """Scanned as Odoo 16 code, the 17 and 18 changes apply too."""
    rules = findings(scan(custom, target, source=16))
    assert rules["views.attrs"] and rules["views.tree"] and rules["removed.name_get"] and rules["js.odoo_define"]
    assert rules["fields.group_operator"]


def test_status_effort_and_report(target, custom):
    result = scan(custom, target)
    module = result.modules[0]
    assert module.status == "red" and module.total_lines > 0
    low, high = effort_days(12)
    assert (low, high) == (1.5, 3.0)
    html = render_html(result, "Acme Ltd")
    assert "Odoo 18 to Odoo 20" in html and "Acme Ltd" in html and "action_cancel_old" in html
    assert short("Better sales. | sales | odoo") == "Better sales"
    assert "Enterprise" in " ".join(result.notes)


def test_index_is_cached(target, tmp_path):
    first = index_mod.load_index(target)
    (target / "addons" / "sale" / "models" / "sale.py").write_text("", encoding="utf-8")
    assert index_mod.load_index(target)["models"] == first["models"]  # from the cache
    assert "sale.order" not in index_mod.load_index(target, refresh=True)["models"]


def test_no_modules_is_a_clear_error(target, tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="No Odoo modules"):
        scan(tmp_path / "empty", target)
