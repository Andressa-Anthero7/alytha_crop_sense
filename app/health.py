"""Local operational counters without credentials or private analytical payloads."""
from . import storage


def snapshot():
    with storage.connect() as db:
        db.execute('SELECT 1').fetchone()
        counts={r[0]:r[1] for r in db.execute('SELECT status,count(*) FROM analytical_jobs GROUP BY status')}
        completed=db.execute("SELECT count(*),avg((julianday(updated_at)-julianday(created_at))*86400) FROM analytical_jobs WHERE status IN ('ready','inconclusive','error')").fetchone()
        expired=db.execute("SELECT count(*) FROM analytical_jobs WHERE status='running' AND lease_until<=?",(storage.now(),)).fetchone()[0]
        version=db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
    return {'status':'ok','checked_at':storage.now(),'database':'reachable','schema_version':version,
            'local_analytical_jobs':counts,'expired_local_leases':expired,
            'completed_local_jobs':completed[0], 'mean_local_turnaround_seconds':round(completed[1],3) if completed[1] is not None else None,
            'scope':'Operação local; não verifica acesso externo, custos, isolamento ou prontidão de produção.'}
