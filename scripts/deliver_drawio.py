#!/usr/bin/env python3
"""Validate exact Draw.io candidate bytes and deliver them with a compact receipt."""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

from validate_drawio import Issue, resolve_drawio_cli, validate_file


RECEIPT_VERSION = 2
SUPPORTED_EXPORT_FORMATS = {"svg", "png", "pdf"}
VISUAL_RISKS = ("none", "local", "global")
VISUAL_REVIEW_STATUSES = ("passed", "not-performed", "failed")
MEASURED_WARNING_CODES = {
    "EDGE_SHORT_DIRECT",
    "EDGE_SHORT_START",
    "EDGE_SHORT_MIDDLE",
    "EDGE_SHORT_END",
}
VALIDATION_EXCEPTIONS = (
    OSError,
    ET.ParseError,
    ValueError,
    binascii.Error,
    zlib.error,
    RuntimeError,
)


@dataclass(frozen=True)
class ExportRequest:
    path: Path
    page_index: int | None = None


@dataclass
class WarningDelta:
    existing: list[Issue]
    new: list[Issue]
    worsened: list[Issue]
    accepted: list[Issue]
    unaccepted: list[Issue]
    unknown_acceptances: list[str]


class DeliveryError(RuntimeError):
    def __init__(self, code: str, message: str, *, exit_code: int = 2) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "sha256": None,
            "bytes": 0,
        }
    if path.is_symlink():
        raise DeliveryError("SYMLINK_TARGET", f"refuse to replace symbolic link: {path}")
    if not path.is_file():
        raise DeliveryError("TARGET_NOT_FILE", f"target is not a regular file: {path}")
    data = path.read_bytes()
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256_bytes(data),
        "bytes": len(data),
    }


def same_state(left: dict[str, object], right: dict[str, object]) -> bool:
    return (
        left["exists"] == right["exists"]
        and left["sha256"] == right["sha256"]
        and left["bytes"] == right["bytes"]
    )


def verify_expected_target(
    target_state: dict[str, object], expected_sha256: str | None
) -> None:
    if expected_sha256 is None:
        raise DeliveryError(
            "EXPECTED_TARGET_REQUIRED",
            "expected target SHA-256 is required; use 'missing' for a new target",
            exit_code=1,
        )
    if expected_sha256 == "missing":
        if target_state["exists"]:
            raise DeliveryError(
                "TARGET_PRECONDITION_FAILED",
                "target exists but the expected state was missing",
                exit_code=1,
            )
        return
    if target_state["sha256"] != expected_sha256:
        raise DeliveryError(
            "TARGET_PRECONDITION_FAILED",
            "target SHA-256 does not match the expected pre-edit state",
            exit_code=1,
        )


def new_staging_path(target: Path, *, kind: str, suffix: str | None = None) -> Path:
    if not target.parent.is_dir():
        raise DeliveryError(
            "TARGET_PARENT_MISSING", f"target directory does not exist: {target.parent}"
        )
    file_descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{target.name}.{kind}-",
        suffix=suffix or target.suffix,
        dir=target.parent,
    )
    os.close(file_descriptor)
    return Path(raw_path)


