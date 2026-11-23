"""Event-issued certificates: templates, issued certificates, replacements,
bulk import previews and the issuance job queue."""
from __future__ import annotations

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.infrastructure.persistence.certificate_tables import (
    certificate_imports,
    certificate_jobs,
    certificate_replacements,
    certificate_templates,
    certificates,
)

LOOKUP_COLUMNS = {'serial': certificates.c.serial, 'access_hash': certificates.c.access_hash}


def _one(tx, query):
    row = tx.execute(query).mappings().first()
    return dict(row) if row else None


class SqlCertificateRepository:
    # Templates ----------------------------------------------------------------
    def add_template(self, tx, row):
        tx.execute(insert(certificate_templates).values(**row))

    def template(self, tx, event_id, template_id):
        return _one(tx, select(certificate_templates).where(certificate_templates.c.id == template_id,
                                                            certificate_templates.c.event_id == event_id))

    def templates(self, tx, event_id):
        query = (select(certificate_templates).where(certificate_templates.c.event_id == event_id)
                 .order_by(certificate_templates.c.created_at))
        return [dict(row) for row in tx.execute(query).mappings()]

    # Certificates ---------------------------------------------------------------
    def certificate(self, tx, event_id, certificate_id):
        return _one(tx, select(certificates).where(certificates.c.event_id == event_id,
                                                   certificates.c.id == certificate_id))

    def find_by(self, tx, field, value):
        return _one(tx, select(certificates).where(LOOKUP_COLUMNS[field] == value))

    def by_request_key(self, tx, event_id, request_key):
        return _one(tx, select(certificates).where(certificates.c.event_id == event_id,
                                                   certificates.c.request_key == request_key))

    def award_exists(self, tx, event_id, recipient_key, award_key):
        query = select(certificates.c.id).where(certificates.c.event_id == event_id,
                                                certificates.c.recipient_key == recipient_key,
                                                certificates.c.award_key == award_key)
        return tx.execute(query).first() is not None

    def add_if_absent(self, tx, row):
        """Unique request key and award key are the authorities against duplicates."""
        try:
            with tx.begin_nested():
                tx.execute(insert(certificates).values(**row))
            return True
        except IntegrityError:
            return False

    def page(self, tx, event_id, offset, limit):
        query = (select(certificates).where(certificates.c.event_id == event_id)
                 .order_by(certificates.c.issued_at.desc(), certificates.c.id).offset(offset).limit(limit))
        return [dict(row) for row in tx.execute(query).mappings()]

    def revoke(self, tx, certificate_id, at, reason):
        tx.execute(update(certificates).where(certificates.c.id == certificate_id, certificates.c.status == 'issued')
                   .values(status='revoked', revoked_at=at, revoke_reason=reason))

    def set_access_hash(self, tx, certificate_id, access_hash):
        tx.execute(update(certificates).where(certificates.c.id == certificate_id).values(access_hash=access_hash))

    # Replacements -----------------------------------------------------------
    def replacement_of(self, tx, previous_id):
        return _one(tx, select(certificate_replacements).where(certificate_replacements.c.previous_id == previous_id))

    def add_replacement_if_absent(self, tx, row):
        try:
            with tx.begin_nested():
                tx.execute(insert(certificate_replacements).values(**row))
            return True
        except IntegrityError:
            return False

    # Bulk imports and jobs ------------------------------------------------------
    def add_import(self, tx, row):
        tx.execute(insert(certificate_imports).values(**row))

    def lock_import(self, tx, import_id, event_id, user_id):
        return _one(tx, select(certificate_imports).where(
            certificate_imports.c.id == import_id, certificate_imports.c.event_id == event_id,
            certificate_imports.c.user_id == user_id).with_for_update())

    def mark_import_committed(self, tx, import_id, at):
        result = tx.execute(update(certificate_imports).where(certificate_imports.c.id == import_id,
                                                             certificate_imports.c.committed_at.is_(None))
                            .values(committed_at=at))
        return result.rowcount == 1

    def add_job(self, tx, row):
        tx.execute(insert(certificate_jobs).values(**row))

    def next_pending_job(self, tx, at):
        query = (select(certificate_jobs).where(certificate_jobs.c.state == 'pending', certificate_jobs.c.available_at <= at)
                 .order_by(certificate_jobs.c.created_at, certificate_jobs.c.id).limit(1))
        if tx.dialect.name == 'postgresql':
            query = query.with_for_update(skip_locked=True)
        return _one(tx, query)

    def claim_job(self, tx, job_id):
        result = tx.execute(update(certificate_jobs).where(certificate_jobs.c.id == job_id,
                                                          certificate_jobs.c.state == 'pending').values(state='running'))
        return result.rowcount == 1

    def finish_job(self, tx, job_id, values):
        tx.execute(update(certificate_jobs).where(certificate_jobs.c.id == job_id).values(**values))

    def job_progress(self, tx, event_id):
        query = (select(certificate_jobs.c.import_id, certificate_jobs.c.state, func.count().label('count'))
                 .where(certificate_jobs.c.event_id == event_id)
                 .group_by(certificate_jobs.c.import_id, certificate_jobs.c.state))
        return [dict(row) for row in tx.execute(query).mappings()]
