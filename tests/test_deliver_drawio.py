#!/usr/bin/env python3
"""Regression tests for bounded, atomic Draw.io delivery."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from deliver_drawio import (
    DeliveryError,
    ExportRequest,
    classify_warnings,
    commit_staged_files,
    deliver,
    validation_receipt,
)
from validate_drawio import Issue, validate_file as real_validate_file


def routed_document(*, x: int = 20, port: str = "0.5", parent: str = "1", label: str = "调用") -> bytes:
    return f'''<mxfile><diagram name="Page-1"><mxGraphModel><root>
      <mxCell id="0"/><mxCell id="1" parent="0"/>
      <mxCell id="a" vertex="1" parent="1"><mxGeometry x="{x}" y="20" width="80" height="40" as="geometry"/></mxCell>
      <mxCell id="b" vertex="1" parent="1"><mxGeometry x="220" y="20" width="80" height="40" as="geometry"/></mxCell>
      <mxCell id="e" edge="1" source="a" target="b" parent="{parent}" value="{label}" style="exitX=1;exitY={port};">
        <mxGeometry relative="1" as="geometry"/>
      </mxCell>
    </root></mxGraphModel></diagram></mxfile>'''.encode()


class AutomaticEdgeCheckTest(unittest.TestCase):
    def test_routing_changes_enable_render_checks_without_a_flag(self) -> None:
        variants = [routed_document(x=50), routed_document(port="0.25"),
                    routed_document(parent="a"),
                    routed_document().replace(b'relative="1" as="geometry"/>',
                        b'relative="1" as="geometry"><Array as="points"><mxPoint x="150" y="100"/></Array></mxGeometry>')]
        for changed in variants:
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                target, candidate = directory / "target.drawio", directory / "candidate.drawio"
                before = routed_document()
                target.write_bytes(before)
                candidate.write_bytes(changed)
                with patch("deliver_drawio.validate_file", return_value=(1, [])) as validate:
                    code, receipt = deliver(candidate, target, expected_target_sha256=sha256(before),
                        visual_risk="local", visual_review="passed", reviewed_candidate_sha256=sha256(changed))
                self.assertEqual(0, code)
                self.assertTrue(validate.call_args.kwargs["check_rendered_edges"])
                self.assertTrue(receipt["validation"]["rendered_edge_check"])

    def test_new_diagram_with_edges_gets_render_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate, target = directory / "candidate.drawio", directory / "new.drawio"
            data = routed_document()
            candidate.write_bytes(data)
            with patch("deliver_drawio.validate_file", return_value=(1, [])) as validate:
                code, receipt = deliver(candidate, target, expected_target_sha256="missing",
                    visual_risk="global", visual_review="passed", reviewed_candidate_sha256=sha256(data))
            self.assertEqual(0, code)
            self.assertTrue(validate.call_args.kwargs["check_rendered_edges"])

    def test_identical_geometry_and_label_changes_do_not_force_a_render(self) -> None:
        for data in [routed_document(), routed_document(label="更新说明")]:
            with self.subTest(data=data), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                candidate, target = directory / "candidate.drawio", directory / "target.drawio"
                before = routed_document()
                candidate.write_bytes(data)
                target.write_bytes(before)
                with patch("deliver_drawio.validate_file", return_value=(1, [])) as validate:
                    code, receipt = deliver(candidate, target, expected_target_sha256=sha256(before),
                        visual_risk="local", visual_review="passed", reviewed_candidate_sha256=sha256(data))
                self.assertEqual(0, code)
                self.assertFalse(validate.call_args.kwargs["check_rendered_edges"])

    def test_geometry_change_cannot_claim_no_visual_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate, target = directory / "candidate.drawio", directory / "target.drawio"
            before = routed_document()
            candidate.write_bytes(routed_document(x=50))
            target.write_bytes(before)
            with patch("deliver_drawio.validate_file", return_value=(1, [])):
                code, receipt = deliver(candidate, target, expected_target_sha256=sha256(before))
            self.assertEqual(1, code)
            self.assertEqual("VISUAL_RISK_UNDERSTATED", receipt["failure"]["code"])
            self.assertEqual(before, target.read_bytes())

    def test_closer_ports_are_a_worsened_warning(self) -> None:
        before = Issue("warning", "EDGE_PORT_SPACING", "Page-1", "before", "a",
                       subject="port:n:a:source:b:source", evidence={"actual_px": 10, "minimum_px": 12})
        after = Issue("warning", "EDGE_PORT_SPACING", "Page-1", "after", "a",
                      subject=before.subject, evidence={"actual_px": 5, "minimum_px": 12})
        result = classify_warnings([after], [before], [])
        self.assertEqual([after], result.worsened)
        self.assertEqual([after], result.unaccepted)


def drawio_document(marker: str, *, warning: bool = False, duplicate: bool = False) -> bytes:
    extra = ""
    if warning:
        extra = """
          <mxCell id="title" value="标题" style="text;connectable=0;" vertex="1" parent="1">
            <mxGeometry x="20" y="20" width="120" height="24" as="geometry"/>
          </mxCell>
        """
    if duplicate:
        extra = '<mxCell id="node" vertex="1" parent="1"><mxGeometry width="80" height="40" as="geometry"/></mxCell>'
    return f"""
    <mxfile host="Electron">
      <diagram id="page-1" name="Page-1">
        <mxGraphModel>
          <root>
            <mxCell id="0"/>
            <mxCell id="1" parent="0"/>
            <mxCell id="node" value="{marker}" vertex="1" parent="1">
              <mxGeometry x="20" y="20" width="80" height="40" as="geometry"/>
            </mxCell>
            {extra}
          </root>
        </mxGraphModel>
      </diagram>
    </mxfile>
    """.encode("utf-8")


def multi_page_document() -> bytes:
    pages = []
    for index in (1, 2):
        pages.append(
            f"""
            <diagram id="page-{index}" name="Page-{index}">
              <mxGraphModel><root>
                <mxCell id="0"/><mxCell id="1" parent="0"/>
                <mxCell id="node-{index}" value="Page {index}" vertex="1" parent="1">
                  <mxGeometry width="80" height="40" as="geometry"/>
                </mxCell>
              </root></mxGraphModel>
            </diagram>
            """
        )
    return f'<mxfile host="Electron">{"".join(pages)}</mxfile>'.encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_fake_drawio(path: Path, *, fail: bool = False) -> None:
    if fail:
        source = "#!/bin/sh\nexit 9\n"
    else:
        source = """#!/usr/bin/env python3