def write_snapshot(
    data: bytes,
    candidate: Path,
    target: Path,
    *,
    kind: str = "candidate",
) -> Path:
    snapshot = new_staging_path(target, kind=kind, suffix=".drawio")
    try:
        with snapshot.open("wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        mode_source = target if target.exists() else candidate
        os.chmod(snapshot, mode_source.stat().st_mode & 0o777)
        return snapshot
    except Exception:
        snapshot.unlink(missing_ok=True)
        raise


def export_artifact(
    drawio_cli: Path,
    source: Path,
    output: Path,
    export_format: str,
    *,
    page_index: int | None,
    all_pages: bool,
) -> None:
    command = [
        str(drawio_cli),
        "-x",
        "-f",
        export_format,
        "-e",
        "-b",
        "10",
    ]
    if all_pages:
        command.append("--all-pages")
    elif page_index is not None:
        command.extend(["--page-index", str(page_index)])
    command.extend(["-o", str(output), str(source)])
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if len(detail) > 1000:
            detail = f"{detail[:1000]}..."
        suffix = f": {detail}" if detail else ""
        raise DeliveryError(
            "EXPORT_FAILED",
            f"{export_format} export failed with exit status {completed.returncode}{suffix}",
        )
    with output.open("rb") as exported:
        os.fsync(exported.fileno())


def copy_backup(destination: Path) -> Path | None:
    if not destination.exists():
        return None
    backup = new_staging_path(destination, kind="backup")
    try:
        shutil.copy2(destination, backup)
        with backup.open("rb") as copied:
            os.fsync(copied.fileno())
        return backup
    except Exception:
        backup.unlink(missing_ok=True)
        raise


def fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def commit_staged_files(staged: Sequence[tuple[Path, Path]]) -> None:
    """Replace each destination and restore every prior file if one replace fails."""
    backups: dict[Path, Path | None] = {}
    committed: list[Path] = []
    try:
        for _, destination in staged:
            backups[destination] = copy_backup(destination)

        for source, destination in staged:
            if destination.exists():
                os.chmod(source, destination.stat().st_mode & 0o777)
            elif destination.suffix.lower() in {".svg", ".png", ".pdf"}:
                os.chmod(source, 0o644)
            os.replace(source, destination)
            fsync_directory(destination.parent)
            committed.append(destination)
    except Exception as exc:
        rollback_errors: list[str] = []
        for destination in reversed(committed):
            backup = backups.get(destination)
            try:
                if backup is None:
                    destination.unlink(missing_ok=True)
                elif backup.exists():
                    os.replace(backup, destination)
                    fsync_directory(destination.parent)
            except Exception as rollback_exc:
                rollback_errors.append(f"{destination}: {rollback_exc}")
        detail = f"; rollback errors: {'; '.join(rollback_errors)}" if rollback_errors else ""
        raise DeliveryError("COMMIT_FAILED", f"atomic delivery failed: {exc}{detail}") from exc
    finally:
        for backup in backups.values():
            if backup is not None:
                backup.unlink(missing_ok=True)


def normalize_export_requests(
    exports: Sequence[Path | ExportRequest],
) -> list[ExportRequest]:
    requests: list[ExportRequest] = []
    for export in exports:
        if isinstance(export, ExportRequest):
            requests.append(
                ExportRequest(absolute_path(export.path), page_index=export.page_index)
            )
        else:
            requests.append(ExportRequest(absolute_path(export)))
    return requests


def export_page_selection(
    request: ExportRequest,
    export_format: str,
    page_count: int,
) -> tuple[int | None, bool, object]:
    if request.page_index is not None:
        if request.page_index < 1 or request.page_index > page_count:
            raise DeliveryError(
                "EXPORT_PAGE_OUT_OF_RANGE",
                f"page {request.page_index} is outside the diagram page range 1..{page_count}",
                exit_code=1,
            )
        return request.page_index, False, [request.page_index]

    if export_format in {"svg", "png"}:
        if page_count > 1:
            raise DeliveryError(
                "MULTI_PAGE_IMAGE_EXPORT_REQUIRES_PAGE",
                (
                    f"multi-page {export_format.upper()} export needs an explicit page; "
                    "use --export-page PAGE=PATH once for each requested page"
                ),
                exit_code=1,
            )
        return 1, False, [1]

    if export_format == "pdf" and page_count > 1:
        return None, True, "all"
    return 1, False, [1]


def warning_is_worsened(candidate: Issue, baseline: Issue) -> bool:
    if candidate.code not in MEASURED_WARNING_CODES:
        return False
    candidate_value = candidate.evidence.get("actual_px")
    baseline_value = baseline.evidence.get("actual_px")
    if not isinstance(candidate_value, (int, float)) or not isinstance(
        baseline_value, (int, float)
    ):
        return False
    return float(candidate_value) < float(baseline_value) - 0.01


def issue_identity(issue: Issue) -> tuple[str, str, str | None]:
    return issue.code, issue.page, issue.subject


def classify_warnings(
    candidate_issues: Sequence[Issue],
    baseline_issues: Sequence[Issue],
    accepted_fingerprints: Sequence[str],
) -> WarningDelta:
    baseline_by_identity = {
        issue_identity(issue): issue
        for issue in baseline_issues
        if issue.severity == "warning"
    }
    existing: list[Issue] = []
    new: list[Issue] = []
    worsened: list[Issue] = []
    for issue in candidate_issues:
        if issue.severity != "warning":
            continue
        baseline = baseline_by_identity.get(issue_identity(issue))
        if baseline is None:
            new.append(issue)
        elif warning_is_worsened(issue, baseline):
            worsened.append(issue)
        else:
            existing.append(issue)

    accepted_set = set(accepted_fingerprints)
    blocking = [*new, *worsened]
    accepted = [issue for issue in blocking if issue.fingerprint in accepted_set]
    unaccepted = [issue for issue in blocking if issue.fingerprint not in accepted_set]
    blocking_fingerprints = {issue.fingerprint for issue in blocking}
    unknown_acceptances = sorted(accepted_set - blocking_fingerprints)
    return WarningDelta(
        existing=existing,
        new=new,
        worsened=worsened,
        accepted=accepted,
        unaccepted=unaccepted,
        unknown_acceptances=unknown_acceptances,
    )


def validate_visual_review(
    *,
    visual_risk: str,
    visual_review: str,
    reviewed_candidate_sha256: str | None,
    candidate_sha256: str,
) -> None:
    if visual_risk not in VISUAL_RISKS:
        raise DeliveryError("INVALID_VISUAL_RISK", f"invalid visual risk: {visual_risk}", exit_code=1)
    if visual_review not in VISUAL_REVIEW_STATUSES:
        raise DeliveryError(
            "INVALID_VISUAL_REVIEW",
            f"invalid visual review status: {visual_review}",
            exit_code=1,
        )
    if visual_review == "failed":
        raise DeliveryError(
            "VISUAL_REVIEW_FAILED",
            "visual review reported a visible defect",
            exit_code=1,
        )
    if visual_risk in {"local", "global"} and visual_review != "passed":
        raise DeliveryError(
            "VISUAL_REVIEW_REQUIRED",
            f"{visual_risk} visual changes require a passed review of the final candidate",
            exit_code=1,
        )
    if visual_review == "passed":
        if reviewed_candidate_sha256 is None:
            raise DeliveryError(
                "REVIEWED_CANDIDATE_HASH_REQUIRED",
                "a passed visual review requires the reviewed candidate SHA-256",
                exit_code=1,
            )
        if reviewed_candidate_sha256.lower() != candidate_sha256:
            raise DeliveryError(
                "REVIEWED_CANDIDATE_MISMATCH",
                "reviewed candidate SHA-256 does not match the delivered candidate",
                exit_code=1,
            )
    elif reviewed_candidate_sha256 is not None:
        raise DeliveryError(
            "UNEXPECTED_REVIEWED_CANDIDATE_HASH",
            "reviewed candidate SHA-256 is only valid with --visual-review passed",
            exit_code=1,
        )
def validation_receipt(
    pages: int,
    issues: Sequence[Issue],
    *,
    check_rendered_edges: bool,
    baseline_status: str,
    baseline_issues: Sequence[Issue],
    baseline_failure: str | None,
    warning_delta: WarningDelta,
    max_issues: int,
) -> dict[str, object]:
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    priority = [
        *(issue for issue in issues if issue.severity == "error"),
        *warning_delta.unaccepted,
        *warning_delta.accepted,
        *warning_delta.existing,
    ]
    included = list(priority[:max_issues])
    accepted_fingerprints = [issue.fingerprint for issue in warning_delta.accepted]
    return {
        "diagnostic_schema_version": 3,
        "pages": pages,
        "errors": errors,
        "warnings": warnings,
        "rendered_edge_check": check_rendered_edges,
        "baseline": {
            "status": baseline_status,
            "warnings": sum(issue.severity == "warning" for issue in baseline_issues),
            "failure": baseline_failure,
        },
        "warning_delta": {
            "existing": len(warning_delta.existing),
            "new": len(warning_delta.new),
            "worsened": len(warning_delta.worsened),
            "accepted": len(warning_delta.accepted),
            "unaccepted": len(warning_delta.unaccepted),
            "accepted_fingerprints": accepted_fingerprints[:max_issues],
            "accepted_fingerprints_truncated": len(accepted_fingerprints) > max_issues,
        },
        "issue_count": len(issues),
        "issues_truncated": len(priority) > len(included),
        "issues": [asdict(issue) for issue in included],
    }


def base_receipt(
    candidate: Path,
    target: Path,
    *,
    visual_risk: str,
    visual_review: str,
    reviewed_candidate_sha256: str | None,
) -> dict[str, object]:
    return {
        "receipt_version": RECEIPT_VERSION,
        "status": "failed",
        "committed": False,
        "candidate": {"path": str(candidate), "sha256": None, "bytes": 0},
        "target": {"path": str(target), "before": None, "after": None},
        "validation": None,
        "artifacts": [],
        "visual_review": {
            "risk": visual_risk,
            "status": visual_review,
            "reviewed_candidate_sha256": reviewed_candidate_sha256,
        },
        "failure": None,
    }


def reject(receipt: dict[str, object], code: str, message: str) -> tuple[int, dict[str, object]]:
    receipt["status"] = "rejected"
    receipt["failure"] = {"code": code, "message": message}
    return 1, receipt


def deliver(
    candidate_path: Path,
    target_path: Path,
    *,
    exports: Sequence[Path | ExportRequest] = (),
    check_rendered_edges: bool = False,
    drawio_cli: Path | None = None,
    accepted_warning_fingerprints: Sequence[str] = (),
    expected_target_sha256: str | None = None,
    visual_risk: str = "none",
    visual_review: str = "not-performed",
    reviewed_candidate_sha256: str | None = None,
    max_issues: int = 10,
) -> tuple[int, dict[str, object]]:
    candidate = absolute_path(candidate_path)
    target = absolute_path(target_path)
    export_requests = normalize_export_requests(exports)
    export_targets = [request.path for request in export_requests]
    receipt = base_receipt(
        candidate,
        target,
        visual_risk=visual_risk,
        visual_review=visual_review,
        reviewed_candidate_sha256=reviewed_candidate_sha256,
    )
    temporary_paths: list[Path] = []

    try:
        if candidate == target:
            raise DeliveryError(
                "CANDIDATE_EQUALS_TARGET",
                "candidate and target must be different paths",
                exit_code=1,
            )
        if candidate.suffix.lower() != ".drawio" or target.suffix.lower() != ".drawio":
            raise DeliveryError(
                "DRAWIO_SUFFIX_REQUIRED",
                "candidate and target must both use the .drawio suffix",
                exit_code=1,
            )
        if candidate.is_symlink() or not candidate.is_file():
            raise DeliveryError("CANDIDATE_NOT_FILE", f"candidate is not a regular file: {candidate}")
        if target.is_symlink():
            raise DeliveryError("SYMLINK_TARGET", f"refuse to replace symbolic link: {target}")
        if not target.parent.is_dir():
            raise DeliveryError("TARGET_PARENT_MISSING", f"target directory does not exist: {target.parent}")
        if max_issues < 1:
            raise DeliveryError("INVALID_MAX_ISSUES", "max_issues must be positive", exit_code=1)

        destinations = [target, *export_targets]
        if len(set(destinations)) != len(destinations):
            raise DeliveryError("DUPLICATE_TARGET", "target and export paths must be unique", exit_code=1)
        if candidate in destinations:
            raise DeliveryError("CANDIDATE_IS_OUTPUT", "candidate cannot also be an output path", exit_code=1)

        export_formats: list[str] = []
        for request in export_requests:
            export_target = request.path
            if export_target.is_symlink():
                raise DeliveryError(
                    "SYMLINK_TARGET", f"refuse to replace symbolic link: {export_target}"
                )
            if not export_target.parent.is_dir():
                raise DeliveryError(
                    "TARGET_PARENT_MISSING",
                    f"export directory does not exist: {export_target.parent}",
                )
            export_format = export_target.suffix.lower().lstrip(".")
            if export_format not in SUPPORTED_EXPORT_FORMATS:
                raise DeliveryError(
                    "UNSUPPORTED_EXPORT_FORMAT",
                    f"unsupported export suffix for {export_target}; use SVG, PNG, or PDF",
                    exit_code=1,
                )
            export_formats.append(export_format)

        target_before = file_state(target)
        receipt["target"]["before"] = target_before  # type: ignore[index]
        verify_expected_target(target_before, expected_target_sha256)
        export_before = {path: file_state(path) for path in export_targets}

        baseline_snapshot: Path | None = None
        if target_before["exists"]:
            baseline_bytes = target.read_bytes()
            if sha256_bytes(baseline_bytes) != target_before["sha256"]:
                return reject(
                    receipt,
                    "TARGET_CHANGED",
                    "target changed while its baseline snapshot was being captured",
                )
            baseline_snapshot = write_snapshot(
                baseline_bytes,
                target,
                target,
                kind="baseline",
            )
            temporary_paths.append(baseline_snapshot)

        candidate_bytes = candidate.read_bytes()
        candidate_sha256 = sha256_bytes(candidate_bytes)
        receipt["candidate"] = {
            "path": str(candidate),
            "sha256": candidate_sha256,
            "bytes": len(candidate_bytes),
        }
        snapshot = write_snapshot(candidate_bytes, candidate, target)
        temporary_paths.append(snapshot)

        pages, issues = validate_file(
            snapshot,
            check_rendered_edges=check_rendered_edges,
            drawio_cli=drawio_cli,
        )

        errors = sum(issue.severity == "error" for issue in issues)
        warnings = sum(issue.severity == "warning" for issue in issues)
        baseline_status = "missing" if baseline_snapshot is None else "not-needed"
        baseline_issues: list[Issue] = []
        baseline_failure: str | None = None
        if warnings and not errors and baseline_snapshot is not None:
            try:
                _, baseline_issues = validate_file(
                    baseline_snapshot,
                    check_rendered_edges=check_rendered_edges,
                    drawio_cli=drawio_cli,
                )
                baseline_status = "checked"
            except VALIDATION_EXCEPTIONS as exc:
                baseline_status = "unavailable"
                baseline_failure = f"{type(exc).__name__}: {exc}"
                if len(baseline_failure) > 500:
                    baseline_failure = f"{baseline_failure[:500]}..."

        warning_delta = classify_warnings(
            issues,
            baseline_issues,
            accepted_warning_fingerprints,
        )
        receipt["validation"] = validation_receipt(
            pages,
            issues,
            check_rendered_edges=check_rendered_edges,
            baseline_status=baseline_status,
            baseline_issues=baseline_issues,
            baseline_failure=baseline_failure,
            warning_delta=warning_delta,
            max_issues=max_issues,
        )
        if errors:
            return reject(
                receipt,
                "VALIDATION_FAILED",
                f"candidate has {errors} error(s) and {warnings} warning(s)",
            )
        if warning_delta.unknown_acceptances:
            return reject(
                receipt,
                "UNKNOWN_WARNING_ACCEPTANCE",
                (
                    "accepted warning fingerprint is not a new or worsened candidate warning: "
                    + ", ".join(warning_delta.unknown_acceptances[:5])
                ),
            )
        if warning_delta.unaccepted:
            return reject(
                receipt,
                "WARNING_ACCEPTANCE_REQUIRED",
                (
                    f"candidate has {len(warning_delta.unaccepted)} unaccepted new or "
                    "worsened warning(s)"
                ),
            )

        validate_visual_review(
            visual_risk=visual_risk,
            visual_review=visual_review,
            reviewed_candidate_sha256=reviewed_candidate_sha256,
            candidate_sha256=candidate_sha256,
        )

        resolved_cli: Path | None = None
        if export_targets:
            resolved_cli = resolve_drawio_cli(drawio_cli)

        staged_exports: list[tuple[Path, Path]] = []
        artifact_receipts: list[dict[str, object]] = []
        for request, export_format in zip(export_requests, export_formats):
            export_target = request.path
            page_index, all_pages, exported_pages = export_page_selection(
                request,
                export_format,
                pages,
            )
            staged_export = new_staging_path(
                export_target,
                kind="export",
                suffix=f".{export_format}",
            )
            staged_export.unlink(missing_ok=True)
            temporary_paths.append(staged_export)
            assert resolved_cli is not None
            export_artifact(
                resolved_cli,
                snapshot,
                staged_export,
                export_format,
                page_index=page_index,
                all_pages=all_pages,
            )
            exported_state = file_state(staged_export)
            artifact_receipts.append(
                {
                    "format": export_format,
                    "pages": exported_pages,
                    "path": str(export_target),
                    "before": export_before[export_target],
                    "after": {
                        "path": str(export_target),
                        "exists": True,
                        "sha256": exported_state["sha256"],
                        "bytes": exported_state["bytes"],
                    },
                }
            )
            staged_exports.append((staged_export, export_target))
        receipt["artifacts"] = artifact_receipts

        target_current = file_state(target)
        if not same_state(target_before, target_current):
            return reject(
                receipt,
                "TARGET_CHANGED",
                "target changed while the candidate was being validated",
            )
        for export_target in export_targets:
            if not same_state(export_before[export_target], file_state(export_target)):
                return reject(
                    receipt,
                    "EXPORT_TARGET_CHANGED",
                    f"export target changed while the candidate was being validated: {export_target}",
                )

        commit_staged_files([*staged_exports, (snapshot, target)])
        receipt["committed"] = True
        target_after = file_state(target)
        receipt["target"]["after"] = target_after  # type: ignore[index]
        if target_after["sha256"] != receipt["candidate"]["sha256"]:  # type: ignore[index]
            raise DeliveryError("POST_COMMIT_MISMATCH", "delivered target hash does not match candidate")
        for artifact in artifact_receipts:
            after = file_state(Path(str(artifact["path"])))
            if after["sha256"] != artifact["after"]["sha256"]:  # type: ignore[index]
                raise DeliveryError(
                    "POST_COMMIT_MISMATCH",
                    f"delivered export hash does not match staged artifact: {artifact['path']}",
                )
            artifact["after"] = after

        receipt["status"] = "passed"
        return 0, receipt
    except DeliveryError as exc:
        receipt["status"] = "rejected" if exc.exit_code == 1 else "failed"
        receipt["failure"] = {"code": exc.code, "message": str(exc)}
        try:
            receipt["target"]["after"] = file_state(target)  # type: ignore[index]
        except DeliveryError:
            pass
        return exc.exit_code, receipt
    except VALIDATION_EXCEPTIONS as exc:
        receipt["status"] = "failed"
        receipt["failure"] = {"code": "DELIVERY_EXCEPTION", "message": str(exc)}
        try:
            receipt["target"]["after"] = file_state(target)  # type: ignore[index]
        except DeliveryError:
            pass
        return 2, receipt
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)


