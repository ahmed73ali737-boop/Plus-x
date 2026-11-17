"""Self-service certificate persistence (owner-isolated library, request links,
participant requests, the leased render/export queues, delivery and limits).

Every query is filtered by the owning account; the database owner-chain
triggers remain as defence in depth.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timezone

from sqlalchemy import and_, delete, exists, func, insert, literal, or_, select, text as sql_text, update
from sqlalchemy.exc import IntegrityError

from app.domain.values import utc_timestamp
from app.infrastructure.persistence.self_certificate_tables import (
    assets,
    browser_sessions,
    certificates,
    export_snapshot_rows,
    exports,
    jobs,
    links,
    model_operations,
    models,
    rate_buckets,
    requests,
    revisions,
)
from app.infrastructure.persistence.tables import assignments, event_participations, memberships, organizations, sites, users

LIBRARY_MANAGER_ROLES = ('owner', 'admin')
RUNNABLE_EXPORT = 'pending'


def _one(tx, query):
    row = tx.execute(query).mappings().first()
    return dict(row) if row else None


def _all(tx, query):
    return [dict(row) for row in tx.execute(query).mappings().all()]


def _organization_management(user_id):
    return (select(memberships.c.organization_id)
            .select_from(memberships.join(organizations, organizations.c.id == memberships.c.organization_id))
            .where(memberships.c.user_id == user_id, memberships.c.status == 'active',
                   memberships.c.role.in_(LIBRARY_MANAGER_ROLES), organizations.c.status == 'active'))


class SqlSelfCertificateRepository:
    # Clock and locks ------------------------------------------------------------
    def lease_now(self, tx):
        """One server clock for leases across processes (PostgreSQL clock_timestamp)."""
        if tx.dialect.name == 'postgresql':
            value = tx.execute(select(func.clock_timestamp())).scalar_one()
            return value.astimezone(timezone.utc).isoformat(timespec='microseconds')
        return utc_timestamp()

    def serialize_operation(self, tx, key: int):
        """Serialize one owner+operation key across processes (PostgreSQL only)."""
        if tx.dialect.name == 'postgresql':
            tx.execute(sql_text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})

    def lock_authority(self, tx, owner_id, event_id):
        """Stable-order row locks on everything that grants the owner this event."""
        tx.execute(select(users.c.id).where(users.c.id == owner_id).with_for_update()).all()
        organization_ids = tx.execute(select(memberships.c.organization_id).where(memberships.c.user_id == owner_id)
                                      .order_by(memberships.c.organization_id).with_for_update()).scalars().all()
        if organization_ids:
            tx.execute(select(organizations.c.id).where(organizations.c.id.in_(organization_ids))
                       .order_by(organizations.c.id).with_for_update()).all()
            tx.execute(select(event_participations.c.id).where(
                event_participations.c.event_id == event_id,
                event_participations.c.organization_id.in_(organization_ids))
                .order_by(event_participations.c.id).with_for_update()).all()
        tx.execute(select(assignments.c.id).where(assignments.c.user_id == owner_id, assignments.c.site_id == event_id)
                   .order_by(assignments.c.id).with_for_update()).all()

    # Library authority ------------------------------------------------------
    def user(self, tx, user_id):
        return _one(tx, select(users).where(users.c.id == user_id))

    def manages_an_organization(self, tx, user_id):
        return tx.execute(_organization_management(user_id).limit(1)).first() is not None

    def event_manager_assignments(self, tx, user_id, event_id=None):
        query = (select(assignments).join(sites, sites.c.id == assignments.c.site_id)
                 .where(assignments.c.user_id == user_id, assignments.c.role == 'event_manager', sites.c.kind == 'event'))
        if event_id is not None:
            query = query.where(assignments.c.site_id == event_id)
        return _all(tx, query)

    def events(self, tx, event_ids=None):
        query = select(sites).where(sites.c.kind == 'event')
        if event_ids is not None:
            query = query.where(sites.c.id.in_(event_ids))
        return [dict(row) for row in tx.execute(query).mappings()]

    def managed_participation_event_ids(self, tx, user_id):
        query = select(event_participations.c.event_id).where(
            event_participations.c.organization_id.in_(_organization_management(user_id)),
            event_participations.c.status == 'active')
        return set(tx.execute(query).scalars())

    def event(self, tx, event_id):
        return _one(tx, select(sites).where(sites.c.id == event_id, sites.c.kind == 'event'))

    def manages_event_participation(self, tx, user_id, event_id):
        query = select(event_participations.c.id).where(
            event_participations.c.event_id == event_id, event_participations.c.status == 'active',
            event_participations.c.organization_id.in_(_organization_management(user_id))).limit(1)
        return tx.execute(query).first() is not None

    # Models, revisions, assets ------------------------------------------------
    def model(self, tx, owner_id, model_id, *, for_update=False):
        query = select(models).where(models.c.id == model_id, models.c.owner_account_id == owner_id)
        if for_update:
            query = query.with_for_update()
        return _one(tx, query)

    def models_page(self, tx, owner_id, search, offset, limit):
        scope = models.c.owner_account_id == owner_id
        if search:
            scope = scope & models.c.name.icontains(search, autoescape=True)
        joined = revisions, (models.c.current_revision_id == revisions.c.id) & (models.c.owner_account_id == revisions.c.owner_account_id)
        query = (select(models, revisions.c.background_asset_id).join(*joined).where(scope)
                 .order_by(models.c.updated_at.desc(), models.c.id).offset(offset).limit(limit))
        total = tx.execute(select(func.count()).select_from(models).where(scope)).scalar_one()
        return [dict(row) for row in tx.execute(query).mappings()], total

    def asset(self, tx, owner_id, asset_id, kind=None):
        query = select(assets).where(assets.c.id == asset_id, assets.c.owner_account_id == owner_id)
        if kind is not None:
            query = query.where(assets.c.kind == kind)
        return _one(tx, query)

    def asset_by_id(self, tx, asset_id):
        return dict(tx.execute(select(assets).where(assets.c.id == asset_id)).mappings().one())

    def add_asset(self, tx, row):
        tx.execute(insert(assets).values(**row))

    def revision(self, tx, owner_id, revision_id):
        return _one(tx, select(revisions).where(revisions.c.id == revision_id, revisions.c.owner_account_id == owner_id))

    def model_operation(self, tx, owner_id, idempotency_key):
        return _one(tx, select(model_operations).where(model_operations.c.owner_account_id == owner_id,
                                                       model_operations.c.idempotency_key == idempotency_key))

    def add_model(self, tx, row):
        tx.execute(insert(models).values(**row))

    def add_revision(self, tx, row):
        tx.execute(insert(revisions).values(**row))

    def advance_model(self, tx, model_id, owner_id, expected_version, values):
        result = tx.execute(update(models).where(models.c.id == model_id, models.c.owner_account_id == owner_id,
                                                 models.c.row_version == expected_version).values(**values))
        return result.rowcount == 1

    def add_model_operation(self, tx, row):
        tx.execute(insert(model_operations).values(**row))

    def delete_model(self, tx, model_id, owner_id, row_version):
        """FK SET NULL detaches revisions; operational copies and assets are retained."""
        result = tx.execute(delete(models).where(models.c.id == model_id, models.c.owner_account_id == owner_id,
                                                 models.c.row_version == row_version))
        return result.rowcount == 1

    # Request links --------------------------------------------------------------
    def link_by_idempotency(self, tx, owner_id, key):
        return _one(tx, select(links).where(links.c.owner_account_id == owner_id, links.c.idempotency_key == key))

    def add_link(self, tx, row):
        tx.execute(insert(links).values(**row))

    def links_page(self, tx, owner_id, offset, limit):
        scope = links.c.owner_account_id == owner_id
        query = select(links).where(scope).order_by(links.c.created_at.desc(), links.c.id).offset(offset).limit(limit)
        total = tx.execute(select(func.count()).select_from(links).where(scope)).scalar_one()
        return [dict(row) for row in tx.execute(query).mappings()], total

    def link(self, tx, owner_id, link_id, *, for_update=False):
        query = select(links).where(links.c.id == link_id, links.c.owner_account_id == owner_id)
        if for_update:
            query = query.with_for_update()
        return _one(tx, query)

    def link_of(self, tx, link_id, owner_id, revision_id=None):
        query = select(links).where(links.c.id == link_id, links.c.owner_account_id == owner_id)
        if revision_id is not None:
            query = query.where(links.c.revision_id == revision_id)
        return _one(tx, query)

    def set_link_state(self, tx, link_id, expected_version, values):
        tx.execute(update(links).where(links.c.id == link_id, links.c.row_version == expected_version).values(**values))

    def public_link(self, tx, public_id, key_version, *, for_update=False):
        query = select(links).where(links.c.public_id == public_id, links.c.key_version == key_version)
        if for_update:
            query = query.with_for_update()
        return _one(tx, query)

    def has_history(self, tx, owner_id=None):
        """Any link or certificate (system-wide), or any request/link of one owner."""
        if owner_id is None:
            return bool(tx.execute(select(links.c.id).limit(1)).first()
                        or tx.execute(select(certificates.c.id).limit(1)).first())
        return bool(tx.execute(select(requests.c.id).where(requests.c.owner_account_id == owner_id).limit(1)).first()
                    or tx.execute(select(links.c.id).where(links.c.owner_account_id == owner_id).limit(1)).first())

    def owner_has_links(self, tx, owner_id):
        return tx.execute(select(links.c.id).where(links.c.owner_account_id == owner_id).limit(1)).first() is not None

    # Browser sessions and participant requests --------------------------------
    def browser_session(self, tx, session_id):
        return _one(tx, select(browser_sessions).where(browser_sessions.c.id == session_id))

    def ensure_browser_session(self, tx, row):
        if tx.dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert as upsert
        else:
            from sqlalchemy.dialects.sqlite import insert as upsert
        tx.execute(upsert(browser_sessions).values(**row).on_conflict_do_nothing(index_elements=[browser_sessions.c.id]))
        return dict(tx.execute(select(browser_sessions).where(browser_sessions.c.id == row['id'])).mappings().one())

    def touch_browser_session(self, tx, session_id, at):
        tx.execute(update(browser_sessions).where(browser_sessions.c.id == session_id).values(last_seen_at=at))

    def request_for_browser(self, tx, link_id, browser_id):
        return _one(tx, select(requests).where(requests.c.link_id == link_id, requests.c.browser_session_id == browser_id))

    def certificate_for_request(self, tx, request_row):
        return _one(tx, select(certificates).where(certificates.c.request_id == request_row['id'],
                                                   certificates.c.owner_account_id == request_row['owner_account_id'],
                                                   certificates.c.link_id == request_row['link_id']))

    def add_request_with_job(self, tx, request_row, job_row):
        """A participant request and its render job commit together."""
        tx.execute(insert(requests).values(**request_row))
        tx.execute(insert(jobs).values(**job_row))

    def request(self, tx, request_id):
        return dict(tx.execute(select(requests).where(requests.c.id == request_id)).mappings().one())

    def owned_request(self, tx, owner_id, request_id, *, for_update=False):
        query = select(requests).where(requests.c.id == request_id, requests.c.owner_account_id == owner_id)
        if for_update:
            query = query.with_for_update()
        return _one(tx, query)

    def job_for_request(self, tx, request_id, *, for_update=False):
        query = select(jobs).where(jobs.c.request_id == request_id)
        if for_update:
            query = query.with_for_update()
        return dict(tx.execute(query).mappings().one())

    def requeue(self, tx, job_id, request_id, at):
        tx.execute(update(jobs).where(jobs.c.id == job_id).values(status='pending', attempts=0, available_at=at,
                                                                   last_error_code=None))
        tx.execute(update(requests).where(requests.c.id == request_id).values(status='registered', error_code=None))

    def request_history(self, tx, owner_id, search, status, event_id, offset, limit):
        scope = [requests.c.owner_account_id == owner_id, links.c.owner_account_id == owner_id]
        if search:
            scope.append(or_(requests.c.participant_name_original.icontains(search, autoescape=True),
                             requests.c.phone_original.icontains(search, autoescape=True),
                             links.c.model_name_snapshot.icontains(search, autoescape=True),
                             links.c.event_name_snapshot.icontains(search, autoescape=True)))
        if status:
            scope.append(requests.c.status == status)
        if event_id:
            scope.append(links.c.event_id == event_id)
        joined = requests.join(links, and_(links.c.id == requests.c.link_id,
                                           links.c.owner_account_id == requests.c.owner_account_id))
        issued = and_(certificates.c.request_id == requests.c.id,
                      certificates.c.owner_account_id == requests.c.owner_account_id,
                      certificates.c.link_id == requests.c.link_id)
        query = (select(requests.c.id, requests.c.participant_name_original, requests.c.phone_original,
                        requests.c.status, requests.c.submitted_at_utc, requests.c.layout, requests.c.error_code,
                        links.c.model_name_snapshot, links.c.event_name_snapshot,
                        certificates.c.id.label('certificate_id'),
                        certificates.c.key_version.label('certificate_key_version'))
                 .select_from(joined.outerjoin(certificates, issued)).where(*scope)
                 .order_by(requests.c.submitted_at_utc.desc(), requests.c.id).offset(offset).limit(limit))
        rows = [dict(row) for row in tx.execute(query).mappings()]
        total = tx.execute(select(func.count()).select_from(joined).where(*scope)).scalar_one()
        return rows, total

    # Render job queue -----------------------------------------------------------
    def _runnable(self, at):
        return or_(and_(jobs.c.status.in_(('pending', 'retry_wait')), jobs.c.available_at <= at),
                   and_(jobs.c.status == 'leased', jobs.c.lease_until < at))

    def fail_exhausted_jobs(self, tx, at):
        exhausted = tx.execute(select(jobs.c.id, jobs.c.request_id).where(jobs.c.attempts >= 3, self._runnable(at))
                               .order_by(jobs.c.available_at, jobs.c.id).limit(100)
                               .with_for_update(skip_locked=True)).all()
        for item in exhausted:
            tx.execute(update(jobs).where(jobs.c.id == item.id).values(status='failed', lease_owner=None,
                                                                       lease_until=None,
                                                                       last_error_code='GENERATION_FAILED'))
            tx.execute(update(requests).where(requests.c.id == item.request_id, requests.c.status != 'issued')
                       .values(status='failed', error_code='GENERATION_FAILED'))

    def next_job(self, tx, at):
        return _one(tx, select(jobs).where(self._runnable(at), jobs.c.attempts < 3)
                    .order_by(jobs.c.available_at, jobs.c.id).limit(1).with_for_update(skip_locked=True))

    def lease_job(self, tx, row, token, lease_until):
        """Compare-and-swap also protects SQLite's non-locking SELECT."""
        changed = tx.execute(update(jobs).where(jobs.c.id == row['id'], jobs.c.status == row['status'],
                                                jobs.c.attempts == row['attempts'])
                             .values(status='leased', attempts=row['attempts'] + 1, lease_owner=token,
                                     lease_until=lease_until))
        return changed.rowcount == 1

    def certificate_exists_for_request(self, tx, request_id):
        return tx.execute(select(certificates.c.id).where(certificates.c.request_id == request_id)).first() is not None

    def finish_job(self, tx, job_id, values):
        tx.execute(update(jobs).where(jobs.c.id == job_id).values(**values))

    def set_request_state(self, tx, request_id, status, error_code):
        tx.execute(update(requests).where(requests.c.id == request_id).values(status=status, error_code=error_code))

    def live_lease(self, tx, job, at):
        return tx.execute(select(jobs).where(jobs.c.id == job['id'], jobs.c.status == 'leased',
                                             jobs.c.lease_owner == job['lease_owner'], jobs.c.lease_until > at)
                          .with_for_update()).mappings().first() is not None

    def issue(self, tx, final_asset, thumbnail_asset, certificate):
        tx.execute(insert(assets), [final_asset, thumbnail_asset])
        tx.execute(insert(certificates).values(**certificate))

    # Delivery ---------------------------------------------------------------------
    def issued_asset(self, tx, asset_id, owner_id, kind):
        return _one(tx, select(assets).where(assets.c.id == asset_id, assets.c.owner_account_id == owner_id,
                                             assets.c.kind == kind))

    def certificate_by_id(self, tx, certificate_id, key_version):
        return _one(tx, select(certificates).where(certificates.c.id == certificate_id,
                                                   certificates.c.key_version == key_version))

    def certificate_by_serial(self, tx, serial):
        return _one(tx, select(certificates).where(certificates.c.serial == serial))

    # Exports ------------------------------------------------------------------------
    def export_by_key(self, tx, owner_id, key):
        return _one(tx, select(exports).where(exports.c.owner_account_id == owner_id, exports.c.idempotency_key == key))

    def add_export_if_absent(self, tx, row):
        try:
            with tx.begin_nested():
                tx.execute(insert(exports).values(**row))
            return True
        except IntegrityError:
            return False

    def snapshot_export(self, tx, export_id, owner_id):
        """One INSERT...SELECT statement is one MVCC view of the owner's requests."""
        source = (select(literal(export_id),
                         func.row_number().over(order_by=(requests.c.submitted_at_utc, requests.c.id)),
                         requests.c.owner_account_id, requests.c.id, requests.c.participant_name_original,
                         requests.c.phone_original, links.c.model_name_snapshot, links.c.event_name_snapshot,
                         requests.c.submitted_at_utc, requests.c.status)
                  .select_from(requests.join(links, and_(links.c.id == requests.c.link_id,
                                                         links.c.owner_account_id == requests.c.owner_account_id)))
                  .where(requests.c.owner_account_id == owner_id))
        tx.execute(insert(export_snapshot_rows).from_select(
            ['export_id', 'ordinal', 'owner_account_id', 'source_request_id', 'participant_name_original',
             'phone_original', 'model_name_snapshot', 'event_name_snapshot', 'submitted_at_utc', 'status'], source))
        count = tx.execute(select(func.count()).select_from(export_snapshot_rows)
                           .where(export_snapshot_rows.c.export_id == export_id)).scalar_one()
        tx.execute(update(exports).where(exports.c.id == export_id).values(expected_rows=count))
        return count

    def exports_page(self, tx, owner_id, offset, limit):
        query = (select(exports.c.id, exports.c.status, exports.c.format, exports.c.row_count, exports.c.cutoff,
                        exports.c.error_code, exports.c.snapshot_version, exports.c.snapshot_taken_at,
                        exports.c.expected_rows, assets.c.created_at.label('file_created_at'))
                 .select_from(exports.outerjoin(assets, exports.c.asset_id == assets.c.id))
                 .where(exports.c.owner_account_id == owner_id)
                 .order_by(exports.c.created_at.desc(), exports.c.id).offset(offset).limit(limit))
        return [dict(row) for row in tx.execute(query).mappings()]

    def export(self, tx, owner_id, export_id):
        return _one(tx, select(exports).where(exports.c.id == export_id, exports.c.owner_account_id == owner_id))

    def _export_runnable(self, at):
        return or_(and_(exports.c.status == RUNNABLE_EXPORT,
                        or_(exports.c.lease_until.is_(None), exports.c.lease_until < at)),
                   and_(exports.c.status == 'processing', exports.c.lease_until < at))

    def fail_exhausted_exports(self, tx, at):
        exhausted = tx.execute(select(exports.c.id).where(exports.c.attempts >= 3, self._export_runnable(at))
                               .order_by(exports.c.created_at, exports.c.id).limit(100)
                               .with_for_update(skip_locked=True)).all()
        for item in exhausted:
            tx.execute(update(exports).where(exports.c.id == item.id).values(
                status='failed', lease_owner=None, lease_until=None, error_code='EXPORT_FAILED'))

    def next_export(self, tx, at):
        return _one(tx, select(exports).where(self._export_runnable(at), exports.c.attempts < 3)
                    .where(exports.c.snapshot_version == 2, exports.c.expected_rows.is_not(None))
                    .order_by(exports.c.created_at, exports.c.id).limit(1).with_for_update(skip_locked=True))

    def lease_export(self, tx, row, token, lease_until, at):
        changed = tx.execute(update(exports).where(exports.c.id == row['id'], exports.c.status == row['status'],
                                                   exports.c.attempts == row['attempts'])
                             .values(status='processing', lease_owner=token, lease_until=lease_until,
                                     attempts=row['attempts'] + 1, started_at=at))
        return changed.rowcount == 1

    def live_export(self, tx, job, at):
        return tx.execute(select(exports.c.id).where(
            exports.c.id == job['id'], exports.c.status == 'processing', exports.c.lease_owner == job['lease_owner'],
            exports.c.lease_until > at).with_for_update()).first() is not None

    def supports_lease_heartbeat(self, database):
        return database.dialect.name == 'postgresql'

    def update_export(self, tx, export_id, values):
        tx.execute(update(exports).where(exports.c.id == export_id).values(**values))

    @contextmanager
    def snapshot_rows(self, database, job):
        """Stream an export's frozen rows inside one (repeatable-read) transaction."""
        with database.connect() as conn:
            if database.dialect.name == 'postgresql':
                conn = conn.execution_options(isolation_level='REPEATABLE READ')
            with conn.begin():
                query = (select(export_snapshot_rows)
                         .where(export_snapshot_rows.c.export_id == job['id'],
                                export_snapshot_rows.c.owner_account_id == job['owner_account_id'])
                         .order_by(export_snapshot_rows.c.ordinal))
                yield conn.execution_options(stream_results=True).execute(query).mappings().yield_per(500)

    def expirable_exports(self, tx, cutoff, batch_size):
        query = (select(exports.c.id, exports.c.asset_id, assets.c.storage_key)
                 .select_from(exports.join(assets, exports.c.asset_id == assets.c.id))
                 .where(exports.c.status == 'done', assets.c.kind == 'export', assets.c.created_at <= cutoff)
                 .order_by(assets.c.created_at, exports.c.id).limit(batch_size)
                 .with_for_update(skip_locked=True, of=exports))
        return [{'id': row.id, 'asset_id': row.asset_id, 'storage_key': row.storage_key}
                for row in tx.execute(query).all()]

    def expire_export(self, tx, export_id, asset_id):
        changed = tx.execute(update(exports).where(exports.c.id == export_id, exports.c.status == 'done',
                                                   exports.c.asset_id == asset_id)
                             .values(status='failed', asset_id=None, error_code='EXPORT_EXPIRED', lease_owner=None,
                                     lease_until=None))
        if changed.rowcount != 1:
            return False
        tx.execute(delete(export_snapshot_rows).where(export_snapshot_rows.c.export_id == export_id))
        tx.execute(delete(assets).where(assets.c.id == asset_id, assets.c.kind == 'export'))
        return True

    def expire_abandoned_exports(self, tx, cutoff, batch_size):
        abandoned = tx.execute(select(exports.c.id).where(
            exports.c.snapshot_version == 2, exports.c.status == 'failed', exports.c.asset_id.is_(None),
            exports.c.error_code != 'EXPORT_EXPIRED', exports.c.created_at <= cutoff)
            .order_by(exports.c.created_at, exports.c.id).limit(batch_size)
            .with_for_update(skip_locked=True)).scalars().all()
        for export_id in abandoned:
            tx.execute(update(exports).where(exports.c.id == export_id).values(error_code='EXPORT_EXPIRED'))
            tx.execute(delete(export_snapshot_rows).where(export_snapshot_rows.c.export_id == export_id))
        return len(abandoned)

    # Private asset store bookkeeping -----------------------------------------------
    def asset_referenced(self, tx, asset_id):
        return bool(
            tx.execute(select(revisions.c.id).where(or_(revisions.c.background_asset_id == asset_id,
                                                        revisions.c.stamp_asset_id == asset_id)).limit(1)).first()
            or tx.execute(select(certificates.c.id).where(or_(certificates.c.final_asset_id == asset_id,
                                                              certificates.c.thumbnail_asset_id == asset_id))
                          .limit(1)).first()
            or tx.execute(select(exports.c.id).where(exports.c.asset_id == asset_id).limit(1)).first())

    def unreferenced_assets(self, tx, created_before, batch_size):
        unreferenced = and_(
            ~exists(select(revisions.c.id).where(or_(revisions.c.background_asset_id == assets.c.id,
                                                     revisions.c.stamp_asset_id == assets.c.id))),
            ~exists(select(certificates.c.id).where(or_(certificates.c.final_asset_id == assets.c.id,
                                                        certificates.c.thumbnail_asset_id == assets.c.id))),
            ~exists(select(exports.c.id).where(exports.c.asset_id == assets.c.id)))
        query = (select(assets).where(assets.c.created_at < created_before, unreferenced)
                 .order_by(assets.c.created_at, assets.c.id).limit(batch_size).with_for_update(skip_locked=True))
        return [dict(row) for row in tx.execute(query).mappings()]

    def delete_asset(self, tx, asset_id):
        tx.execute(delete(assets).where(assets.c.id == asset_id))

    def storage_key_known(self, tx, key):
        return tx.execute(select(assets.c.id).where(assets.c.storage_key == key).limit(1)).first() is not None

    # Readiness facts ------------------------------------------------------------------
    def readiness_facts(self, tx):
        queue = dict(tx.execute(select(jobs.c.status, func.count()).group_by(jobs.c.status)).all())
        active = ('pending', 'retry_wait', 'leased')
        return {
            'has_history': self.has_history(tx),
            'key_versions': tx.execute(select(links.c.key_version).union(select(certificates.c.key_version))).scalars().all(),
            'queue': queue,
            'oldest_job_created_at': tx.execute(select(func.min(jobs.c.created_at))
                                                .where(jobs.c.status.in_(active))).scalar_one(),
            'export_pending': tx.execute(select(func.count()).select_from(exports)
                                         .where(exports.c.status.in_(('pending', 'processing')))).scalar_one(),
            'now': self.lease_now(tx),
        }

    # Rate limits ------------------------------------------------------------------------
    def count_in_window(self, database, bucket_hash, window):
        """Atomic per-window counter (upsert) in its own short transaction."""
        if database.dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert as upsert
        else:
            from sqlalchemy.dialects.sqlite import insert as upsert
        with database.begin() as conn:
            statement = upsert(rate_buckets).values(bucket_hash=bucket_hash, window=window, count=1)
            return conn.execute(statement.on_conflict_do_update(
                index_elements=[rate_buckets.c.bucket_hash, rate_buckets.c.window],
                set_={'count': rate_buckets.c.count + 1}).returning(rate_buckets.c.count)).scalar_one()

    def prune_windows(self, tx, before_window, limit=1000):
        """Bounded cleanup; no participant or certificate data is purged."""
        rows = tx.execute(select(rate_buckets.c.bucket_hash, rate_buckets.c.window)
                          .where(rate_buckets.c.window < before_window).limit(limit)).all()
        for key, window in rows:
            tx.execute(delete(rate_buckets).where(rate_buckets.c.bucket_hash == key, rate_buckets.c.window == window))
        return len(rows)