import pathlib
import sys

output = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
export_format = sys.argv[sys.argv.index("-f") + 1]
if "--all-pages" in sys.argv:
    selection = "all"
elif "--page-index" in sys.argv:
    selection = "page-" + sys.argv[sys.argv.index("--page-index") + 1]
else:
    selection = "implicit"
output.write_bytes(("fake-export-" + export_format + "-" + selection).encode("utf-8"))
"""
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


class AtomicDeliveryTest(unittest.TestCase):
    def test_commit_failure_rolls_back_every_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first_stage = directory / ".first-stage"
            second_stage = directory / ".second-stage"
            first_target = directory / "first.drawio"
            second_target = directory / "second.svg"
            first_stage.write_bytes(b"new-source")
            second_stage.write_bytes(b"new-export")
            first_target.write_bytes(b"old-source")
            second_target.write_bytes(b"old-export")
            real_replace = os.replace

            def fail_second_replace(source, destination):
                if Path(source) == second_stage:
                    raise OSError("injected second replace failure")
                return real_replace(source, destination)

            with patch("deliver_drawio.os.replace", side_effect=fail_second_replace):
                with self.assertRaises(DeliveryError) as captured:
                    commit_staged_files(
                        [(first_stage, first_target), (second_stage, second_target)]
                    )

            self.assertEqual("COMMIT_FAILED", captured.exception.code)
            self.assertEqual(b"old-source", first_target.read_bytes())
            self.assertEqual(b"old-export", second_target.read_bytes())

    def test_validation_receipt_bounds_diagnostics(self) -> None:
        issues = [
            Issue("error", "DUPLICATE_ID", "Page-1", "duplicate", cell="a"),
            Issue("warning", "TEXT_BOUNDARY_UNCHECKED", "Page-1", "text", cell="b"),
        ]
        warning_delta = classify_warnings(issues, [], [])

        receipt = validation_receipt(
            1,
            issues,
            check_rendered_edges=False,
            baseline_status="missing",
            baseline_issues=[],
            baseline_failure=None,
            warning_delta=warning_delta,
            max_issues=1,
        )

        self.assertEqual(2, receipt["issue_count"])
        self.assertTrue(receipt["issues_truncated"])
        self.assertEqual(1, len(receipt["issues"]))

    def test_success_replaces_target_with_exact_candidate_and_emits_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            old_bytes = drawio_document("旧版本")
            candidate_bytes = drawio_document("新版本")
            candidate.write_bytes(candidate_bytes)
            target.write_bytes(old_bytes)

            exit_code, receipt = deliver(
                candidate,
                target,
                expected_target_sha256=sha256(old_bytes),
                visual_risk="local",
                visual_review="passed",
                reviewed_candidate_sha256=sha256(candidate_bytes),
            )

            self.assertEqual(0, exit_code)
            self.assertEqual("passed", receipt["status"])
            self.assertTrue(receipt["committed"])
            self.assertEqual(candidate_bytes, target.read_bytes())
            self.assertEqual(candidate_bytes, candidate.read_bytes())
            self.assertEqual(sha256(candidate_bytes), receipt["target"]["after"]["sha256"])
            self.assertEqual(0, receipt["validation"]["errors"])
            self.assertEqual("passed", receipt["visual_review"]["status"])
            self.assertEqual("local", receipt["visual_review"]["risk"])

    def test_validation_failure_preserves_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            old_bytes = drawio_document("可信版本")
            candidate.write_bytes(drawio_document("重复节点", duplicate=True))
            target.write_bytes(old_bytes)

            exit_code, receipt = deliver(
                candidate,
                target,
                expected_target_sha256=sha256(old_bytes),
            )

            self.assertEqual(1, exit_code)
            self.assertEqual("rejected", receipt["status"])
            self.assertEqual("VALIDATION_FAILED", receipt["failure"]["code"])
            self.assertFalse(receipt["committed"])
            self.assertEqual(old_bytes, target.read_bytes())
            issue = next(
                issue
                for issue in receipt["validation"]["issues"]
                if issue["code"] == "DUPLICATE_ID"
            )
            self.assertEqual("cell:node", issue["subject"])
            self.assertIn("rename_duplicate_cell_id", issue["supported_fixes"])

    def test_new_warning_requires_exact_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            old_bytes = drawio_document("旧版本")
            candidate.write_bytes(drawio_document("含顶层文字", warning=True))
            target.write_bytes(old_bytes)

            rejected_code, rejected = deliver(
                candidate,
                target,
                expected_target_sha256=sha256(old_bytes),
            )
            fingerprint = rejected["validation"]["issues"][0]["fingerprint"]
            passed_code, passed = deliver(
                candidate,
                target,
                accepted_warning_fingerprints=[fingerprint],
                expected_target_sha256=sha256(old_bytes),
            )

            self.assertEqual(1, rejected_code)
            self.assertEqual("WARNING_ACCEPTANCE_REQUIRED", rejected["failure"]["code"])
            self.assertEqual(1, rejected["validation"]["warning_delta"]["new"])
            self.assertEqual(0, passed_code)
            self.assertEqual(1, passed["validation"]["warning_delta"]["accepted"])

    def test_unchanged_baseline_warning_does_not_block_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            old_bytes = drawio_document("旧版本", warning=True)
            candidate.write_bytes(drawio_document("新版本", warning=True))
            target.write_bytes(old_bytes)

            exit_code, receipt = deliver(
                candidate,
                target,
                expected_target_sha256=sha256(old_bytes),
            )

            self.assertEqual(0, exit_code)
            self.assertEqual(1, receipt["validation"]["warning_delta"]["existing"])
            self.assertEqual(0, receipt["validation"]["warning_delta"]["unaccepted"])

    def test_unknown_warning_acceptance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            old_bytes = drawio_document("旧版本")
            candidate.write_bytes(drawio_document("新版本"))
            target.write_bytes(old_bytes)

            exit_code, receipt = deliver(
                candidate,
                target,
                accepted_warning_fingerprints=["diag-not-present"],
                expected_target_sha256=sha256(old_bytes),
            )

            self.assertEqual(1, exit_code)
            self.assertEqual("UNKNOWN_WARNING_ACCEPTANCE", receipt["failure"]["code"])

    def test_expected_hash_mismatch_preserves_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            old_bytes = drawio_document("旧版本")
            candidate.write_bytes(drawio_document("新版本"))
            target.write_bytes(old_bytes)

            exit_code, receipt = deliver(
                candidate,
                target,
                expected_target_sha256="0" * 64,
            )

            self.assertEqual(1, exit_code)
            self.assertEqual("TARGET_PRECONDITION_FAILED", receipt["failure"]["code"])
            self.assertEqual(old_bytes, target.read_bytes())

    def test_expected_target_hash_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            old_bytes = drawio_document("旧版本")
            candidate.write_bytes(drawio_document("新版本"))
            target.write_bytes(old_bytes)

            exit_code, receipt = deliver(candidate, target)

            self.assertEqual(1, exit_code)
            self.assertEqual("EXPECTED_TARGET_REQUIRED", receipt["failure"]["code"])
            self.assertEqual(old_bytes, target.read_bytes())

    def test_new_target_requires_explicit_missing_precondition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "new.drawio"
            candidate_bytes = drawio_document("新文件")
            candidate.write_bytes(candidate_bytes)

            exit_code, receipt = deliver(
                candidate,
                target,
                expected_target_sha256="missing",
            )

            self.assertEqual(0, exit_code)
            self.assertEqual(candidate_bytes, target.read_bytes())
            self.assertFalse(receipt["target"]["before"]["exists"])

    def test_concurrent_target_change_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            candidate.write_bytes(drawio_document("候选版本"))
            target.write_bytes(drawio_document("初始版本"))
            concurrent_bytes = drawio_document("并发版本")

            def validate_and_change(*args, **kwargs):
                result = real_validate_file(*args, **kwargs)
                target.write_bytes(concurrent_bytes)
                return result

            with patch("deliver_drawio.validate_file", side_effect=validate_and_change):
                exit_code, receipt = deliver(
                    candidate,
                    target,
                    expected_target_sha256=sha256(drawio_document("初始版本")),
                )

            self.assertEqual(1, exit_code)
            self.assertEqual("TARGET_CHANGED", receipt["failure"]["code"])
            self.assertEqual(concurrent_bytes, target.read_bytes())

    def test_export_failure_preserves_source_and_existing_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            export = directory / "diagram.svg"
            fake_cli = directory / "drawio"
            old_source = drawio_document("旧版本")
            old_export = b"old-export"
            candidate.write_bytes(drawio_document("新版本"))
            target.write_bytes(old_source)
            export.write_bytes(old_export)
            write_fake_drawio(fake_cli, fail=True)

            exit_code, receipt = deliver(
                candidate,
                target,
                exports=[export],
                drawio_cli=fake_cli,
                expected_target_sha256=sha256(old_source),
            )

            self.assertEqual(2, exit_code)
            self.assertEqual("EXPORT_FAILED", receipt["failure"]["code"])
            self.assertEqual(old_source, target.read_bytes())
            self.assertEqual(old_export, export.read_bytes())

    def test_successful_export_is_bound_to_same_candidate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            export = directory / "diagram.svg"
            fake_cli = directory / "drawio"
            candidate.write_bytes(drawio_document("新版本"))
            old_bytes = drawio_document("旧版本")
            target.write_bytes(old_bytes)
            write_fake_drawio(fake_cli)

            exit_code, receipt = deliver(
                candidate,
                target,
                exports=[export],
                drawio_cli=fake_cli,
                expected_target_sha256=sha256(old_bytes),
            )

            self.assertEqual(0, exit_code)
            self.assertEqual(b"fake-export-svg-page-1", export.read_bytes())
            self.assertEqual(1, len(receipt["artifacts"]))
            self.assertEqual([1], receipt["artifacts"][0]["pages"])
            self.assertEqual(sha256(export.read_bytes()), receipt["artifacts"][0]["after"]["sha256"])

    def test_local_visual_change_requires_matching_reviewed_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            candidate_bytes = drawio_document("新版本")
            old_bytes = drawio_document("旧版本")
            candidate.write_bytes(candidate_bytes)
            target.write_bytes(old_bytes)

            missing_code, missing = deliver(
                candidate,
                target,
                expected_target_sha256=sha256(old_bytes),
                visual_risk="local",
                visual_review="passed",
            )
            mismatch_code, mismatch = deliver(
                candidate,
                target,
                expected_target_sha256=sha256(old_bytes),
                visual_risk="local",
                visual_review="passed",
                reviewed_candidate_sha256="0" * 64,
            )
            passed_code, passed = deliver(
                candidate,
                target,
                expected_target_sha256=sha256(old_bytes),
                visual_risk="local",
                visual_review="passed",
                reviewed_candidate_sha256=sha256(candidate_bytes),
            )

            self.assertEqual(1, missing_code)
            self.assertEqual("REVIEWED_CANDIDATE_HASH_REQUIRED", missing["failure"]["code"])
            self.assertEqual(1, mismatch_code)
            self.assertEqual("REVIEWED_CANDIDATE_MISMATCH", mismatch["failure"]["code"])
            self.assertEqual(0, passed_code)
            self.assertEqual("passed", passed["status"])

    def test_global_visual_change_requires_completed_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            old_bytes = drawio_document("旧版本")
            candidate.write_bytes(drawio_document("新版本"))
            target.write_bytes(old_bytes)

            exit_code, receipt = deliver(
                candidate,
                target,
                expected_target_sha256=sha256(old_bytes),
                visual_risk="global",
                visual_review="not-performed",
            )

            self.assertEqual(1, exit_code)
            self.assertEqual("VISUAL_REVIEW_REQUIRED", receipt["failure"]["code"])
            self.assertEqual(old_bytes, target.read_bytes())

    def test_multi_page_image_requires_explicit_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            export = directory / "diagram.svg"
            fake_cli = directory / "drawio"
            old_bytes = multi_page_document()
            candidate.write_bytes(old_bytes)
            target.write_bytes(old_bytes)
            write_fake_drawio(fake_cli)

            exit_code, receipt = deliver(
                candidate,
                target,
                exports=[export],
                drawio_cli=fake_cli,
                expected_target_sha256=sha256(old_bytes),
            )

            self.assertEqual(1, exit_code)
            self.assertEqual(
                "MULTI_PAGE_IMAGE_EXPORT_REQUIRES_PAGE",
                receipt["failure"]["code"],
            )
            self.assertFalse(export.exists())

    def test_explicit_multi_page_image_and_all_page_pdf_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.drawio"
            target = directory / "diagram.drawio"
            page_svg = directory / "page-2.svg"
            all_pdf = directory / "all.pdf"
            fake_cli = directory / "drawio"
            old_bytes = multi_page_document()
            candidate.write_bytes(old_bytes)
            target.write_bytes(old_bytes)
            write_fake_drawio(fake_cli)

            exit_code, receipt = deliver(
                candidate,
                target,
                exports=[ExportRequest(page_svg, page_index=2), all_pdf],
                drawio_cli=fake_cli,
                expected_target_sha256=sha256(old_bytes),
            )

            self.assertEqual(0, exit_code)
            self.assertEqual(b"fake-export-svg-page-2", page_svg.read_bytes())
            self.assertEqual(b"fake-export-pdf-all", all_pdf.read_bytes())
            self.assertEqual([2], receipt["artifacts"][0]["pages"])
            self.assertEqual("all", receipt["artifacts"][1]["pages"])

    def test_shorter_existing_segment_is_classified_as_worsened(self) -> None:
        baseline = Issue(
            "warning",
            "EDGE_SHORT_END",
            "Page-1",
            "short",
            cell="edge-1",
            evidence={"actual_px": 20.0, "minimum_px": 24.0},
        )
        candidate = Issue(
            "warning",
            "EDGE_SHORT_END",
            "Page-1",
            "shorter",
            cell="edge-1",
            evidence={"actual_px": 12.0, "minimum_px": 24.0},
        )

        delta = classify_warnings([candidate], [baseline], [])
        stale_acceptance = classify_warnings(
            [candidate],
            [baseline],
            [baseline.fingerprint],
        )

        self.assertNotEqual(baseline.fingerprint, candidate.fingerprint)
        self.assertEqual([], delta.existing)
        self.assertEqual([candidate], delta.worsened)
        self.assertEqual([candidate], delta.unaccepted)
        self.assertEqual([candidate], stale_acceptance.unaccepted)
        self.assertEqual([baseline.fingerprint], stale_acceptance.unknown_acceptances)


if __name__ == "__main__":
    unittest.main()