def expected_sha256(value: str) -> str:
    if value == "missing":
        return value
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise argparse.ArgumentTypeError("expected target SHA-256 must be 64 hex characters or 'missing'")
    return value.lower()


def reviewed_sha256(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise argparse.ArgumentTypeError("reviewed candidate SHA-256 must be 64 hex characters")
    return value.lower()


def export_page_request(value: str) -> ExportRequest:
    page_text, separator, path_text = value.partition("=")
    if not separator or not page_text.isdigit() or not path_text:
        raise argparse.ArgumentTypeError("page export must use PAGE=PATH, for example 2=/tmp/page-2.svg")
    page_index = int(page_text)
    if page_index < 1:
        raise argparse.ArgumentTypeError("page export index must be positive")
    return ExportRequest(Path(path_text), page_index=page_index)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate exact candidate bytes, stage requested exports, atomically replace targets, "
            "and emit a bounded delivery receipt."
        )
    )
    parser.add_argument("candidate", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument(
        "--export",
        action="append",
        default=[],
        type=Path,
        help=(
            "Deliver an SVG/PNG for a single-page diagram or an all-page PDF. "
            "Use --export-page for a page from a multi-page image diagram."
        ),
    )
    parser.add_argument(
        "--export-page",
        action="append",
        default=[],
        type=export_page_request,
        metavar="PAGE=PATH",
        help="Deliver one explicit page as SVG, PNG, or PDF; repeat as needed.",
    )
    parser.add_argument("--check-rendered-edges", action="store_true")
    parser.add_argument("--drawio-cli", type=Path)
    parser.add_argument(
        "--accept-warning",
        action="append",
        default=[],
        metavar="FINGERPRINT",
        help="Accept one new or worsened warning fingerprint from the candidate receipt; repeat as needed.",
    )
    parser.add_argument(
        "--expected-target-sha256",
        type=expected_sha256,
        required=True,
        help="Pre-edit target SHA-256, or 'missing' for a new target.",
    )
    parser.add_argument(
        "--visual-risk",
        choices=VISUAL_RISKS,
        required=True,
        help="Declare whether the candidate has no, local, or global visual changes.",
    )
    parser.add_argument(
        "--visual-review",
        choices=VISUAL_REVIEW_STATUSES,
        required=True,
        help="Record the caller's truthful visual review status; this command does not inspect images.",
    )
    parser.add_argument(
        "--reviewed-candidate-sha256",
        type=reviewed_sha256,
        help="SHA-256 of the exact visually reviewed candidate; required when review status is passed.",
    )
    parser.add_argument(
        "--max-issues",
        type=int,
        default=10,
        help="Maximum diagnostics included in the compact receipt (default: 10).",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON receipt.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    exit_code, receipt = deliver(
        args.candidate,
        args.target,
        exports=[*args.export, *args.export_page],
        check_rendered_edges=args.check_rendered_edges,
        drawio_cli=args.drawio_cli,
        accepted_warning_fingerprints=args.accept_warning,
        expected_target_sha256=args.expected_target_sha256,
        visual_risk=args.visual_risk,
        visual_review=args.visual_review,
        reviewed_candidate_sha256=args.reviewed_candidate_sha256,
        max_issues=args.max_issues,
    )
    if args.pretty:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
