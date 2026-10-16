"""Durable queue for local analytical tools, separate from satellite collection.

SQLite leases and completion fencing permit independent worker processes. Only
local tools can be replayed: an ambiguous external request must not be retried by
this queue. The legacy satellite and visual workers are separate subsystems.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone
from . import storage, research, analytical_assistant, conversation_context

TOOLS = {'historical_comparison','direction','planting_window','synthesis','regional_calendar'}


def submit(data):
    prompt=data.get('prompt')
    if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=3000:
        raise ValueError('Informe uma pergunta de até 3000 caracteres.')
    data=conversation_context.restore(data)
    tool=analytical_assistant.requested(prompt)
    if tool not in TOOLS:raise ValueError('A fila aceita apenas análises locais, sem coleta Sentinel, meteorologia externa ou provedor de IA.')
    history=analytical_assistant.history_for(data)
    payload={k:data[k] for k in (*conversation_context.FIELDS,'prompt','planting_window','soil','cultivar_group','risk_percent','management') if k in data}
    payload['dataset_id']=history['id']
    with storage.connect() as db:
        stamp=db.execute("SELECT max(fetched_at) FROM source_snapshots WHERE cache_key LIKE 'cv:job:%' AND json_extract(result,'$.parameters.area_id')=?",
                         (history['parameters']['area_key'],)).fetchone()[0]
    window=storage.source_snapshot('evolution-window:v1:'+history['parameters']['area_key'])
    dedupe=research.fingerprint([payload,research.fingerprint(history),stamp,window,1])
    identifier=secrets.token_hex(32);now=storage.now()
    with storage.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT id FROM analytical_jobs WHERE dedupe_key=?',(dedupe,)).fetchone()
        if existing:return get_in(db,existing['id'])
        pending=db.execute("SELECT count(*) FROM analytical_jobs WHERE status IN ('queued','running')").fetchone()[0]
        if pending>=1000:raise ValueError('Fila local cheia; aguarde a conclusão dos trabalhos existentes.')
        db.execute('INSERT INTO analytical_jobs(id,dedupe_key,tool,payload,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                   (identifier,dedupe,tool,json.dumps(payload), 'queued',now,now))
        return get_in(db,identifier)


def get_in(db, identifier):
    row=db.execute('SELECT * FROM analytical_jobs WHERE id=?',(identifier,)).fetchone()
    if not row:raise ValueError('Trabalho não encontrado.')
    result={key:row[key] for key in ('id','tool','status','created_at','updated_at','attempts','lease_until','error')}
    result['mode']='local_only';result['result']=json.loads(row['result']) if row['result'] else None
    return result


def get(identifier):
    with storage.connect() as db:return get_in(db,identifier)


def claim(worker_id, lease_seconds=300, concurrency=2):
    if not 1<=lease_seconds<=3600 or not 1<=concurrency<=8:raise ValueError('Limites de execução inválidos.')
    now=storage.now();until=(datetime.now(timezone.utc)+timedelta(seconds=lease_seconds)).isoformat()
    with storage.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # Local-only replay is safe; repeatedly interrupted work stops after 3 claims.
        db.execute("UPDATE analytical_jobs SET status='error',error='Limite de retomadas locais atingido.',updated_at=?,lease_token=NULL,lease_until=NULL WHERE status='running' AND lease_until<=? AND attempts>=3",(now,now))
        running=db.execute("SELECT count(*) FROM analytical_jobs WHERE status='running' AND lease_until>?",(now,)).fetchone()[0]
        if running>=concurrency:return None
        row=db.execute("SELECT * FROM analytical_jobs WHERE status='queued' OR (status='running' AND lease_until<=? AND attempts<3) ORDER BY created_at,id LIMIT 1",(now,)).fetchone()
        if not row:return None
        token=secrets.token_hex(32)
        db.execute("UPDATE analytical_jobs SET status='running',attempts=attempts+1,lease_until=?,lease_token=?,worker_id=?,updated_at=? WHERE id=?",
                   (until,token,worker_id,now,row['id']))
        return {'id':row['id'],'tool':row['tool'],'payload':json.loads(row['payload']),'lease_token':token}


def heartbeat(identifier, token, lease_seconds=300):
    until=(datetime.now(timezone.utc)+timedelta(seconds=lease_seconds)).isoformat()
    with storage.connect() as db:
        return db.execute("UPDATE analytical_jobs SET lease_until=?,updated_at=? WHERE id=? AND lease_token=? AND status='running' AND lease_until>?",
                          (until,storage.now(),identifier,token,storage.now())).rowcount==1


def complete(identifier, token, response):
    now=storage.now()
    status=response['work']['status']
    if status not in ('ready','inconclusive','error'):raise ValueError('Estado final inválido.')
    with storage.connect() as db:
        return db.execute("UPDATE analytical_jobs SET status=?,result=?,error=?,updated_at=?,lease_token=NULL,lease_until=NULL WHERE id=? AND lease_token=? AND status='running' AND lease_until>?",
                          (status,json.dumps(response,ensure_ascii=False,allow_nan=False),response['answer'] if status=='error' else None,
                           now,identifier,token,now)).rowcount==1
