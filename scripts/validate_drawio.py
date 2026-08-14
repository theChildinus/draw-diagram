#!/usr/bin/env python3
"""Validate deterministic Draw.io XML and text-box geometry constraints."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Issue:
    severity: str
    code: str
    page: str
    message: str
    cell: str | None = None


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def direct_child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if local_name(child.tag) == name), None)


def decode_diagram_text(text: str) -> ET.Element:
    payload = text.strip()
    if payload.startswith("<"):
        return ET.fromstring(payload)

    compressed = base64.b64decode(payload)
    encoded_xml = zlib.decompress(compressed, -15).decode("utf-8")
    xml_text = urllib.parse.unquote(encoded_xml)
    return ET.fromstring(xml_text)


def load_models(path: Path) -> list[tuple[str, ET.Element]]:
    root = ET.parse(path).getroot()
    if local_name(root.tag) == "mxGraphModel":
        return [("Page-1", root)]

    models: list[tuple[str, ET.Element]] = []
    for index, diagram in enumerate(
        element for element in root.iter() if local_name(element.tag) == "diagram"
    ):
        page = diagram.get("name") or diagram.get("id") or f"Page-{index + 1}"
        model = direct_child(diagram, "mxGraphModel")
        if model is None and diagram.text and diagram.text.strip():
            try:
                model = decode_diagram_text(diagram.text)
            except Exception as exc:
                raise ValueError(f"{page}: cannot decode diagram content: {exc}") from exc
        if model is None or local_name(model.tag) != "mxGraphModel":
            raise ValueError(f"{page}: mxGraphModel not found")
        models.append((page, model))

    if not models:
        raise ValueError("mxGraphModel or diagram page not found")
    return models


def parse_style(style: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in style.split(";"):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            result[key.strip().lower()] = value.strip()
        else:
            result[token.lower()] = "1"
    return result


def effective_cell_ids(model: ET.Element) -> tuple[list[tuple[ET.Element, str | None]], dict[str, ET.Element]]:
    wrapper_ids: dict[int, str] = {}
    for wrapper in model.iter():
        if local_name(wrapper.tag) == "mxCell" or not wrapper.get("id"):
            continue
        for child in wrapper:
            if local_name(child.tag) == "mxCell":
                wrapper_ids[id(child)] = wrapper.get("id", "")

    cells: list[tuple[ET.Element, str | None]] = []
    by_id: dict[str, ET.Element] = {}
    for cell in (element for element in model.iter() if local_name(element.tag) == "mxCell"):
        cell_id = cell.get("id") or wrapper_ids.get(id(cell))
        cells.append((cell, cell_id))
        if cell_id and cell_id not in by_id:
            by_id[cell_id] = cell
    return cells, by_id


def number(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


def geometry(cell: ET.Element) -> ET.Element | None:
    return direct_child(cell, "mxGeometry")


def validate_model(page: str, model: ET.Element) -> list[Issue]:
    issues: list[Issue] = []
    cells, by_id = effective_cell_ids(model)
    seen: set[str] = set()

    for cell, cell_id in cells:
        if not cell_id:
            issues.append(Issue("error", "MISSING_ID", page, "mxCell has no id"))
            continue
        if cell_id in seen:
            issues.append(Issue("error", "DUPLICATE_ID", page, f"duplicate id: {cell_id}", cell_id))
        seen.add(cell_id)

    for cell, cell_id in cells:
        if not cell_id:
            continue

        parent_id = cell.get("parent")
        if parent_id and parent_id not in by_id:
            issues.append(
                Issue("error", "MISSING_PARENT", page, f"parent does not exist: {parent_id}", cell_id)
            )

        if cell.get("edge") == "1":
            source = cell.get("source")
            target = cell.get("target")
            if not source or not target:
                issues.append(
                    Issue("error", "EDGE_MISSING_ENDPOINT", page, "edge needs source and target", cell_id)
                )
            else:
                if source not in by_id:
                    issues.append(
                        Issue("error", "EDGE_SOURCE_NOT_FOUND", page, f"source does not exist: {source}", cell_id)
                    )
                if target not in by_id:
                    issues.append(
                        Issue("error", "EDGE_TARGET_NOT_FOUND", page, f"target does not exist: {target}", cell_id)
                    )
            edge_geometry = geometry(cell)
            if edge_geometry is None or edge_geometry.get("relative") != "1":
                issues.append(
                    Issue("error", "EDGE_GEOMETRY", page, "edge needs relative mxGeometry", cell_id)
                )

        style = parse_style(cell.get("style", ""))
        is_text_box = cell.get("vertex") == "1" and "text" in style
        if not is_text_box:
            continue

        owner = by_id.get(parent_id or "")
        owner_style = parse_style(owner.get("style", "")) if owner is not None else {}
        is_structural_row = (
            owner_style.get("childlayout", "").lower() == "stacklayout"
            or owner_style.get("shape", "").lower() in {"table", "tablerow"}
        )
        if is_structural_row:
            continue

        if style.get("connectable") != "0" and cell.get("connectable") != "0":
            issues.append(
                Issue("error", "TEXT_CONNECTABLE", page, "independent text box needs connectable=0", cell_id)
            )

        text_geometry = geometry(cell)
        if text_geometry is None:
            issues.append(Issue("error", "TEXT_GEOMETRY", page, "text box has no geometry", cell_id))
            continue

        if owner is None or owner.get("vertex") != "1":
            issues.append(
                Issue(
                    "warning",
                    "TEXT_BOUNDARY_UNCHECKED",
                    page,
                    "top-level text has no owning shape; verify its placement in the preview",
                    cell_id,
                )
            )
            continue

        owner_geometry = geometry(owner)
        if owner_geometry is None:
            issues.append(
                Issue("warning", "OWNER_GEOMETRY", page, "owning shape has no geometry", cell_id)
            )
            continue

        if text_geometry.get("relative") == "1":
            issues.append(
                Issue(
                    "warning",
                    "TEXT_RELATIVE_GEOMETRY",
                    page,
                    "relative text geometry cannot be checked with pixel safe bounds",
                    cell_id,
                )
            )
            continue

        try:
            owner_width = number(owner_geometry.get("width"))
            owner_height = number(owner_geometry.get("height"))
            text_x = number(text_geometry.get("x"))
            text_y = number(text_geometry.get("y"))
            text_width = number(text_geometry.get("width"))
            text_height = number(text_geometry.get("height"))
        except ValueError as exc:
            issues.append(
                Issue("error", "INVALID_GEOMETRY", page, f"geometry is not numeric: {exc}", cell_id)
            )
            continue

        safe_x = max(12.0, min(24.0, owner_width * 0.08))
        safe_y = max(6.0, min(12.0, owner_height * 0.12))
        epsilon = 0.01
        horizontal_ok = (
            text_x + epsilon >= safe_x
            and text_x + text_width <= owner_width - safe_x + epsilon
        )
        vertical_ok = (
            text_y + epsilon >= safe_y
            and text_y + text_height <= owner_height - safe_y + epsilon
        )
        if not horizontal_ok or not vertical_ok:
            expected = (
                f"x=[{safe_x:.1f}, {owner_width - safe_x:.1f}], "
                f"y=[{safe_y:.1f}, {owner_height - safe_y:.1f}]"
            )
            actual = (
                f"x=[{text_x:.1f}, {text_x + text_width:.1f}], "
                f"y=[{text_y:.1f}, {text_y + text_height:.1f}]"
            )
            issues.append(
                Issue(
                    "error",
                    "TEXT_SAFE_BOUNDARY",
                    page,
                    f"text box exceeds safe bounds; expected {expected}; actual {actual}",
                    cell_id,
                )
            )

    return issues


def format_issue(issue: Issue) -> str:
    location = f" [{issue.page}]"
    if issue.cell:
        location += f" cell={issue.cell}"
    return f"{issue.severity.upper()} {issue.code}{location}: {issue.message}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Draw.io XML structure and independent text-box boundaries."
    )
    parser.add_argument("drawio_file", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Return a failing exit status when warnings are present.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        models = load_models(args.drawio_file)
    except (OSError, ET.ParseError, ValueError, binascii.Error, zlib.error) as exc:
        if args.as_json:
            print(json.dumps({"file": str(args.drawio_file), "fatal": str(exc)}, ensure_ascii=False))
        else:
            print(f"FATAL: {exc}", file=sys.stderr)
        return 2

    issues: list[Issue] = []
    for page, model in models:
        issues.extend(validate_model(page, model))

    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    if args.as_json:
        print(
            json.dumps(
                {
                    "file": str(args.drawio_file),
                    "pages": len(models),
                    "errors": errors,
                    "warnings": warnings,
                    "issues": [asdict(issue) for issue in issues],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for issue in issues:
            print(format_issue(issue))
        if not issues:
            print(f"OK: {args.drawio_file} ({len(models)} page(s))")
        else:
            print(f"SUMMARY: {errors} error(s), {warnings} warning(s), {len(models)} page(s)")

    if errors or (warnings and args.strict_warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
