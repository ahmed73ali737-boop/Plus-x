"""SQLAlchemy Core persistence adapters (tables, repositories, unit of work).

``install_sql_persistence`` is called by the composition root (``make_engine``)
and binds every application port to its SQL implementation.
"""
from __future__ import annotations


def install_sql_persistence() -> None:
    from app.application.ports import persistence
    from app.infrastructure.channel_gateway import ChannelGatewayPhoneVerifier
    from app.infrastructure.persistence.access_repository import SqlAccessRepository
    from app.infrastructure.persistence.account_request_repository import SqlAccountRequestRepository
    from app.infrastructure.persistence.audit_repository import SqlAuditLog
    from app.infrastructure.persistence.certificate_repository import SqlCertificateRepository
    from app.infrastructure.persistence.committee_repository import SqlCommitteeRepository
    from app.infrastructure.persistence.identity_repository import SqlIdentityRepository
    from app.infrastructure.persistence.self_certificate_repository import SqlSelfCertificateRepository
    from app.infrastructure.persistence.site_admin_repository import SqlSiteAdminRepository
    from app.infrastructure.persistence.submission_repository import SqlSubmissionRepository
    from app.infrastructure.persistence.admission_repository import SqlAdmissionRepository
    from app.infrastructure.persistence.device_repository import SqlDeviceRepository
    from app.infrastructure.persistence.gate_repository import SqlCheckinLog, SqlPresenceRepository
    from app.infrastructure.persistence.guest_repository import SqlGuestRepository
    from app.infrastructure.persistence.site_repository import SqlSiteRepository
    from app.infrastructure.persistence.transactions import SqlTransactions

    persistence.install(
        transactions=SqlTransactions(),
        sites=SqlSiteRepository(),
        guests=SqlGuestRepository(),
        presence=SqlPresenceRepository(),
        checkins=SqlCheckinLog(),
        admission=SqlAdmissionRepository(),
        devices=SqlDeviceRepository(),
        access=SqlAccessRepository(),
        identity=SqlIdentityRepository(),
        audit=SqlAuditLog(),
        submissions=SqlSubmissionRepository(),
        site_admin=SqlSiteAdminRepository(),
        account_requests=SqlAccountRequestRepository(),
        committee=SqlCommitteeRepository(),
        certificates=SqlCertificateRepository(),
        self_certificates=SqlSelfCertificateRepository(),
        phone_verifier=ChannelGatewayPhoneVerifier(),
    )
