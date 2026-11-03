"""Desktop worker services. No Tk imports; every call owns its SQLite connection."""

from dataclasses import dataclass,replace,field

from .catalog import CatalogMonitor,CatalogRepository,utc_now
from .classification import catalog_cards,refresh_classification,rows,save_mod_edit,save_effect_edit,add_user_effect,retire_user_effect
from .conflicts import AnalysisDiagnostic,analyze_conflicts
from .extensions import M63_VERSION
from .migrations import upgrade
from .planning import planning_report,selected_packages,set_membership
from .scanner import discover
from .storage import CatalogDatabase,CatalogError,StoragePolicy
from .security import ScopedWorkshopAccess
from .editing import save_details
from .previews import PreviewCache,Image
from .workshop_metadata import cached_metadata,fetch_collection
import time


@dataclass(frozen=True)
class DesktopState:
    cards: tuple
    overlaps: object
    planning: object
    targets: tuple[dict,...]
    components: tuple[dict,...]
    categories: tuple[dict,...]
    status: str
    backup: str | None
    metadata: dict = field(default_factory=dict)
    previews: dict = field(default_factory=dict)
    checked_at: str = ''
    operation_notice: str = ''


def uncertain_state(state):
    """Keep cached evidence visibly historical after a failed refresh; never erase it."""
    packages=tuple(replace(package,included_as="retained",evidence_freshness="retained") if package.included_as=="current" else package for package in state.overlaps.packages)
    by_id={package.package_id:package for package in packages}
    retained=tuple(replace(pair,package_a=by_id[pair.package_a.package_id],package_b=by_id[pair.package_b.package_id],evidence_freshness="retained")
        for pair in (*state.overlaps.current_findings,*state.overlaps.retained_findings))
    coverage=state.overlaps.coverage
    coverage=replace(coverage,complete=False,current_eligible_packages=0,current_asset_entries=0,
        uncertain_active_packages=coverage.active_packages,retained_included_packages=sum(package.included_as=="retained" for package in packages),
        retained_asset_entries=coverage.current_asset_entries+coverage.retained_asset_entries,live_verification="refresh_failed",
        diagnostics=coverage.diagnostics+(AnalysisDiagnostic("REFRESH_FAILED","Only retained last-known evidence is available until refresh succeeds."),))
    overlaps=replace(state.overlaps,packages=packages,coverage=coverage,current_findings=(),retained_findings=retained)
    cards=tuple(replace(card,index_status="stale" if card.index_status=="current" else card.index_status,review_status="Stale / Needs Review",
        effects=tuple(replace(effect,review_status="Stale / Needs Review") for effect in card.effects)) for card in state.cards)
    return replace(state,cards=cards,overlaps=overlaps,planning=planning_report(overlaps,state.planning.selected_ids),status="Last-known data only; refresh failed. Retry Scan / Refresh.")


