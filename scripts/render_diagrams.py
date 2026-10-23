"""Render the Mermaid source under each SVG preview in the architecture docs.

Requires Node/npm. The pinned Mermaid CLI supplies the renderer and Chromium.
Pass --puppeteer-config to use an existing browser instead.
"""

import argparse
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docs/assets/diagrams/mermaid-config.json"
DIAGRAM = re.compile(
    r"!\[[^\]]*\]\(([^)]+\.svg)\)\s*"
    r"<details>\s*<summary>Mermaid source</summary>\s*"
    r"```mermaid\n(.*?)```",
    re.DOTALL,
)


def natural_size(path: Path) -> None:
    """Keep embedded images at their natural size, with Markdown scaling down as needed."""
    svg = path.read_text()
    _, _, width, height = ET.fromstring(svg).attrib["viewBox"].split()
    svg = re.sub(
        r'(<svg\b[^>]*?)\bwidth="[^"]*"',
        rf'\g<1>width="{width}" height="{height}"',
        svg,
        count=1,
    )
    path.write_text(svg)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puppeteer-config", type=Path)
    args = parser.parse_args()
    count = 0
    with tempfile.TemporaryDirectory(prefix="cafe-diagrams-") as directory:
        source = Path(directory) / "diagram.mmd"
        for relative in ("README.md", "docs/architecture.md"):
            document = ROOT / relative
            for target, mermaid in DIAGRAM.findall(document.read_text()):
                output = (document.parent / target).resolve()
                output.relative_to(ROOT / "docs/assets/diagrams")
                output.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(mermaid)
                command = [
                    "npx",
                    "--yes",
                    "--package=@mermaid-js/mermaid-cli@12.0.0",
                    "mmdc",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--configFile",
                    str(CONFIG),
                    "--backgroundColor",
                    "white",
                    "--no-font-embed",
                ]
                if args.puppeteer_config:
                    command.extend(["--puppeteerConfigFile", str(args.puppeteer_config)])
                subprocess.run(command, check=True)
                natural_size(output)
                count += 1
    if not count:
        raise SystemExit("No Mermaid preview/source pairs found.")
    print(f"Rendered {count} SVG diagrams.")


if __name__ == "__main__":
    main()
