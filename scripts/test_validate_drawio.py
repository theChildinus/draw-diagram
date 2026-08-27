#!/usr/bin/env python3
"""Regression tests for Draw.io structure validation."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from validate_drawio import resolve_drawio_cli, validate_model, validate_rendered_svg


def model_with_text(text_parent: str) -> ET.Element:
    text_geometry = (
        'x="60" y="88" width="180" height="32"'
        if text_parent == "lane"
        else 'x="20" y="24" width="180" height="32"'
    )
    return ET.fromstring(
        f"""
        <mxGraphModel>
          <root>
            <mxCell id="0"/>
            <mxCell id="1" parent="0"/>
            <mxCell id="lane" value="阶段" style="swimlane;" vertex="1" parent="1">
              <mxGeometry x="20" y="20" width="480" height="240" as="geometry"/>
            </mxCell>
            <mxCell id="module" value="" style="rounded=1;" vertex="1" parent="lane">
              <mxGeometry x="40" y="60" width="220" height="100" as="geometry"/>
            </mxCell>
            <mxCell id="module-text" value="模块名称" style="text;connectable=0;" vertex="1" parent="{text_parent}">
              <mxGeometry {text_geometry} as="geometry"/>
            </mxCell>
          </root>
        </mxGraphModel>
        """
    )


def rendered_model(*edges: str, include_obstacle: bool = False) -> ET.Element:
    obstacle = """
      <mxCell id="obstacle" value="障碍" style="rounded=1;" vertex="1" parent="1">
        <mxGeometry x="40" y="40" width="20" height="20" as="geometry"/>
      </mxCell>
    """ if include_obstacle else ""
    return ET.fromstring(
        f"""
        <mxGraphModel>
          <root>
            <mxCell id="0"/>
            <mxCell id="1" parent="0"/>
            <mxCell id="source-a" vertex="1" parent="1"><mxGeometry width="10" height="10" as="geometry"/></mxCell>
            <mxCell id="target-a" vertex="1" parent="1"><mxGeometry width="10" height="10" as="geometry"/></mxCell>
            <mxCell id="source-b" vertex="1" parent="1"><mxGeometry width="10" height="10" as="geometry"/></mxCell>
            <mxCell id="target-b" vertex="1" parent="1"><mxGeometry width="10" height="10" as="geometry"/></mxCell>
            {obstacle}
            {''.join(edges)}
          </root>
        </mxGraphModel>
        """
    )


def model_with_background_container(arc_size: int, width: int = 720, height: int = 520) -> ET.Element:
    return ET.fromstring(
        f"""
        <mxGraphModel>
          <root>
            <mxCell id="0"/>
            <mxCell id="1" parent="0"/>
            <mxCell id="region-bg" value=""
              style="rounded=1;arcSize={arc_size};pointerEvents=0;connectable=0;"
              vertex="1" parent="1">
              <mxGeometry x="20" y="20" width="{width}" height="{height}" as="geometry"/>
            </mxCell>
          </root>
        </mxGraphModel>
        """
    )


def edge_cell(cell_id: str, source: str, target: str, extra_style: str = "") -> str:
    return f"""
      <mxCell id="{cell_id}" edge="1" parent="1" source="{source}" target="{target}"
        style="edgeStyle=orthogonalEdgeStyle;rounded=1;{extra_style}">
        <mxGeometry relative="1" as="geometry"/>
      </mxCell>
    """


def svg_with_cells(*cells: str) -> ET.Element:
    return ET.fromstring(
        f'<svg xmlns="http://www.w3.org/2000/svg"><g>{"".join(cells)}</g></svg>'
    )


def svg_edge(cell_id: str, path: str) -> str:
    return f"""
      <g data-cell-id="{cell_id}"><g transform="translate(0.5,0.5)">
        <path d="{path}" fill="none" stroke="#000000" pointer-events="stroke"/>
      </g></g>
    """


class SiblingOverlayTest(unittest.TestCase):
    def test_rejects_text_over_blank_sibling_shape(self) -> None:
        issues = validate_model("Page-1", model_with_text("lane"))

        self.assertIn("TEXT_SIBLING_OVERLAY", {issue.code for issue in issues})

    def test_accepts_text_owned_by_shape(self) -> None:
        issues = validate_model("Page-1", model_with_text("module"))

        self.assertEqual([], issues)


class OuterContainerCornerRadiusTest(unittest.TestCase):
    def test_rejects_large_background_with_card_corner_radius(self) -> None:
        issues = validate_model("Page-1", model_with_background_container(12))

        self.assertIn("OUTER_CONTAINER_CORNER_RADIUS", {issue.code for issue in issues})

    def test_accepts_large_background_with_small_corner_radius(self) -> None:
        issues = validate_model("Page-1", model_with_background_container(4))

        self.assertNotIn("OUTER_CONTAINER_CORNER_RADIUS", {issue.code for issue in issues})

    def test_ignores_compact_background_card(self) -> None:
        issues = validate_model(
            "Page-1", model_with_background_container(12, width=240, height=180)
        )

        self.assertNotIn("OUTER_CONTAINER_CORNER_RADIUS", {issue.code for issue in issues})


class RenderedEdgeTest(unittest.TestCase):
    def test_explicit_missing_cli_does_not_fall_back(self) -> None:
        with self.assertRaises(FileNotFoundError):
            resolve_drawio_cli(Path("/definitely/missing/drawio"))

    def test_reports_transverse_edge_crossing(self) -> None:
        model = rendered_model(
            edge_cell("edge-a", "source-a", "target-a"),
            edge_cell("edge-b", "source-b", "target-b"),
        )
        svg = svg_with_cells(
            svg_edge("edge-a", "M 0 50 L 100 50"),
            svg_edge("edge-b", "M 50 0 L 50 100"),
        )

        issues = validate_rendered_svg("Page-1", model, svg)

        self.assertIn("EDGE_CROSSING", {issue.code for issue in issues})

    def test_reports_crossing_on_rounded_curve(self) -> None:
        model = rendered_model(
            edge_cell("edge-a", "source-a", "target-a"),
            edge_cell("edge-b", "source-b", "target-b"),
        )
        svg = svg_with_cells(
            svg_edge("edge-a", "M 65 0 L 65 100"),
            svg_edge("edge-b", "M 62.5 90 Q 62.5 80 72.5 80 L 100 80"),
        )

        issues = validate_rendered_svg("Page-1", model, svg)

        self.assertIn("EDGE_CROSSING", {issue.code for issue in issues})

    def test_allows_edges_to_meet_at_shared_endpoint(self) -> None:
        model = rendered_model(
            edge_cell("edge-a", "source-a", "target-a"),
            edge_cell("edge-b", "source-a", "target-b"),
        )
        svg = svg_with_cells(
            svg_edge("edge-a", "M 0 0 L 50 0"),
            svg_edge("edge-b", "M 0 0 L 0 50"),
        )

        issues = validate_rendered_svg("Page-1", model, svg)

        self.assertNotIn("EDGE_CROSSING", {issue.code for issue in issues})

    def test_reports_edge_through_non_endpoint_shape(self) -> None:
        model = rendered_model(
            edge_cell("edge-a", "source-a", "target-a"),
            include_obstacle=True,
        )
        svg = svg_with_cells(
            '<g data-cell-id="obstacle"><g><rect x="40" y="40" width="20" height="20" fill="#fff" pointer-events="all"/></g></g>',
            svg_edge("edge-a", "M 0 50 L 100 50"),
        )

        issues = validate_rendered_svg("Page-1", model, svg)

        self.assertIn("EDGE_THROUGH_SHAPE", {issue.code for issue in issues})

    def test_reports_short_routed_segments(self) -> None:
        model = rendered_model(edge_cell("edge-a", "source-a", "target-a"))
        svg = svg_with_cells(svg_edge("edge-a", "M 0 0 L 10 0 L 50 0 L 50 20"))

        issues = validate_rendered_svg("Page-1", model, svg)
        codes = {issue.code for issue in issues}

        self.assertIn("EDGE_SHORT_START", codes)
        self.assertIn("EDGE_SHORT_END", codes)

    def test_flags_jump_style_for_manual_review(self) -> None:
        model = rendered_model(
            edge_cell("edge-a", "source-a", "target-a", "jumpStyle=arc;")
        )
        svg = svg_with_cells(svg_edge("edge-a", "M 0 0 L 100 0"))

        issues = validate_rendered_svg("Page-1", model, svg)

        self.assertIn("EDGE_JUMP_STYLE_REVIEW", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()