class DesktopBackend:
    def __init__(self, root, *, test_directory=None, settle_seconds=2.0):
        self.root=root;self.test_directory=test_directory;self.settle_seconds=settle_seconds
        self.preview_cache=PreviewCache()

    def _policy(self, access, *, create=False):
        return StoragePolicy.isolated_test(self.test_directory,access) if self.test_directory else StoragePolicy.production(access,create=create)

    def load(self, *, scan=False, action=None, progress=None):
        progress=progress or (lambda message:None)
        progress('Checking your game folder…')
        access=ScopedWorkshopAccess(self.root)
        policy=self._policy(access,create=scan)
        if not policy.database.is_file() and not scan:
            raise CatalogError("No saved catalog. Choose Scan / Refresh to build it safely.")
        with CatalogDatabase(policy) as database:
            migration=upgrade(database,target_version=M63_VERSION)
            repository=CatalogRepository(database,access)
            if scan:
                progress('Checking local Workshop changes and updating your collection…')
                monitor=CatalogMonitor(repository,settle_seconds=self.settle_seconds)
                monitor.poll();time.sleep(self.settle_seconds);monitor.poll()
            notice=''
            if action and action[0]=='steam':
                progress('Fetching public Steam titles and tags… Your corrections are kept.')
                observed=discover(access)
                fetched=fetch_collection(database,repository.installation_id,{package.workshop_id for package in observed.packages if package.workshop_id})
                notice=f"Steam info: {fetched['ok']} updated, {fetched['failed']} unavailable, {fetched['cached']} cached."
            elif action:
                kind,args=action
                functions={"mod":save_mod_edit,"effect":save_effect_edit,"details":save_details,"add_effect":add_user_effect,"retire_effect":retire_user_effect,"selection":set_membership}
                functions[kind](database,repository.installation_id,**args)
            progress('Reviewing changed resources…')
            refresh_classification(database,repository.installation_id)
            # Fresh metadata guards prevent saved-current rows from masquerading as
            # current files. This observation never confirms/persists a removal.
            for attempt in range(2):
                before=database.connection.execute("SELECT catalog_generation FROM installations WHERE installation_id=?",(repository.installation_id,)).fetchone()[0]
                observation=discover(access)
                cards=catalog_cards(database.connection,repository.installation_id)
                overlaps=analyze_conflicts(database.connection,repository.installation_id,include_retained=True,observation=observation)
                selected=selected_packages(database.connection,repository.installation_id)
                after=database.connection.execute("SELECT catalog_generation FROM installations WHERE installation_id=?",(repository.installation_id,)).fetchone()[0]
                if before==overlaps.coverage.catalog_generation==after:break
            else:raise CatalogError("Catalog changed while loading. Refresh again; saved user inputs were retained.")
            fresh_versions={package.package_id:package.index_generation for package in overlaps.packages if package.included_as=="current"}
            cards=tuple(card if fresh_versions.get(card.package_id)==card.index_generation and card.package_id in fresh_versions else replace(card,index_status="stale" if card.index_status=="current" else card.index_status,review_status="Stale / Needs Review",
                effects=tuple(replace(effect,review_status="Stale / Needs Review") for effect in card.effects)) for card in cards)
            plan=planning_report(overlaps,selected)
            metadata=cached_metadata(database.connection,[card.workshop_id for card in cards if card.workshop_id])
            progress('Loading local preview images…')
            by_filename={package.file.filename:package for package in observation.packages}
            previews={card.package_id:self.preview_cache.load(access,by_filename[card.filename]) for card in cards if card.filename in by_filename}
            status=f"Last checked {utc_now()[:19].replace('T',' ')} UTC. Observed {len(observation.packages)} VPKs; {overlaps.coverage.current_eligible_packages} current indexes; {overlaps.coverage.current_asset_entries} assets. "
            status+=("Metadata matches saved sources; runtime state unverified." if overlaps.coverage.complete else "Coverage incomplete — Scan / Refresh and inspect stale or unknown files.")
            state=DesktopState(cards,overlaps,plan,tuple(dict(row) for row in rows(database.connection,"SELECT * FROM targets ORDER BY label")),
                tuple(dict(row) for row in rows(database.connection,"SELECT * FROM components ORDER BY label")),
                tuple(dict(row) for row in rows(database.connection,"SELECT * FROM categories ORDER BY label")),status,
                migration.backup_path if migration else None,metadata,previews,utc_now(),notice+(' Preview images need Pillow; see README.' if Image is None else ''))
        return state

    def sync_metadata(self, *, cancelled=lambda:False):
        """Separate connection/worker: HTTPS never holds the UI work queue."""
        access=ScopedWorkshopAccess(self.root)
        with CatalogDatabase(self._policy(access)) as database:
            # UI load has already migrated and registered this installation.
            repository=CatalogRepository(database,access)
            observed=discover(access)
            counts=fetch_collection(database,repository.installation_id,
                {p.workshop_id for p in observed.packages if p.workshop_id},cancelled=cancelled)
            metadata=cached_metadata(database.connection,[r[0] for r in database.connection.execute(
                'SELECT DISTINCT workshop_id FROM packages WHERE installation_id=? AND removed_at IS NULL AND workshop_id IS NOT NULL',(repository.installation_id,))])
        return metadata,counts


def filter_cards(cards, text="", category="All", review="All", index="All"):
    needle=text.casefold().strip()
    return tuple(card for card in cards if (not needle or needle in " ".join((card.display_name,card.filename,card.workshop_id or "",card.description,card.summary," ".join(card.categories))).casefold())
        and (category=="All" or category in card.categories)
        and (review=="All" or (review=="Needs Review" and card.review_status!="User confirmed") or card.review_status==review)
        and (index=="All" or card.index_status==index))


def short_summary(card):
    active=sorted((effect for effect in card.effects if effect.active),key=lambda effect:(not bool(effect.target_ids),effect.component_label))
    known=[effect for effect in active if effect.target_ids]
    if known:
        summary="; ".join((", ".join(label+(" ["+identifier+"]" if identifier else "") for label,identifier in zip(effect.target_labels,effect.game_identifiers))+" → "+(effect.replacement or "Unknown")) for effect in known)
        extra=len(active)-len(known)
        return summary+(f"; +{extra} unassigned component(s)" if extra else "")
    return "Unknown target → " + next((effect.replacement for effect in active if effect.replacement),"Unknown replacement")
