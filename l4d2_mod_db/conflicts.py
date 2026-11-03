"""M4 derived path-overlap evidence. No game I/O, SQL mutation or classification."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from itertools import combinations
import json
import sqlite3

from .catalog import SIGNATURE_FIELDS, _relative, _signature, _uuid
from .schema import CANONICALIZATION_VERSION, PARSER_VERSION
from .scanner import DiscoveryReport, infer_workshop_id
from .security import DiscoveryStatus
from .storage import CatalogError
from .vpk import canonicalize_virtual_path


class ConflictAnalysisError(CatalogError):
    pass


@dataclass(frozen=True, slots=True)
class AnalysisLimits:
    max_asset_entries: int = 1_000_000
    max_pair_path_matches: int = 1_000_000

    def __post_init__(self):
        if min(self.max_asset_entries, self.max_pair_path_matches) <= 0:
            raise ValueError("Analysis limits must be positive.")


@dataclass(frozen=True, slots=True)
class AnalysisDiagnostic:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class PackageEvidence:
    package_id: str
    workshop_id: str | None
    filename: str
    relative_path: str
    presence_status: str
    index_status: str
    index_generation: int | None
    indexed_scan_id: int | None
    indexed_at: str | None
    parser_version: str | None
    canonicalization_version: str | None
    asset_entries: int
    evidence_freshness: str
    included_as: str
    source_diagnostic_code: str | None
    reasons: tuple[AnalysisDiagnostic, ...]


def path_value(raw: bytes) -> dict:
    """Hex is authoritative; backslash escapes display undecodable bytes safely."""
    return {"canonical_path_hex": raw.hex(), "display": raw.decode("utf-8", "backslashreplace")}


@dataclass(frozen=True, slots=True)
class PairOverlap:
    package_a: PackageEvidence
    package_b: PackageEvidence
    canonical_paths: tuple[bytes, ...]
    evidence_freshness: str

    @property
    def overlapping_path_count(self) -> int:
        return len(self.canonical_paths)

    def to_dict(self) -> dict:
        return dict(package_a=asdict(self.package_a), package_b=asdict(self.package_b),
            overlapping_path_count=self.overlapping_path_count, evidence_freshness=self.evidence_freshness,
            paths=[path_value(path) for path in self.canonical_paths])


@dataclass(frozen=True, slots=True)
class AnalysisCoverage:
    scope: str
    catalog_generation: int
    committed_scan_id: int | None
    committed_at: str | None
    directory_status: str | None
    active_packages: int
    current_eligible_packages: int
    retained_included_packages: int
    uncertain_active_packages: int
    excluded_packages: int
    removed_packages: int
    observed_packages: int | None
    uncataloged_observed_packages: int
    current_asset_entries: int
    retained_asset_entries: int
    complete: bool
    live_verification: str
    diagnostics: tuple[AnalysisDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class ConflictReport:
    coverage: AnalysisCoverage
    packages: tuple[PackageEvidence, ...]
    current_findings: tuple[PairOverlap, ...]
    retained_findings: tuple[PairOverlap, ...]
    uncataloged_relative_paths: tuple[str, ...] = ()

    @property
    def counts(self) -> dict:
        current_paths = {path for pair in self.current_findings for path in pair.canonical_paths}
        retained_paths = {path for pair in self.retained_findings for path in pair.canonical_paths}
        return dict(current_package_pairs=len(self.current_findings), current_unique_paths=len(current_paths),
            retained_package_pairs=len(self.retained_findings), retained_unique_paths=len(retained_paths),
            combined_unique_paths=len(current_paths | retained_paths),
            combined_package_pairs=len(self.current_findings) + len(self.retained_findings))

    def to_dict(self) -> dict:
        return dict(report_version=1, meaning="Confirmed canonical-path overlap; potential resource conflict, not a proven gameplay problem.",
            canonicalization_version=CANONICALIZATION_VERSION, coverage=asdict(self.coverage), counts=self.counts,
            packages=[asdict(package) for package in self.packages],
            uncataloged_relative_paths=list(self.uncataloged_relative_paths),
            current_findings=[finding.to_dict() for finding in self.current_findings],
            retained_findings=[finding.to_dict() for finding in self.retained_findings])


def _reason(code, message):
    return AnalysisDiagnostic(code, message)


def _package(row, include_retained: bool) -> PackageEvidence:
    reasons = []
    has_index = row["index_generation"] is not None
    usable = has_index
    if not has_index:
        reasons.append(_reason("NO_VALID_INDEX", "No last valid index is available."))
    try:
        _uuid(row["package_id"])
        _relative(row["relative_path"])
        if row["relative_path_key"] != row["relative_path"].casefold() or row["workshop_id"] != infer_workshop_id(row["relative_path"].rsplit("/", 1)[-1]):
            raise CatalogError("Invalid saved package identity/location metadata.")
    except (CatalogError, ValueError, TypeError):
        usable = False
        reasons.append(_reason("INVALID_PACKAGE_METADATA", "Saved UUID, relative location, comparison key or inferred ID is inconsistent; package excluded."))
    if has_index and row["canonicalization_version"] != CANONICALIZATION_VERSION:
        usable = False
        reasons.append(_reason("INCOMPATIBLE_CANONICALIZATION", "Stored path policy is incompatible; reindex with the supported policy."))
    if has_index and row["parser_version"] != PARSER_VERSION:
        usable = False
        reasons.append(_reason("INCOMPATIBLE_PARSER", "Stored parser contract is unsupported; reindex before comparison."))
    if row["indexed_scan_id"] is not None and row["indexed_outcome"] != "committed":
        usable = False
        reasons.append(_reason("UNCONFIRMED_INDEX", "The retained index has no committed producing scan."))
    if row["state_outcome"] != "committed":
        usable = False
        reasons.append(_reason("UNCONFIRMED_STATE", "The package state has no committed producing scan."))
    removed = row["removed_at"] is not None or row["presence_status"] == "removed"
    if removed:
        reasons.append(_reason("CONFIRMED_REMOVAL", "Excluded from installed analysis; removal does not prove unsubscription."))
    if not removed and row["presence_status"] != "present":
        reasons.append(_reason("PRESENCE_UNCERTAIN", "Package presence is not currently confirmed in the saved catalog."))
    if not removed and row["index_status"] != "current":
        reasons.append(_reason("INDEX_NOT_CURRENT", "Pending, corrupt or unavailable observations cannot support current findings."))
    signature_equal = False
    if usable:
        try:
            signature_equal = _signature(row, "observed_") == _signature(row, "source_")
        except (CatalogError, ValueError, TypeError):
            usable = False
            reasons.append(_reason("INVALID_SOURCE_SIGNATURE", "Saved source observation metadata is invalid."))
        if usable and not signature_equal:
            reasons.append(_reason("SOURCE_SIGNATURE_MISMATCH", "Last valid source differs from the latest observed file."))
    current = usable and not removed and row["presence_status"] == "present" and row["index_status"] == "current" and signature_equal
    freshness = "removed" if removed else "current" if current else "retained" if usable else "unusable"
    role = "current" if current else "retained" if usable and not removed and include_retained else "excluded"
    return PackageEvidence(row["package_id"], row["workshop_id"], row["relative_path"].rsplit("/", 1)[-1],
        row["relative_path"], row["presence_status"], row["index_status"], row["index_generation"], row["indexed_scan_id"],
        row["indexed_at"], row["parser_version"], row["canonicalization_version"], row["asset_entries"], freshness, role,
        row["source_diagnostic_code"], tuple(reasons))


def _valid_path(row) -> bool:
    original, canonical = row["original_path_bytes"], row["canonical_path_bytes"]
    if not isinstance(original, bytes) or not isinstance(canonical, bytes):
        return False
    try:
        expected = canonicalize_virtual_path(original.decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape")
        try:
            original.decode("utf-8")
            valid_utf8 = 1
        except UnicodeDecodeError:
            valid_utf8 = 0
        return expected == canonical and row["utf8_valid"] == valid_utf8
    except (ValueError, UnicodeError):
        return False


def analyze_conflicts(connection: sqlite3.Connection, installation_id: str, *, include_retained: bool = False,
                      observation: DiscoveryReport | None = None,
                      limits: AnalysisLimits = AnalysisLimits()) -> ConflictReport:
    """Analyze one coherent saved installation snapshot, without mutation.

    Caller supplies an idle connection. Production uses CatalogReader. Results
    are deterministic; current refers to saved observations, not live game state.
    Removed packages are always excluded, even when retained evidence is requested.
    """
    if connection.in_transaction:
        raise ConflictAnalysisError("Analysis requires an idle connection for its own read snapshot.")
    cursor = connection.cursor()
    cursor.row_factory = sqlite3.Row
    connection.execute("BEGIN")
    try:
        installation = cursor.execute("SELECT catalog_generation FROM installations WHERE installation_id=?", (installation_id,)).fetchone()
        if installation is None:
            raise ConflictAnalysisError("Unknown installation scope; no analysis performed.")
        generation = installation["catalog_generation"]
        committed = cursor.execute("SELECT * FROM scan_runs WHERE installation_id=? AND outcome='committed' AND committed_generation=? ORDER BY scan_id DESC LIMIT 1", (installation_id, generation)).fetchone()
        diagnostics = []
        if committed is None:
            diagnostics.append(_reason("NO_COMMITTED_SNAPSHOT", "Catalog has no confirmed committed scan for this generation."))
        elif committed["directory_status"] != "complete":
            diagnostics.append(_reason("INCOMPLETE_DIRECTORY", "Latest committed enumeration was not complete; unknown packages may be absent from this catalog."))
        newer = cursor.execute("SELECT outcome FROM scan_runs WHERE installation_id=? AND scan_id>? AND outcome IN ('started','failed','interrupted','superseded') ORDER BY scan_id", (installation_id, committed["scan_id"] if committed else 0)).fetchall()
        if newer:
            diagnostics.append(_reason("NEWER_UNPUBLISHED_ATTEMPT", "A newer scan failed, was interrupted, is unconfirmed or was superseded; saved evidence does not establish complete current coverage."))
        sources = ",".join("ix.source_" + field for field in SIGNATURE_FIELDS)
        rows = cursor.execute(f"""SELECT p.*, ix.generation AS index_generation, ix.indexed_scan_id,
            ix.parser_version, ix.canonicalization_version, {sources}, r.finished_at AS indexed_at,
            r.outcome AS indexed_outcome, s.outcome AS state_outcome,
            (SELECT count(*) FROM assets a WHERE a.package_id=p.package_id) AS asset_entries,
            (SELECT code FROM scan_issues si WHERE si.package_id=p.package_id AND si.scan_id=p.state_scan_id
             ORDER BY issue_id DESC LIMIT 1) AS source_diagnostic_code
            FROM packages p LEFT JOIN package_indexes ix ON ix.package_id=p.package_id
            LEFT JOIN scan_runs r ON r.scan_id=ix.indexed_scan_id
            LEFT JOIN scan_runs s ON s.scan_id=p.state_scan_id
            WHERE p.installation_id=? ORDER BY p.package_id""", (installation_id,)).fetchall()
        packages = [_package(row, include_retained) for row in rows]
        uncataloged = ()
        if observation is not None:
            observed = {package.file.relative_path.casefold(): package.file for package in observation.packages}
            active_keys = {row["relative_path_key"] for row in rows if row["removed_at"] is None}
            uncataloged = tuple(sorted(file.relative_path for key, file in observed.items() if key not in active_keys))
            if observation.status != DiscoveryStatus.COMPLETE:
                diagnostics.append(_reason("INCOMPLETE_LIVE_OBSERVATION", "Fresh metadata discovery is incomplete; no removal or complete-coverage claim is inferred."))
            if uncataloged:
                diagnostics.append(_reason("UNCATALOGED_OBSERVED_PACKAGES", "Freshly discovered files lack an active catalog lineage/index; reconcile with M3 before complete analysis."))
            for number, (row, package) in enumerate(zip(rows, packages)):
                if package.included_as != "current":
                    continue
                file = observed.get(row["relative_path_key"])
                if file is None or file.signature != _signature(row, "source_"):
                    packages[number] = replace(package, included_as="retained" if include_retained else "excluded",
                        evidence_freshness="retained", reasons=package.reasons + (_reason(
                            "LIVE_SOURCE_MISMATCH" if file else "LIVE_ABSENCE_UNCONFIRMED",
                            "Fresh metadata does not confirm the indexed source; prior evidence retained without changing catalog state."),))
        if sum(package.asset_entries for package in packages if package.included_as != "excluded") > limits.max_asset_entries:
            raise ConflictAnalysisError("ANALYSIS_LIMIT: asset budget exceeded; no complete overlap result was produced.")
        owners = defaultdict(list)
        # One indexed child query per candidate avoids SQL asset x audit joins.
        for number, package in enumerate(packages):
            if package.included_as == "excluded":
                continue
            assets = cursor.execute("SELECT original_path_bytes,canonical_path_bytes,utf8_valid FROM assets WHERE package_id=? ORDER BY canonical_path_bytes", (package.package_id,)).fetchall()
            if not all(_valid_path(asset) for asset in assets):
                packages[number] = replace(package, included_as="excluded", evidence_freshness="unusable",
                    reasons=package.reasons + (_reason("INVALID_PATH_EVIDENCE", "Stored path bytes/encoding flag do not match the supported canonicalization policy; entire index excluded."),))
                continue
            for asset in assets:
                owners[asset["canonical_path_bytes"]].append(package.package_id)
        identities = {package.package_id: package for package in packages}
        pair_paths = defaultdict(list)
        matches = 0
        for path in sorted(owners):
            members = owners[path]
            matches += len(members) * (len(members) - 1) // 2
            if matches > limits.max_pair_path_matches:
                raise ConflictAnalysisError("ANALYSIS_LIMIT: pair/path budget exceeded; no complete overlap result was produced.")
            for pair in combinations(members, 2):
                pair_paths[pair].append(path)
        current, retained = [], []
        for (left, right), paths in sorted(pair_paths.items()):
            a, b = identities[left], identities[right]
            freshness = "current" if a.included_as == b.included_as == "current" else "retained"
            finding = PairOverlap(a, b, tuple(paths), freshness)
            (current if freshness == "current" else retained).append(finding)
        active = [package for package in packages if package.presence_status != "removed"]
        eligible = [package for package in active if package.included_as == "current"]
        stale = [package for package in active if package.included_as == "retained"]
        uncertain = len(active) - len(eligible)
        if uncertain:
            diagnostics.append(_reason("INCOMPLETE_PACKAGE_COVERAGE", "Some active catalog packages lack reliable current evidence; missing overlaps cannot be ruled out."))
        coverage = AnalysisCoverage("saved_catalog", generation, committed["scan_id"] if committed else None,
            committed["finished_at"] if committed else None, committed["directory_status"] if committed else None,
            len(active), len(eligible), len(stale), uncertain, sum(package.included_as == "excluded" for package in packages),
            len(packages) - len(active), len(observation.packages) if observation is not None else None, len(uncataloged),
            sum(package.asset_entries for package in eligible), sum(package.asset_entries for package in stale),
            not diagnostics, "metadata_observation" if observation is not None else "not_performed", tuple(diagnostics))
        return ConflictReport(coverage, tuple(packages), tuple(current), tuple(retained), uncataloged)
    finally:
        cursor.close()
        connection.rollback()  # Release only this read transaction, including on cancellation.


def format_conflicts(report: ConflictReport) -> str:
    coverage, counts = report.coverage, report.counts
    lines = ["M4 - Confirmed path overlaps / potential resource conflicts",
        "A matching path is not proof of a gameplay problem, crash or incompatible modification.",
        f"Saved catalog generation {coverage.catalog_generation}; committed at {json.dumps(coverage.committed_at or 'Unknown', ensure_ascii=True)}; live filesystem verification: {coverage.live_verification} (no runtime/payload verification).",
        f"Coverage: {'complete for saved catalog' if coverage.complete else 'INCOMPLETE'}; current eligible {coverage.current_eligible_packages}/{coverage.active_packages}; uncertain active {coverage.uncertain_active_packages}; removed excluded {coverage.removed_packages}.",
        f"Current evidence: {counts['current_package_pairs']} unique package pair(s), {counts['current_unique_paths']} unique overlapping path(s), {coverage.current_asset_entries} asset entries considered."]
    if not report.current_findings:
        lines.append("No path overlaps found in eligible saved-current data. This does not establish that the collection is conflict-free.")
    for label, findings in (("CURRENT (saved observations)", report.current_findings), ("RETAINED / STALE (not current)", report.retained_findings)):
        for pair in findings:
            lines.append(f"{label}: {pair.overlapping_path_count} shared path(s)")
            for package in (pair.package_a, pair.package_b):
                lines.append(f"  {package.package_id} | inferred Workshop {package.workshop_id or 'Unknown'} | {json.dumps(package.filename, ensure_ascii=True)} | index generation {package.index_generation} | {package.evidence_freshness}")
            for path in pair.canonical_paths:
                value = path_value(path)
                lines.append(f"    {json.dumps(value['display'], ensure_ascii=True)} [hex {value['canonical_path_hex']}]")
    lines.append(f"Retained evidence included: {coverage.retained_included_packages} package(s), {counts['retained_package_pairs']} pair(s), {counts['retained_unique_paths']} shared path(s); never counted as current.")
    for package in report.packages:
        if package.included_as != "current":
            reasons = "; ".join(reason.code for reason in package.reasons)
            lines.append(f"{package.included_as.upper()}: {package.package_id} {json.dumps(package.filename, ensure_ascii=True)} [{reasons}]")
    for diagnostic in coverage.diagnostics:
        lines.append(f"[{diagnostic.code}] {diagnostic.message}")
    return "\n".join(lines)
