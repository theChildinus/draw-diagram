#!/usr/bin/env python3
"""Validate Draw.io structure, text boundaries and rendered connection geometry."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator


SUPPORTED_FIXES_BY_CODE: dict[str, tuple[str, ...]] = {
    "MISSING_ID": ("assign_unique_cell_id",),
    "DUPLICATE_ID": ("rename_duplicate_cell_id",),
    "MISSING_PARENT": ("set_existing_parent",),
    "EDGE_MISSING_ENDPOINT": ("set_source_and_target",),
    "EDGE_SOURCE_NOT_FOUND": ("set_existing_source",),
    "EDGE_TARGET_NOT_FOUND": ("set_existing_target",),
    "EDGE_GEOMETRY": ("add_relative_edge_geometry",),
    "OUTER_CONTAINER_CORNER_RADIUS": (
        "set_arc_size_at_most_4",
        "disable_container_rounding",
    ),
    "TEXT_CONNECTABLE": ("set_connectable_0",),
    "TEXT_GEOMETRY": ("add_text_geometry",),
    "TEXT_SIBLING_OVERLAY": (
        "move_text_under_shape",
        "use_shape_value",
    ),
    "TEXT_BOUNDARY_UNCHECKED": ("inspect_preview",),
    "OWNER_GEOMETRY": ("add_owner_geometry",),
    "TEXT_RELATIVE_GEOMETRY": (
        "use_absolute_text_geometry",
        "inspect_preview",
    ),
    "INVALID_GEOMETRY": ("replace_with_numeric_geometry",),
    "TEXT_SAFE_BOUNDARY": (
        "move_or_resize_text_within_safe_bounds",
        "expand_owner_or_use_shape_value",
    ),
    "EDGE_RENDER_PARSE": ("inspect_exported_edge",),
    "EDGE_RENDER_MISSING": ("reexport_visible_edge", "inspect_edge_visibility"),
    "EDGE_SHARED_PORT": ("allocate_distinct_ports", "model_explicit_junction"),
    "EDGE_PORT_SPACING": ("spread_ports_or_resize_node",),
    "EDGE_OVERLAP": ("separate_edge_routes", "draw_shared_trunk_once"),
    "EDGE_PARALLEL_CLEARANCE": ("increase_routing_channel_spacing",),
    "EDGE_JUMP_STYLE_REVIEW": (
        "remove_jump_style",
        "record_manual_crossing_review",
    ),
    "EDGE_SHORT_DIRECT": ("increase_endpoint_clearance",),
    "EDGE_SHORT_START": ("realign_source_or_adjust_route",),
    "EDGE_SHORT_MIDDLE": ("remove_short_dogleg_or_adjust_route",),
    "EDGE_SHORT_END": ("realign_target_or_adjust_route",),
    "EDGE_CROSSING": (
        "move_endpoint_or_adjust_route",
        "reposition_node",
    ),
    "EDGE_THROUGH_SHAPE": (
        "move_endpoint_or_adjust_route",
        "reposition_obstacle",
    ),
}


@dataclass
class Issue:
    severity: str
    code: str
    page: str
    message: str
    cell: str | None = None
    subject: str | None = None
    evidence: dict[str, object] = field(default_factory=dict)
    supported_fixes: tuple[str, ...] = ()
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.subject is None:
            self.subject = f"cell:{self.cell}" if self.cell else f"page:{self.page}"
        if not self.supported_fixes:
            self.supported_fixes = SUPPORTED_FIXES_BY_CODE.get(self.code, ())
        if not self.fingerprint:
            observation = json.dumps(
                {
                    "code": self.code,
                    "severity": self.severity,
                    "page": self.page,
                    "subject": self.subject,
                    "evidence": self.evidence,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            self.fingerprint = f"diag-{hashlib.sha256(observation.encode('utf-8')).hexdigest()[:16]}"


Point = tuple[float, float]
Segment = tuple[Point, Point]
Matrix = tuple[float, float, float, float, float, float]
IDENTITY_MATRIX: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass
class RenderedEdge:
    cell_id: str
    source: str | None
    target: str | None
    style: dict[str, str]
    segments: list[Segment]
    straight_segments: list[Segment]

    @property
    def start(self) -> Point | None:
        return self.segments[0][0] if self.segments else None

    @property
    def end(self) -> Point | None:
        return self.segments[-1][1] if self.segments else None


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


def multiply_matrix(left: Matrix, right: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = left
    a2, b2, c2, d2, e2, f2 = right
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def transform_point(matrix: Matrix, point: Point) -> Point:
    a, b, c, d, e, f = matrix
    x, y = point
    return (a * x + c * y + e, b * x + d * y + f)


def parse_transform(value: str | None) -> Matrix:
    result = IDENTITY_MATRIX
    if not value:
        return result

    for name, payload in re.findall(r"([A-Za-z]+)\s*\(([^)]*)\)", value):
        values = [float(item) for item in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", payload)]
        operation = IDENTITY_MATRIX
        if name == "matrix" and len(values) == 6:
            operation = tuple(values)  # type: ignore[assignment]
        elif name == "translate" and values:
            operation = (1.0, 0.0, 0.0, 1.0, values[0], values[1] if len(values) > 1 else 0.0)
        elif name == "scale" and values:
            operation = (values[0], 0.0, 0.0, values[1] if len(values) > 1 else values[0], 0.0, 0.0)
        elif name == "rotate" and values:
            radians = math.radians(values[0])
            cosine, sine = math.cos(radians), math.sin(radians)
            rotation: Matrix = (cosine, sine, -sine, cosine, 0.0, 0.0)
            if len(values) >= 3:
                cx, cy = values[1], values[2]
                operation = multiply_matrix(
                    multiply_matrix((1.0, 0.0, 0.0, 1.0, cx, cy), rotation),
                    (1.0, 0.0, 0.0, 1.0, -cx, -cy),
                )
            else:
                operation = rotation
        result = multiply_matrix(result, operation)
    return result


PATH_TOKEN = re.compile(
    r"[A-Za-z]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)


def parse_svg_path(path_data: str, matrix: Matrix = IDENTITY_MATRIX) -> tuple[list[Segment], list[Segment]]:
    tokens = PATH_TOKEN.findall(path_data)
    index = 0
    command = ""
    current: Point = (0.0, 0.0)
    start: Point = current
    last_quadratic_control: Point | None = None
    last_cubic_control: Point | None = None
    segments: list[Segment] = []
    straight_segments: list[Segment] = []

    def point_at(x: float, y: float, relative: bool) -> Point:
        return (current[0] + x, current[1] + y) if relative else (x, y)

    def add_line(destination: Point, straight: bool = True) -> None:
        nonlocal current
        rendered = (transform_point(matrix, current), transform_point(matrix, destination))
        segments.append(rendered)
        if straight:
            straight_segments.append(rendered)
        current = destination

    def add_quadratic(control: Point, destination: Point) -> None:
        nonlocal current
        origin = current
        previous = origin
        for step in range(1, 9):
            ratio = step / 8.0
            inverse = 1.0 - ratio
            point = (
                inverse * inverse * origin[0] + 2 * inverse * ratio * control[0] + ratio * ratio * destination[0],
                inverse * inverse * origin[1] + 2 * inverse * ratio * control[1] + ratio * ratio * destination[1],
            )
            segments.append((transform_point(matrix, previous), transform_point(matrix, point)))
            previous = point
        current = destination

    def add_cubic(control1: Point, control2: Point, destination: Point) -> None:
        nonlocal current
        origin = current
        previous = origin
        for step in range(1, 13):
            ratio = step / 12.0
            inverse = 1.0 - ratio
            point = (
                inverse**3 * origin[0]
                + 3 * inverse * inverse * ratio * control1[0]
                + 3 * inverse * ratio * ratio * control2[0]
                + ratio**3 * destination[0],
                inverse**3 * origin[1]
                + 3 * inverse * inverse * ratio * control1[1]
                + 3 * inverse * ratio * ratio * control2[1]
                + ratio**3 * destination[1],
            )
            segments.append((transform_point(matrix, previous), transform_point(matrix, point)))
            previous = point
        current = destination

    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
        if not command:
            raise ValueError("SVG path starts without a command")

        relative = command.islower()
        upper = command.upper()
        if upper == "Z":
            add_line(start, straight=False)
            command = ""
            continue
        if upper == "M":
            destination = point_at(float(tokens[index]), float(tokens[index + 1]), relative)
            index += 2
            current = destination
            start = destination
            command = "l" if relative else "L"
        elif upper == "L":
            destination = point_at(float(tokens[index]), float(tokens[index + 1]), relative)
            index += 2
            add_line(destination)
        elif upper == "H":
            x = current[0] + float(tokens[index]) if relative else float(tokens[index])
            index += 1
            add_line((x, current[1]))
        elif upper == "V":
            y = current[1] + float(tokens[index]) if relative else float(tokens[index])
            index += 1
            add_line((current[0], y))
        elif upper == "Q":
            control = point_at(float(tokens[index]), float(tokens[index + 1]), relative)
            destination = point_at(float(tokens[index + 2]), float(tokens[index + 3]), relative)
            index += 4
            add_quadratic(control, destination)
            last_quadratic_control = control
        elif upper == "T":
            control = current if last_quadratic_control is None else (
                2 * current[0] - last_quadratic_control[0],
                2 * current[1] - last_quadratic_control[1],
            )
            destination = point_at(float(tokens[index]), float(tokens[index + 1]), relative)
            index += 2
            add_quadratic(control, destination)
            last_quadratic_control = control
        elif upper == "C":
            control1 = point_at(float(tokens[index]), float(tokens[index + 1]), relative)
            control2 = point_at(float(tokens[index + 2]), float(tokens[index + 3]), relative)
            destination = point_at(float(tokens[index + 4]), float(tokens[index + 5]), relative)
            index += 6
            add_cubic(control1, control2, destination)
            last_cubic_control = control2
        elif upper == "S":
            control1 = current if last_cubic_control is None else (
                2 * current[0] - last_cubic_control[0],
                2 * current[1] - last_cubic_control[1],
            )
            control2 = point_at(float(tokens[index]), float(tokens[index + 1]), relative)
            destination = point_at(float(tokens[index + 2]), float(tokens[index + 3]), relative)
            index += 4
            add_cubic(control1, control2, destination)
            last_cubic_control = control2
        elif upper == "A":
            destination = point_at(float(tokens[index + 5]), float(tokens[index + 6]), relative)
            index += 7
            add_line(destination, straight=False)
        else:
            raise ValueError(f"unsupported SVG path command: {command}")

        if upper not in {"Q", "T"}:
            last_quadratic_control = None
        if upper not in {"C", "S"}:
            last_cubic_control = None

    return segments, straight_segments


def rendered_cell_groups(svg_root: ET.Element) -> dict[str, tuple[ET.Element, Matrix]]:
    groups: dict[str, tuple[ET.Element, Matrix]] = {}

    def visit(element: ET.Element, parent_matrix: Matrix) -> None:
        matrix = multiply_matrix(parent_matrix, parse_transform(element.get("transform")))
        cell_id = element.get("data-cell-id")
        if local_name(element.tag) == "g" and cell_id:
            groups[cell_id] = (element, matrix)
        for child in element:
            visit(child, matrix)

    visit(svg_root, IDENTITY_MATRIX)
    return groups


def group_graphics(group: ET.Element, group_matrix: Matrix) -> Iterator[tuple[ET.Element, Matrix]]:
    def visit(element: ET.Element, parent_matrix: Matrix) -> Iterator[tuple[ET.Element, Matrix]]:
        matrix = multiply_matrix(parent_matrix, parse_transform(element.get("transform")))
        if element is not group and element.get("data-cell-id"):
            return
        if local_name(element.tag) in {"rect", "ellipse", "circle", "line", "polygon", "polyline", "path"}:
            yield element, matrix
        for child in element:
            yield from visit(child, matrix)

    for child in group:
        yield from visit(child, group_matrix)


def main_rendered_path(group: ET.Element, matrix: Matrix) -> tuple[list[Segment], list[Segment]] | None:
    for element, element_matrix in group_graphics(group, matrix):
        if (
            local_name(element.tag) == "path"
            and element.get("fill") == "none"
            and element.get("pointer-events") == "stroke"
            and element.get("d")
        ):
            return parse_svg_path(element.get("d", ""), element_matrix)
    return None


def primitive_points(element: ET.Element, matrix: Matrix) -> list[Point]:
    tag = local_name(element.tag)
    if tag == "path" and element.get("d"):
        segments, _ = parse_svg_path(element.get("d", ""), matrix)
        return [point for segment in segments for point in segment]
    if tag == "rect":
        x, y = number(element.get("x")), number(element.get("y"))
        width, height = number(element.get("width")), number(element.get("height"))
        return [transform_point(matrix, point) for point in ((x, y), (x + width, y), (x + width, y + height), (x, y + height))]
    if tag in {"ellipse", "circle"}:
        cx, cy = number(element.get("cx")), number(element.get("cy"))
        rx = number(element.get("rx"), number(element.get("r")))
        ry = number(element.get("ry"), number(element.get("r")))
        return [
            transform_point(matrix, (cx + rx * math.cos(index * math.pi / 16), cy + ry * math.sin(index * math.pi / 16)))
            for index in range(32)
        ]
    if tag == "line":
        return [
            transform_point(matrix, (number(element.get("x1")), number(element.get("y1")))),
            transform_point(matrix, (number(element.get("x2")), number(element.get("y2")))),
        ]
    if tag in {"polygon", "polyline"}:
        values = [float(value) for value in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", element.get("points", ""))]
        return [transform_point(matrix, (values[index], values[index + 1])) for index in range(0, len(values) - 1, 2)]
    return []


def rendered_shape_bounds(group: ET.Element, matrix: Matrix) -> tuple[float, float, float, float] | None:
    points: list[Point] = []
    for element, element_matrix in group_graphics(group, matrix):
        if element.get("pointer-events") == "all":
            points.extend(primitive_points(element, element_matrix))
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def segment_length(segment: Segment) -> float:
    return math.dist(segment[0], segment[1])


def proper_intersection(first: Segment, second: Segment, epsilon: float = 1e-6) -> Point | None:
    (px, py), (p2x, p2y) = first
    (qx, qy), (q2x, q2y) = second
    rx, ry = p2x - px, p2y - py
    sx, sy = q2x - qx, q2y - qy
    denominator = rx * sy - ry * sx
    if abs(denominator) <= epsilon:
        return None
    qpx, qpy = qx - px, qy - py
    first_ratio = (qpx * sy - qpy * sx) / denominator
    second_ratio = (qpx * ry - qpy * rx) / denominator
    if -epsilon <= first_ratio <= 1 + epsilon and -epsilon <= second_ratio <= 1 + epsilon:
        return px + first_ratio * rx, py + first_ratio * ry
    return None


def near(point: Point, candidate: Point | None, tolerance: float = 3.0) -> bool:
    return candidate is not None and math.dist(point, candidate) <= tolerance


def parallel_run(first: Segment, second: Segment) -> tuple[float, float] | None:
    """Return perpendicular clearance and positive shared projected length."""
    (px, py), (qx, qy) = first
    (ax, ay), (bx, by) = second
    length, other_length = segment_length(first), segment_length(second)
    if min(length, other_length) <= 0.01:
        return None
    ux, uy = (qx - px) / length, (qy - py) / length
    vx, vy = (bx - ax) / other_length, (by - ay) / other_length
    if abs(ux * vy - uy * vx) > 1e-6:
        return None
    start = (ax - px) * ux + (ay - py) * uy
    end = (bx - px) * ux + (by - py) * uy
    overlap = min(length, max(start, end)) - max(0.0, min(start, end))
    if overlap <= 0.01:
        return None
    distance = abs((ax - px) * uy - (ay - py) * ux)
    return distance, overlap


def hidden_cell(cell: ET.Element, by_id: dict[str, ET.Element]) -> bool:
    """Explicitly hidden layers and children of collapsed containers are not exported."""
    seen: set[str] = set()
    current: ET.Element | None = cell
    while current is not None:
        if current.get("visible") == "0" or (current is not cell and current.get("collapsed") == "1"):
            return True
        parent = current.get("parent")
        if not parent or parent in seen:
            break
        seen.add(parent)
        current = by_id.get(parent)
    return False


def explicit_junction(cell: ET.Element) -> bool:
    style = parse_style(cell.get("style", ""))
    box = geometry(cell)
    if style.get("diagramjunction") != "1" or box is None:
        return False
    return (
        cell.get("vertex") == "1"
        and ("ellipse" in style or style.get("shape") == "ellipse")
        and 0 < number(box.get("width")) <= 16
        and 0 < number(box.get("height")) <= 16
        and style.get("fillcolor", "#000000").lower() not in {"none", "transparent"}
        and number(style.get("opacity"), 100) > 0
        and number(style.get("fillopacity"), 100) > 0
    )


def boundary_endpoint(point: Point, neighbor: Point, bounds: tuple[float, float, float, float] | None) -> Point:
    """Project a shortened orthogonal arrow stroke to its node's boundary.

    Inside-box and diagonal endpoints stay as rendered; no arbitrary endpoint
    is snapped to a distant corner or to another side of the node.
    """
    if bounds is None:
        return point
    left, top, right, bottom = bounds
    x, y = point
    if left <= x <= right and top <= y <= bottom:
        return point
    if abs(y - neighbor[1]) < 0.01 and top <= y <= bottom:
        if x < left and x > neighbor[0]:
            return left, y
        if x > right and x < neighbor[0]:
            return right, y
    if abs(x - neighbor[0]) < 0.01 and left <= x <= right:
        if y < top and y > neighbor[1]:
            return x, top
        if y > bottom and y < neighbor[1]:
            return x, bottom
    return point


def connection_issues(page: str, edges: list[RenderedEdge], by_id: dict[str, ET.Element],
                      groups: dict[str, tuple[ET.Element, Matrix]]) -> list[Issue]:
    issues: list[Issue] = []
    ports: dict[str, list[tuple[str, str, Point]]] = {}
    for edge in edges:
        for node, role, point, neighbor in [
            (edge.source, "source", edge.start, edge.segments[0][1]),
            (edge.target, "target", edge.end, edge.segments[-1][0]),
        ]:
            if node is None or point is None:
                continue
            bounds = None
            if node in groups:
                try:
                    bounds = rendered_shape_bounds(*groups[node])
                except (IndexError, ValueError):
                    pass
            ports.setdefault(node, []).append((edge.cell_id, role, boundary_endpoint(point, neighbor, bounds)))

    for node, connections in sorted(ports.items()):
        if node in by_id and node in groups and explicit_junction(by_id[node]):
            try:
                if rendered_shape_bounds(*groups[node]) is not None:
                    continue
            except (IndexError, ValueError):
                pass
        connections.sort()
        for index, (first, first_role, first_point) in enumerate(connections):
            for second, second_role, second_point in connections[index + 1:]:
                distance = math.dist(first_point, second_point)
                if distance >= 12.0 - 0.01:
                    continue
                shared = distance <= 0.01
                issues.append(Issue(
                    "error" if shared else "warning",
                    "EDGE_SHARED_PORT" if shared else "EDGE_PORT_SPACING", page,
                    f"{first} ({first_role}) and {second} ({second_role}) use ports {distance:.2f}px apart on {node}",
                    first, subject=f"port:{node}:{first}:{first_role}:{second}:{second_role}",
                    evidence={"node": node, "other_edge": second, "roles": [first_role, second_role],
                              "actual_px": round(distance, 3), "minimum_px": 12.0,
                              "points": [first_point, second_point]},
                ))

    for index, first in enumerate(edges):
        for second in edges[index + 1:]:
            overlap = 0.0
            for a in first.segments:
                for b in second.segments:
                    run = parallel_run(a, b)
                    if run is not None and run[0] <= 0.01:
                        overlap = max(overlap, run[1])
            pair = sorted([first.cell_id, second.cell_id])
            subject = f"edges:{pair[0]}:{pair[1]}"
            if overlap > 1.0:
                issues.append(Issue("error", "EDGE_OVERLAP", page,
                    f"{first.cell_id} and {second.cell_id} share a line segment of {overlap:.1f}px",
                    pair[0], subject=subject,
                    evidence={"edges": pair, "overlap_px": round(overlap, 3)}))
                continue
            close_runs = []
            for a in first.straight_segments:
                for b in second.straight_segments:
                    run = parallel_run(a, b)
                    if run is not None and 0.01 < run[0] < 12.0 - 0.01 and run[1] >= 16.0:
                        close_runs.append(run)
            if close_runs:
                distance, length = min(close_runs)
                issues.append(Issue("warning", "EDGE_PARALLEL_CLEARANCE", page,
                    f"{first.cell_id} and {second.cell_id} run {distance:.1f}px apart for {length:.1f}px",
                    pair[0], subject=subject,
                    evidence={"edges": pair, "actual_px": round(distance, 3),
                              "minimum_px": 12.0, "parallel_run_px": round(length, 3)}))
    return issues


def point_inside_shape(point: Point, bounds: tuple[float, float, float, float], style: dict[str, str]) -> bool:
    left, top, right, bottom = bounds
    margin = 1.5
    if not (left + margin < point[0] < right - margin and top + margin < point[1] < bottom - margin):
        return False
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    radius_x, radius_y = max((right - left) / 2, 1.0), max((bottom - top) / 2, 1.0)
    shape = style.get("shape", "").lower()
    if "rhombus" in style or shape == "rhombus":
        return abs(point[0] - center_x) / radius_x + abs(point[1] - center_y) / radius_y < 0.97
    if "ellipse" in style or shape == "ellipse":
        return ((point[0] - center_x) / radius_x) ** 2 + ((point[1] - center_y) / radius_y) ** 2 < 0.94
    return True


def segment_enters_shape(segment: Segment, bounds: tuple[float, float, float, float], style: dict[str, str]) -> bool:
    length = segment_length(segment)
    samples = max(1, math.ceil(length / 2.0))
    for index in range(samples + 1):
        ratio = index / samples
        point = (
            segment[0][0] + (segment[1][0] - segment[0][0]) * ratio,
            segment[0][1] + (segment[1][1] - segment[0][1]) * ratio,
        )
        if point_inside_shape(point, bounds, style):
            return True
    return False


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


def has_visible_value(cell: ET.Element) -> bool:
    value = html.unescape(cell.get("value", "")).replace("\xa0", " ")
    return bool(re.sub(r"<[^>]*>", "", value).strip())


def blank_sibling_under_text(
    text_cell: ET.Element,
    parent_id: str,
    cells: list[tuple[ET.Element, str | None]],
) -> str | None:
    text_geometry = geometry(text_cell)
    if text_geometry is None or text_geometry.get("relative") == "1":
        return None

    try:
        text_x = number(text_geometry.get("x"))
        text_y = number(text_geometry.get("y"))
        text_width = number(text_geometry.get("width"))
        text_height = number(text_geometry.get("height"))
    except ValueError:
        return None

    text_area = text_width * text_height
    if text_area <= 0:
        return None

    for candidate, candidate_id in cells:
        if (
            not candidate_id
            or candidate is text_cell
            or candidate.get("vertex") != "1"
            or candidate.get("parent") != parent_id
            or has_visible_value(candidate)
        ):
            continue

        candidate_style = parse_style(candidate.get("style", ""))
        if (
            "text" in candidate_style
            or "group" in candidate_style
            or "swimlane" in candidate_style
            or candidate_style.get("container") == "1"
            or candidate_style.get("pointerevents") == "0"
            or candidate_style.get("connectable") == "0"
        ):
            continue

        candidate_geometry = geometry(candidate)
        if candidate_geometry is None or candidate_geometry.get("relative") == "1":
            continue

        try:
            candidate_x = number(candidate_geometry.get("x"))
            candidate_y = number(candidate_geometry.get("y"))
            candidate_width = number(candidate_geometry.get("width"))
            candidate_height = number(candidate_geometry.get("height"))
        except ValueError:
            continue

        intersection_width = max(
            0.0,
            min(text_x + text_width, candidate_x + candidate_width)
            - max(text_x, candidate_x),
        )
        intersection_height = max(
            0.0,
            min(text_y + text_height, candidate_y + candidate_height)
            - max(text_y, candidate_y),
        )
        if intersection_width * intersection_height >= text_area * 0.8:
            return candidate_id

    return None


def validate_model(page: str, model: ET.Element) -> list[Issue]:
    issues: list[Issue] = []
    cells, by_id = effective_cell_ids(model)
    seen: set[str] = set()

    for cell_index, (cell, cell_id) in enumerate(cells):
        if not cell_id:
            issues.append(
                Issue(
                    "error",
                    "MISSING_ID",
                    page,
                    "mxCell has no id",
                    subject=f"cell-index:{cell_index}",
                    evidence={"cell_index": cell_index, "element": "mxCell"},
                )
            )
            continue
        if cell_id in seen:
            issues.append(
                Issue(
                    "error",
                    "DUPLICATE_ID",
                    page,
                    f"duplicate id: {cell_id}",
                    cell_id,
                    evidence={"duplicate_id": cell_id},
                )
            )
        seen.add(cell_id)

    for cell, cell_id in cells:
        if not cell_id:
            continue

        parent_id = cell.get("parent")
        if parent_id and parent_id not in by_id:
            issues.append(
                Issue(
                    "error",
                    "MISSING_PARENT",
                    page,
                    f"parent does not exist: {parent_id}",
                    cell_id,
                    evidence={"missing_parent": parent_id},
                )
            )

        if cell.get("edge") == "1":
            source = cell.get("source")
            target = cell.get("target")
            if not source or not target:
                issues.append(
                    Issue(
                        "error",
                        "EDGE_MISSING_ENDPOINT",
                        page,
                        "edge needs source and target",
                        cell_id,
                        evidence={"source": source, "target": target},
                    )
                )
            else:
                if source not in by_id:
                    issues.append(
                        Issue(
                            "error",
                            "EDGE_SOURCE_NOT_FOUND",
                            page,
                            f"source does not exist: {source}",
                            cell_id,
                            evidence={"missing_source": source},
                        )
                    )
                if target not in by_id:
                    issues.append(
                        Issue(
                            "error",
                            "EDGE_TARGET_NOT_FOUND",
                            page,
                            f"target does not exist: {target}",
                            cell_id,
                            evidence={"missing_target": target},
                        )
                    )
            edge_geometry = geometry(cell)
            if edge_geometry is None or edge_geometry.get("relative") != "1":
                issues.append(
                    Issue(
                        "error",
                        "EDGE_GEOMETRY",
                        page,
                        "edge needs relative mxGeometry",
                        cell_id,
                        evidence={
                            "geometry_present": edge_geometry is not None,
                            "relative": edge_geometry.get("relative")
                            if edge_geometry is not None
                            else None,
                        },
                    )
                )

        style = parse_style(cell.get("style", ""))
        is_large_background_container = False
        if (
            cell.get("vertex") == "1"
            and not has_visible_value(cell)
            and style.get("rounded") == "1"
            and (style.get("pointerevents") == "0" or style.get("container") == "1")
        ):
            cell_geometry = geometry(cell)
            if cell_geometry is not None and cell_geometry.get("relative") != "1":
                try:
                    width = number(cell_geometry.get("width"))
                    height = number(cell_geometry.get("height"))
                    is_large_background_container = width >= 300.0 and height >= 300.0
                except ValueError:
                    pass

        if is_large_background_container:
            try:
                arc_size = number(style.get("arcsize"), 10.0)
            except ValueError:
                arc_size = 10.0
            if arc_size > 4.0:
                issues.append(
                    Issue(
                        "error",
                        "OUTER_CONTAINER_CORNER_RADIUS",
                        page,
                        (
                            f"large background container arcSize is {arc_size:g}; "
                            "use rounded=0 or set an explicit arcSize no greater than 4"
                        ),
                        cell_id,
                        evidence={
                            "arc_size": arc_size,
                            "maximum_arc_size": 4.0,
                            "width": width,
                            "height": height,
                        },
                    )
                )

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
                Issue(
                    "error",
                    "TEXT_CONNECTABLE",
                    page,
                    "independent text box needs connectable=0",
                    cell_id,
                    evidence={
                        "style_connectable": style.get("connectable"),
                        "attribute_connectable": cell.get("connectable"),
                    },
                )
            )

        text_geometry = geometry(cell)
        if text_geometry is None:
            issues.append(
                Issue(
                    "error",
                    "TEXT_GEOMETRY",
                    page,
                    "text box has no geometry",
                    cell_id,
                    evidence={"parent": parent_id, "geometry_present": False},
                )
            )
            continue

        if owner is not None and owner.get("vertex") == "1" and parent_id:
            sibling_id = blank_sibling_under_text(cell, parent_id, cells)
            if sibling_id:
                issues.append(
                    Issue(
                        "error",
                        "TEXT_SIBLING_OVERLAY",
                        page,
                        (
                            f"text overlaps blank sibling shape {sibling_id}; use the shape value "
                            "or make the text a child of that shape"
                        ),
                        cell_id,
                        evidence={"overlapped_sibling": sibling_id},
                    )
                )
                continue

        if owner is None or owner.get("vertex") != "1":
            issues.append(
                Issue(
                    "warning",
                    "TEXT_BOUNDARY_UNCHECKED",
                    page,
                    "top-level text has no owning shape; verify its placement in the preview",
                    cell_id,
                    evidence={
                        "parent": parent_id,
                        "owner_present": owner is not None,
                        "owner_is_vertex": owner.get("vertex") == "1"
                        if owner is not None
                        else False,
                    },
                )
            )
            continue

        owner_geometry = geometry(owner)
        if owner_geometry is None:
            issues.append(
                Issue(
                    "warning",
                    "OWNER_GEOMETRY",
                    page,
                    "owning shape has no geometry",
                    cell_id,
                    evidence={"owner": parent_id, "geometry_present": False},
                )
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
                    evidence={"owner": parent_id, "relative": text_geometry.get("relative")},
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
                Issue(
                    "error",
                    "INVALID_GEOMETRY",
                    page,
                    f"geometry is not numeric: {exc}",
                    cell_id,
                    evidence={
                        "owner": parent_id,
                        "owner_geometry": dict(owner_geometry.attrib),
                        "text_geometry": dict(text_geometry.attrib),
                    },
                )
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
                    evidence={
                        "owner": parent_id,
                        "safe_bounds": {
                            "left": safe_x,
                            "right": owner_width - safe_x,
                            "top": safe_y,
                            "bottom": owner_height - safe_y,
                        },
                        "actual_bounds": {
                            "left": text_x,
                            "right": text_x + text_width,
                            "top": text_y,
                            "bottom": text_y + text_height,
                        },
                    },
                )
            )

    return issues


def validate_rendered_svg(page: str, model: ET.Element, svg_root: ET.Element) -> list[Issue]:
    issues: list[Issue] = []
    cells, _ = effective_cell_ids(model)
    by_id = {cell_id: cell for cell, cell_id in cells if cell_id}
    groups = rendered_cell_groups(svg_root)
    edges: list[RenderedEdge] = []

    for cell, cell_id in cells:
        if not cell_id or cell.get("edge") != "1" or hidden_cell(cell, by_id):
            continue
        if cell_id not in groups:
            # Draw.io also hides edges whose terminal or terminal's layer is hidden.
            if any(endpoint in by_id and hidden_cell(by_id[endpoint], by_id)
                   for endpoint in (cell.get("source"), cell.get("target"))):
                continue
            issues.append(Issue("error", "EDGE_RENDER_MISSING", page,
                "visible edge has no rendered SVG group", cell_id,
                evidence={"reason": "missing_group"}))
            continue
        group, matrix = groups[cell_id]
        try:
            rendered_path = main_rendered_path(group, matrix)
        except (IndexError, ValueError) as exc:
            issues.append(
                Issue(
                    "error",
                    "EDGE_RENDER_PARSE",
                    page,
                    f"cannot parse rendered edge path: {exc}",
                    cell_id,
                    evidence={"exception": type(exc).__name__, "reason": str(exc)},
                )
            )
            continue
        if rendered_path is None or not rendered_path[0] or not any(segment_length(s) > 0.01 for s in rendered_path[0]):
            issues.append(Issue("error", "EDGE_RENDER_MISSING", page,
                "visible edge has no usable rendered path", cell_id,
                evidence={"reason": "missing_or_empty_path"}))
            continue
        segments, straight_segments = rendered_path
        style = parse_style(cell.get("style", ""))
        edge = RenderedEdge(
            cell_id=cell_id,
            source=cell.get("source"),
            target=cell.get("target"),
            style=style,
            segments=segments,
            straight_segments=straight_segments,
        )
        edges.append(edge)

        jump_style = style.get("jumpstyle", "").lower()
        if jump_style and jump_style not in {"none", "0"}:
            issues.append(
                Issue(
                    "warning",
                    "EDGE_JUMP_STYLE_REVIEW",
                    page,
                    f"jumpStyle={jump_style} needs proof that the crossing cannot be routed away",
                    cell_id,
                    evidence={"jump_style": jump_style},
                )
            )

        if style.get("edgestyle", "").lower() != "orthogonaledgestyle" or not straight_segments:
            continue
        lengths = [segment_length(segment) for segment in straight_segments]
        if len(lengths) == 1:
            if lengths[0] < 24.0 - 0.01:
                issues.append(
                    Issue(
                        "warning",
                        "EDGE_SHORT_DIRECT",
                        page,
                        f"single straight segment is {lengths[0]:.1f}px; expected at least 24px",
                        cell_id,
                        evidence={"actual_px": lengths[0], "minimum_px": 24.0},
                    )
                )
            continue
        if lengths[0] < 16.0 - 0.01:
            issues.append(
                Issue(
                    "warning",
                    "EDGE_SHORT_START",
                    page,
                    f"first straight segment is {lengths[0]:.1f}px; expected at least 16px",
                    cell_id,
                    evidence={"actual_px": lengths[0], "minimum_px": 16.0},
                )
            )
        short_middle = [length for length in lengths[1:-1] if length < 16.0 - 0.01]
        if short_middle:
            issues.append(
                Issue(
                    "warning",
                    "EDGE_SHORT_MIDDLE",
                    page,
                    f"middle straight segment is as short as {min(short_middle):.1f}px; expected at least 16px",
                    cell_id,
                    evidence={"actual_px": min(short_middle), "minimum_px": 16.0},
                )
            )
        if lengths[-1] < 24.0 - 0.01:
            issues.append(
                Issue(
                    "warning",
                    "EDGE_SHORT_END",
                    page,
                    f"last straight segment is {lengths[-1]:.1f}px; expected at least 24px",
                    cell_id,
                    evidence={"actual_px": lengths[-1], "minimum_px": 24.0},
                )
            )

    edges.sort(key=lambda edge: edge.cell_id)
    issues.extend(connection_issues(page, edges, by_id, groups))

    for index, first in enumerate(edges):
        for second in edges[index + 1 :]:
            crossing: Point | None = None
            for first_segment in first.segments:
                for second_segment in second.segments:
                    candidate = proper_intersection(first_segment, second_segment)
                    if candidate is None:
                        continue
                    shared_endpoint = bool(
                        {first.source, first.target}.difference({None})
                        & {second.source, second.target}.difference({None})
                    )
                    if shared_endpoint and (
                        (near(candidate, first.start) or near(candidate, first.end))
                        and (near(candidate, second.start) or near(candidate, second.end))
                    ):
                        continue
                    crossing = candidate
                    break
                if crossing is not None:
                    break
            if crossing is not None:
                issues.append(
                    Issue(
                        "error",
                        "EDGE_CROSSING",
                        page,
                        f"crosses {second.cell_id} near ({crossing[0]:.1f}, {crossing[1]:.1f})",
                        first.cell_id,
                        evidence={
                            "other_edge": second.cell_id,
                            "intersection": {"x": crossing[0], "y": crossing[1]},
                        },
                    )
                )

    child_cells: dict[str, list[ET.Element]] = {}
    for cell, _ in cells:
        if cell.get("parent"):
            child_cells.setdefault(cell.get("parent", ""), []).append(cell)

    rendered_shapes: dict[str, tuple[tuple[float, float, float, float], dict[str, str]]] = {}
    for cell, cell_id in cells:
        if not cell_id or cell.get("vertex") != "1" or cell_id not in groups:
            continue
        style = parse_style(cell.get("style", ""))
        if (
            "text" in style
            or "group" in style
            or "swimlane" in style
            or style.get("container") == "1"
            or style.get("pointerevents") == "0"
            or style.get("connectable") == "0"
        ):
            continue
        structural_children = any(
            child.get("edge") == "1"
            or (child.get("vertex") == "1" and "text" not in parse_style(child.get("style", "")))
            for child in child_cells.get(cell_id, [])
        )
        if structural_children:
            continue
        group, matrix = groups[cell_id]
        try:
            bounds = rendered_shape_bounds(group, matrix)
        except (IndexError, ValueError):
            bounds = None
        if bounds is not None:
            rendered_shapes[cell_id] = (bounds, style)

    for edge in edges:
        endpoints = {edge.source, edge.target}
        for shape_id, (bounds, style) in rendered_shapes.items():
            if shape_id in endpoints:
                continue
            if any(segment_enters_shape(segment, bounds, style) for segment in edge.segments):
                issues.append(
                    Issue(
                        "error",
                        "EDGE_THROUGH_SHAPE",
                        page,
                        f"rendered path enters non-endpoint shape {shape_id}",
                        edge.cell_id,
                        evidence={"non_endpoint_shape": shape_id},
                    )
                )

    return issues


def resolve_drawio_cli(explicit: Path | None) -> Path:
    if explicit is not None:
        candidates = [explicit.expanduser()]
    else:
        candidates = [Path("/Applications/draw.io.app/Contents/MacOS/draw.io")]
        discovered = shutil.which("drawio")
        if discovered:
            candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_mode & 0o111:
            return candidate
    requested = f" at {explicit}" if explicit is not None else ""
    raise FileNotFoundError(f"Draw.io Desktop CLI not found{requested}")


def export_svg_page(drawio_cli: Path, drawio_file: Path, page_index: int, output: Path) -> None:
    command = [
        str(drawio_cli),
        "-x",
        "-f",
        "svg",
        "--page-index",
        str(page_index),
        "--embed-svg-fonts",
        "false",
        "--theme",
        "light",
        "-b",
        "0",
        "-o",
        str(output),
        str(drawio_file),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not output.is_file():
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit status {completed.returncode}"
        raise RuntimeError(f"page {page_index} SVG export failed: {detail}")


def validate_file(
    drawio_file: Path,
    *,
    check_rendered_edges: bool = False,
    drawio_cli: Path | None = None,
) -> tuple[int, list[Issue]]:
    """Validate one exact Draw.io file and return its page count and diagnostics."""
    models = load_models(drawio_file)
    issues: list[Issue] = []
    for page, model in models:
        issues.extend(validate_model(page, model))

    if check_rendered_edges and not any(issue.severity == "error" for issue in issues):
        resolved_cli = resolve_drawio_cli(drawio_cli)
        with tempfile.TemporaryDirectory(prefix="drawio-rendered-edge-check-") as temporary:
            temporary_path = Path(temporary)
            for page_index, (page, model) in enumerate(models, start=1):
                svg_path = temporary_path / f"page-{page_index}.svg"
                export_svg_page(resolved_cli, drawio_file, page_index, svg_path)
                svg_root = ET.parse(svg_path).getroot()
                issues.extend(validate_rendered_svg(page, model, svg_root))

    return len(models), issues


def format_issue(issue: Issue) -> str:
    location = f" [{issue.page}]"
    if issue.cell:
        location += f" cell={issue.cell}"
    return f"{issue.severity.upper()} {issue.code}{location}: {issue.message}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Draw.io XML structure, text boxes, and optional rendered edge geometry."
    )
    parser.add_argument("drawio_file", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--check-rendered-edges",
        action="store_true",
        help="Check visible edge coverage, ports, overlapping/close routes, crossings, obstacles and short segments.",
    )
    parser.add_argument(
        "--drawio-cli",
        type=Path,
        help="Draw.io Desktop CLI path; defaults to the standard macOS path or command lookup.",
    )
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Return a failing exit status when warnings are present.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        pages, issues = validate_file(
            args.drawio_file,
            check_rendered_edges=args.check_rendered_edges,
            drawio_cli=args.drawio_cli,
        )
    except (
        OSError,
        ET.ParseError,
        ValueError,
        binascii.Error,
        zlib.error,
        RuntimeError,
    ) as exc:
        if args.as_json:
            print(
                json.dumps(
                    {
                        "diagnostic_schema_version": 3,
                        "file": str(args.drawio_file),
                        "fatal": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(f"FATAL: {exc}", file=sys.stderr)
        return 2

    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    if args.as_json:
        print(
            json.dumps(
                {
                    "diagnostic_schema_version": 3,
                    "file": str(args.drawio_file),
                    "pages": pages,
                    "errors": errors,
                    "warnings": warnings,
                    "rendered_edge_check": args.check_rendered_edges,
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
            print(f"OK: {args.drawio_file} ({pages} page(s))")
        else:
            print(f"SUMMARY: {errors} error(s), {warnings} warning(s), {pages} page(s)")

    if errors or (warnings and args.strict_warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
