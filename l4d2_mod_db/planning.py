"""M6 one-set membership and explicit presentation of unchanged M4 evidence."""

from dataclasses import dataclass
import hashlib
import json

from .catalog import utc_now
from .conflicts import ConflictReport, PairOverlap
from .storage import CatalogError


# Transparent, exact root-path presentation exceptions only. Nothing is removed
# from M4 findings/counts. A similarly named resource in a subdirectory is not exempt.
INFORMATIONAL_PATHS = frozenset((b"addoninfo.txt", b"addonimage.jpg"))


def selected_packages(connection, installation_id):
    return frozenset(row[0] for row in connection.execute("""SELECT m.package_id FROM planning_members m
        JOIN packages p ON p.package_id=m.package_id AND p.installation_id=m.installation_id
        WHERE m.installation_id=? AND p.removed_at IS NULL""", (installation_id,)))


def set_membership(database, installation_id, package_id, selected):
    with database.transaction() as connection:
        package = connection.execute("SELECT package_id FROM packages WHERE package_id=? AND installation_id=? AND removed_at IS NULL", (package_id,installation_id)).fetchone()
        if package is None: raise CatalogError("A removed or differently scoped package cannot be selected.")
        connection.execute("INSERT INTO planning_sets VALUES (?,?) ON CONFLICT(installation_id) DO NOTHING", (installation_id,utc_now()))
        if selected:
            connection.execute("INSERT INTO planning_members VALUES (?,?) ON CONFLICT DO NOTHING", (installation_id,package_id))
        else:
            connection.execute("DELETE FROM planning_members WHERE installation_id=? AND package_id=?", (installation_id,package_id))


@dataclass(frozen=True)
class PlanningFinding:
    pair: PairOverlap
    context: str
    presentation: str
    resource_paths: tuple[bytes, ...]
    informational_paths: tuple[bytes, ...]


@dataclass(frozen=True)
class PlanningReport:
    selected_ids: frozenset[str]
    findings: tuple[PlanningFinding, ...]
    coverage_complete: bool
    uncertain_selected_ids: tuple[str, ...]

    @property
    def counts(self):
        return {context + "_" + presentation: sum(finding.context==context and finding.presentation==presentation for finding in self.findings)
            for context in ("selected", "candidate") for presentation in ("attention", "informational", "retained")}


def planning_report(report: ConflictReport, selected_ids) -> PlanningReport:
    selected = frozenset(selected_ids)
    findings=[]
    for pair in (*report.current_findings,*report.retained_findings):
        left,right=pair.package_a.package_id,pair.package_b.package_id
        if left not in selected and right not in selected: continue
        context="selected" if left in selected and right in selected else "candidate"
        resources=tuple(path for path in pair.canonical_paths if path not in INFORMATIONAL_PATHS)
        informational=tuple(path for path in pair.canonical_paths if path in INFORMATIONAL_PATHS)
        presentation="retained" if pair.evidence_freshness!="current" else "attention" if resources else "informational"
        findings.append(PlanningFinding(pair,context,presentation,resources,informational))
    current_ids={package.package_id for package in report.packages if package.included_as=="current"}
    uncertain=tuple(sorted(selected-current_ids))
    return PlanningReport(selected,tuple(findings),report.coverage.complete and not uncertain,uncertain)


def selected_warning_ids(report):
    """Only selected-selected resource findings can flag the selected list."""
    return frozenset(package.package_id for finding in report.findings if finding.context=='selected' and finding.presentation=='attention'
                     for package in (finding.pair.package_a,finding.pair.package_b))


def review_key(finding):
    pair=finding.pair
    if finding.context!='selected' or pair.evidence_freshness!='current':return None
    versions=sorted((package.package_id,package.index_generation,package.indexed_scan_id,package.parser_version,package.canonicalization_version)
                    for package in (pair.package_a,pair.package_b))
    payload=[versions,sorted(path.hex() for path in pair.canonical_paths)]
    return hashlib.sha256(json.dumps(payload,separators=(',',':')).encode()).hexdigest()


class ReviewSession:
    """Acknowledgement only for this open app session; no SQL/file writes or hiding."""
    def __init__(self):self._reviewed=set()

    def reconcile(self,report):
        self._reviewed.intersection_update(key for finding in report.findings if (key:=review_key(finding)))

    def reviewed(self,finding):return review_key(finding) in self._reviewed

    def toggle(self,finding):
        key=review_key(finding)
        if key is None:raise ValueError('Only current overlaps between selected mods can be reviewed. Refresh stale evidence first.')
        if key in self._reviewed:self._reviewed.remove(key)
        else:self._reviewed.add(key)
