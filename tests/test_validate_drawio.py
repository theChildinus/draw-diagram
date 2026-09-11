#!/usr/bin/env python3
"""Regression tests for Draw.io structure validation."""

from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

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

    def test_diagnostic_exposes_subject_evidence_and_supported_fixes(self) -> None:
        issues = validate_model("Page-1", model_with_background_container(12))
        issue = next(
            issue for issue in issues if issue.code == "OUTER_CONTAINER_CORNER_RADIUS"
        )
        payload = asdict(issue)

        self.assertEqual("cell:region-bg", payload["subject"])
        self.assertRegex(payload["fingerprint"], r"^diag-[0-9a-f]{16}$")
        self.assertEqual(12.0, payload["evidence"]["arc_size"])
        self.assertEqual(4.0, payload["evidence"]["maximum_arc_size"])
        self.assertIn("set_arc_size_at_most_4", payload["supported_fixes"])

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

    def test_shared_endpoint_is_reported_as_a_port_problem(self) -> None:
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
        self.assertIn("EDGE_SHARED_PORT", {issue.code for issue in issues})

    def test_shared_incoming_and_mixed_ports_are_checked(self) -> None:
        for first, second, paths in [
            (edge_cell("a", "source-a", "target-a"), edge_cell("b", "source-b", "target-a"),
             ("M -80 0 L 0 0", "M 0 -80 L 0 0")),
            (edge_cell("a", "source-a", "target-a"), edge_cell("b", "target-a", "target-b"),
             ("M -80 0 L 0 0", "M 0 0 L 0 80")),
        ]:
            with self.subTest(paths=paths):
                issues = validate_rendered_svg("Page-1", rendered_model(first, second),
                    svg_with_cells(svg_edge("a", paths[0]), svg_edge("b", paths[1])))
                self.assertIn("EDGE_SHARED_PORT", {i.code for i in issues})

    def test_distinct_ports_have_measured_clearance(self) -> None:
        model = rendered_model(edge_cell("a", "source-a", "target-a"),
                               edge_cell("b", "source-a", "target-b"))
        for gap in (5, 12, 20):
            with self.subTest(gap=gap):
                issues = validate_rendered_svg("Page-1", model, svg_with_cells(
                    svg_edge("a", "M 0 0 L 80 0"), svg_edge("b", f"M 0 {gap} L 80 {gap}")))
                self.assertEqual(gap < 12, any(i.code == "EDGE_PORT_SPACING" for i in issues))
                self.assertEqual(gap < 12, any(i.code == "EDGE_PARALLEL_CLEARANCE" for i in issues))

    def test_collinear_overlap_in_both_directions_and_diagonal(self) -> None:
        model = rendered_model(edge_cell("a", "source-a", "target-a"),
                               edge_cell("b", "source-b", "target-b"))
        for paths in [("M 0 0 L 100 0", "M 20 0 L 120 0"),
                      ("M 0 0 L 100 0", "M 120 0 L 20 0"),
                      ("M 0 0 L 100 100", "M 20 20 L 120 120")]:
            with self.subTest(paths=paths):
                issues = validate_rendered_svg("Page-1", model, svg_with_cells(
                    svg_edge("a", paths[0]), svg_edge("b", paths[1])))
                issue = next(i for i in issues if i.code == "EDGE_OVERLAP")
                self.assertEqual("error", issue.severity)
                self.assertGreater(issue.evidence["overlap_px"], 79)

    def test_separate_collinear_runs_do_not_overlap(self) -> None:
        model = rendered_model(edge_cell("a", "source-a", "target-a"),
                               edge_cell("b", "source-b", "target-b"))
        issues = validate_rendered_svg("Page-1", model, svg_with_cells(
            svg_edge("a", "M 0 0 L 80 0"), svg_edge("b", "M 100 0 L 180 0")))
        self.assertEqual([], issues)

    def test_explicit_visible_junction_allows_a_shared_port(self) -> None:
        model = rendered_model(edge_cell("a", "source-a", "target-a"),
                               edge_cell("b", "source-a", "target-b"))
        node = model.find(".//mxCell[@id='source-a']")
        node.set("style", "ellipse;diagramJunction=1;fillColor=#404A53;")
        svg = svg_with_cells(
            '<g data-cell-id="source-a"><ellipse cx="0.5" cy="0.5" rx="5" ry="5" fill="#404A53" pointer-events="all"/></g>',
            svg_edge("a", "M 0 0 L 80 0"), svg_edge("b", "M 0 0 L 0 80"))
        self.assertEqual([], validate_rendered_svg("Page-1", model, svg))
        node.find("mxGeometry").set("width", "160")
        issues = validate_rendered_svg("Page-1", model, svg)
        self.assertIn("EDGE_SHARED_PORT", {i.code for i in issues})

    def test_junction_does_not_exempt_duplicate_trunk(self) -> None:
        model = rendered_model(edge_cell("a", "source-a", "target-a"),
                               edge_cell("b", "source-a", "target-b"))
        model.find(".//mxCell[@id='source-a']").set("style", "ellipse;diagramJunction=1;")
        issues = validate_rendered_svg("Page-1", model, svg_with_cells(
            svg_edge("a", "M 0 0 L 80 0"), svg_edge("b", "M 0 0 L 120 0")))
        self.assertIn("EDGE_OVERLAP", {i.code for i in issues})

    def test_missing_or_unusable_visible_path_is_an_error(self) -> None:
        model = rendered_model(edge_cell("a", "source-a", "target-a"))
        for svg in [svg_with_cells(), svg_with_cells('<g data-cell-id="a"/>'),
                    svg_with_cells(svg_edge("a", "M 0 0")),
                    svg_with_cells(svg_edge("a", "M 0 0 X 80 0"))]:
            with self.subTest(svg=ET.tostring(svg)):
                issues = validate_rendered_svg("Page-1", model, svg)
                self.assertTrue(any(i.severity == "error" and i.code.startswith("EDGE_RENDER") for i in issues))

    def test_explicitly_hidden_edges_do_not_need_rendered_paths(self) -> None:
        model = rendered_model(edge_cell("a", "source-a", "target-a"))
        model.find(".//mxCell[@id='a']").set("visible", "0")
        self.assertEqual([], validate_rendered_svg("Page-1", model, svg_with_cells()))

    def test_hidden_layers_and_terminals_do_not_create_missing_path_errors(self) -> None:
        for cell_id in ("1", "source-a"):
            model = rendered_model(edge_cell("a", "source-a", "target-a"))
            model.find(f".//mxCell[@id='{cell_id}']").set("visible", "0")
            self.assertEqual([], validate_rendered_svg("Page-1", model, svg_with_cells()))

    def test_junction_marker_without_a_rendered_dot_is_not_an_exemption(self) -> None:
        model = rendered_model(edge_cell("a", "source-a", "target-a"),
                               edge_cell("b", "source-a", "target-b"))
        model.find(".//mxCell[@id='source-a']").set("style", "ellipse;diagramJunction=1;")
        svg = svg_with_cells('<g data-cell-id="source-a"/>',
            svg_edge("a", "M 0 0 L 80 0"), svg_edge("b", "M 0 0 L 0 80"))
        self.assertIn("EDGE_SHARED_PORT", {i.code for i in validate_rendered_svg("Page-1", model, svg)})

    def test_mixed_ports_use_shape_boundary_not_shortened_arrow_stroke(self) -> None:
        model = rendered_model(edge_cell("a", "source-b", "source-a"),
                               edge_cell("b", "source-a", "target-b"))
        svg = svg_with_cells(
            '<g data-cell-id="source-a"><rect x="100.5" y="0.5" width="80" height="80" fill="#fff" pointer-events="all"/></g>',
            svg_edge("a", "M 0 40 L 91 40"), svg_edge("b", "M 100 40 L 20 40"))
        issues = validate_rendered_svg("Page-1", model, svg)
        self.assertIn("EDGE_SHARED_PORT", {i.code for i in issues})

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

        short_end = next(issue for issue in issues if issue.code == "EDGE_SHORT_END")
        self.assertEqual(20.0, short_end.evidence["actual_px"])
        self.assertEqual(24.0, short_end.evidence["minimum_px"])
        self.assertIn("realign_target_or_adjust_route", short_end.supported_fixes)

    def test_flags_jump_style_for_manual_review(self) -> None:
        model = rendered_model(
            edge_cell("edge-a", "source-a", "target-a", "jumpStyle=arc;")
        )
        svg = svg_with_cells(svg_edge("edge-a", "M 0 0 L 100 0"))

        issues = validate_rendered_svg("Page-1", model, svg)

        self.assertIn("EDGE_JUMP_STYLE_REVIEW", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()
