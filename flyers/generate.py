#!/usr/bin/env python3
"""Typst flyer generator — accepts JSON params, renders PDF + PNG."""

import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

TEMPLATES_DIR = Path("/app/templates")
OUTPUT_DIR = Path("/app/output")


def list_templates():
    """List available templates."""
    templates = []
    for f in sorted(TEMPLATES_DIR.glob("*.typ")):
        # Read first comment line as description
        desc = ""
        with open(f) as fh:
            first_line = fh.readline().strip()
            if first_line.startswith("//"):
                desc = first_line.lstrip("/ ").strip()
        templates.append({"name": f.stem, "description": desc})
    return templates


def generate_params_file(params: dict, path: Path):
    """Write a Typst file with variable definitions from params."""
    lines = ['// Auto-generated parameters\n']
    for key, value in params.items():
        # Typst variables use hyphens (kebab-case), which is valid
        if isinstance(value, bool):
            lines.append(f'#let {key} = {str(value).lower()}\n')
        elif isinstance(value, (int, float)):
            lines.append(f'#let {key} = {value}\n')
        elif isinstance(value, list):
            items = ", ".join(f'"{item}"' for item in value)
            lines.append(f'#let {key} = ({items},)\n')
        else:
            escaped = str(value).replace('\\', '\\\\').replace('"', '\\"')
            lines.append(f'#let {key} = "{escaped}"\n')
    path.write_text("".join(lines))


def generate_flyer(template_name: str, params: dict, output_name: str = None,
                   fmt: str = "png"):
    """Generate a flyer from template + params."""
    template_path = TEMPLATES_DIR / f"{template_name}.typ"
    if not template_path.exists():
        available = [f.stem for f in TEMPLATES_DIR.glob("*.typ")]
        return {"error": f"Template '{template_name}' not found. Available: {available}"}

    if not output_name:
        output_name = f"{template_name}-output"

    # Create a temp working directory with template copy + params
    with tempfile.TemporaryDirectory(prefix="flyer-") as tmpdir:
        tmpdir = Path(tmpdir)

        # Copy all templates (for shared imports)
        for f in TEMPLATES_DIR.glob("*.typ"):
            shutil.copy2(f, tmpdir / f.name)

        # Write params file
        generate_params_file(params, tmpdir / "params.typ")

        # Create a wrapper: import template function, then apply with params
        # We directly set variables before importing the template so they take effect
        wrapper = tmpdir / "main.typ"

        # Read the template to extract its default variable names
        template_content = template_path.read_text()

        # Build the wrapper: set params first, then include template content
        wrapper_lines = ['// Auto-generated wrapper\n']
        wrapper_lines.append('#import "theme.typ": *\n')

        # Write param overrides
        for key, value in params.items():
            if isinstance(value, bool):
                wrapper_lines.append(f'#let {key} = {str(value).lower()}\n')
            elif isinstance(value, (int, float)):
                wrapper_lines.append(f'#let {key} = {value}\n')
            elif isinstance(value, list):
                items = ", ".join(f'"{item}"' for item in value)
                wrapper_lines.append(f'#let {key} = ({items},)\n')
            else:
                escaped = str(value).replace('\\', '\\\\').replace('"', '\\"')
                wrapper_lines.append(f'#let {key} = "{escaped}"\n')

        # Include template content, but skip its default #let lines for keys we override
        # and skip its #import "theme.typ" line (already imported above)
        for line in template_content.splitlines():
            stripped = line.strip()
            # Skip theme import (already done)
            if stripped.startswith('#import "theme.typ"'):
                continue
            # Skip #let lines for variables we're overriding
            skip = False
            if stripped.startswith('#let '):
                for key in params:
                    if stripped.startswith(f'#let {key} '):
                        skip = True
                        break
            if not skip:
                wrapper_lines.append(line + '\n')

        wrapper_lines.append('\n#show: flyer\n')
        wrapper.write_text("".join(wrapper_lines))

        # Compile to PDF
        pdf_path = tmpdir / f"{output_name}.pdf"
        result = subprocess.run(
            ["typst", "compile", str(wrapper), str(pdf_path)],
            capture_output=True, text=True,
            env={**os.environ, "TYPST_FONT_PATHS": "/usr/share/fonts"}
        )

        if result.returncode != 0:
            return {"error": f"Typst compilation failed: {result.stderr}"}

        # Copy PDF to output
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        final_pdf = OUTPUT_DIR / f"{output_name}.pdf"
        shutil.copy2(pdf_path, final_pdf)

        # Convert to PNG if requested
        final_png = None
        if fmt in ("png", "both"):
            # Use {p} template for multi-page support, then take page 1
            png_template = tmpdir / f"{output_name}-{{p}}.png"
            png_result = subprocess.run(
                ["typst", "compile", str(wrapper), str(png_template),
                 "--format", "png", "--ppi", "300"],
                capture_output=True, text=True,
                env={**os.environ, "TYPST_FONT_PATHS": "/usr/share/fonts"}
            )
            # Take the first page
            page1 = tmpdir / f"{output_name}-1.png"
            if png_result.returncode == 0 and page1.exists():
                final_png = OUTPUT_DIR / f"{output_name}.png"
                shutil.copy2(page1, final_png)
            else:
                # Fallback: try without {p} (single page)
                png_path = tmpdir / f"{output_name}.png"
                png_result2 = subprocess.run(
                    ["typst", "compile", str(wrapper), str(png_path),
                     "--format", "png", "--ppi", "300"],
                    capture_output=True, text=True,
                    env={**os.environ, "TYPST_FONT_PATHS": "/usr/share/fonts"}
                )
                if png_result2.returncode == 0:
                    final_png = OUTPUT_DIR / f"{output_name}.png"
                    shutil.copy2(png_path, final_png)
                else:
                    import sys
                    print(f"PNG warning: {png_result2.stderr}", file=sys.stderr)

        return {
            "success": True,
            "pdf": str(final_pdf),
            "png": str(final_png) if final_png else None,
            "template": template_name,
            "params": params
        }


def main():
    """CLI interface — reads JSON from stdin or args."""
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        print(json.dumps(list_templates(), indent=2))
        return

    # Read JSON input from stdin or first arg
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        try:
            data = json.loads(sys.argv[1])
        except json.JSONDecodeError:
            # Maybe it's a file path
            with open(sys.argv[1]) as f:
                data = json.load(f)
    else:
        data = json.load(sys.stdin)

    template = data.get("template", "event-promo")
    params = data.get("params", {})
    output_name = data.get("output_name")
    fmt = data.get("format", "png")

    result = generate_flyer(template, params, output_name, fmt)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
