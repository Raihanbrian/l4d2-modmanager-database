"""Presentation over unchanged byte-safe M4 evidence; never crash prediction."""
from dataclasses import dataclass
from .planning import INFORMATIONAL_PATHS
from .references import component_for,reference_match


@dataclass(frozen=True)
class RuntimeIncident:
    kind: str
    source: str
    note: str

    def __post_init__(self):
        if self.kind not in ('crash','visual','join','consistency','other') or not self.source.strip() or not self.note.strip():
            raise ValueError('An explicit incident kind, source and observation are required.')


@dataclass(frozen=True)
class ConflictExplanation:
    category: str
    reason: str
    roles: tuple[str,...]
    freshness: str
    crash_evidence: str = 'Not verified'
    limits: str = 'Payload equality, model internals, script execution, dependencies, engine limits and multiplayer compatibility: not evaluated.'


def explain_overlap(finding, incident=None):
    paths=finding.pair.canonical_paths
    resources=tuple(p for p in paths if p not in INFORMATIONAL_PATHS)
    roles=tuple(sorted({component_for(p) for p in resources}))
    models={match[0] for p in resources if component_for(p)=='model' and (match:=reference_match(p))}
    if not resources:
        category='Informational';reason='Common addon metadata only; this alone does not establish gameplay incompatibility.'
    elif 'script' in roles:
        category='Needs investigation';reason='Shared script/config paths; one version may take priority and change intended behavior.'
        if models:reason+=' Original model resources also overlap.'
    elif models:
        category='Replacement competition';reason='Both provide the same original model resource ('+', '.join(sorted(models))+'). One version may take priority.'
    elif 'model' in roles:
        category='Needs investigation';reason='Shared model/dependency paths; content and animation compatibility are not evaluated.'
    elif set(roles)<={'material','ui','sound'}:
        category='Shared resources';reason='Shared '+', '.join({'material':'material/texture','ui':'UI/localization','sound':'sound'}[r] for r in roles)+' files, even if original targets differ. One version may take priority.'
    else:
        category='Needs investigation';reason='Exact paths overlap; the resource role or gameplay impact is unknown.'
    if finding.pair.evidence_freshness!='current':reason='Retained evidence — refresh first. '+reason
    crash='Not verified'
    if incident:
        category='Reported runtime problem'
        reason+=f' Explicit {incident.kind} report: {incident.note} (Source: {incident.source}). Causation is not established.'
        crash='Reported, not independently verified' if incident.kind=='crash' else 'Not verified; reported issue is '+incident.kind
    return ConflictExplanation(category,reason,roles,finding.pair.evidence_freshness,crash)


NO_OVERLAPS='No current selected-pair resource overlaps found. This does not prove gameplay or multiplayer compatibility; semantic/dependency issues may have no shared paths.'
