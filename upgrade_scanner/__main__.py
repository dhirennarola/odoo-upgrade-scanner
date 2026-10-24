"""Command line:

    python -m upgrade_scanner PATH --odoo C:\\odoo20\\odoo [--enterprise C:\\odoo20\\enterprise]
                              [--source 17] [--html report.html] [--json report.json] [--client "Acme Ltd"]

PATH is a folder of custom modules (or one module). --odoo is the TARGET version's source
folder (the one with odoo-bin). Nothing is installed, imported or sent anywhere.
"""

import argparse
import json
import sys
from pathlib import Path

from .report import render_html, summary_lines
from .scan import scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="upgrade_scanner", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path)
    parser.add_argument("--odoo", type=Path, required=True, help="target Odoo source (folder with odoo-bin)")
    parser.add_argument("--enterprise", type=Path, help="target Enterprise addons folder")
    parser.add_argument("--source", type=int, default=0, help="Odoo version the modules are written for")
    parser.add_argument("--html", type=Path, help="write the HTML report here")
    parser.add_argument("--json", type=Path, help="write the findings as JSON here")
    parser.add_argument("--client", default="", help="client name on the report")
    parser.add_argument("--refresh-index", action="store_true", help="re-read the target source")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        result = scan(args.path, args.odoo, args.enterprise, args.source, args.refresh_index)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print("\n".join(summary_lines(result)))
    if args.html:
        args.html.write_text(render_html(result, args.client), encoding="utf-8")
        print(f"HTML report: {args.html}")
    if args.json:
        args.json.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        print(f"JSON: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
