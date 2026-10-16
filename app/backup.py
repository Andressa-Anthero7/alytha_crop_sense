"""Consistent SQLite backup plus raw rasters, models and visual source assets.

Core mode excludes regenerable exports; full mode includes all data files.
Restore always targets a new directory and verifies every archived byte hash.
"""
import argparse
import hashlib
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from contextlib import closing
from . import storage

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    sha=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):sha.update(chunk)
    return sha.hexdigest()


def database_check(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Falha na integridade do banco restaurado.')
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts={table:db.execute('SELECT count(*) FROM "'+table.replace('"','""')+'"').fetchone()[0] for table in tables}
    return counts


def create(destination=None, full=False, data_root=None):
    data=Path(data_root or ROOT/'data').resolve()
    target=Path(destination or ROOT/'local_backups'/('alytha-'+storage.now().replace(':','-')+'.zip')).resolve()
    if target.exists():raise ValueError('O arquivo de backup já existe; escolha um novo destino.')
    if target.is_relative_to(data):raise ValueError('Guarde o backup fora da árvore de dados de origem.')
    target.parent.mkdir(parents=True,exist_ok=True)
    paths=[]
    roots=[data] if full else [data/'rasters',data/'models',data/'outputs/vision/assets']
    for folder in roots:
        if folder.exists():
            for path in folder.rglob('*'):
                if path.is_file() and path.resolve().is_relative_to(data) and not path.is_symlink():
                    if path.name.startswith(storage.DB_PATH.name) or path.suffix=='.tmp' or path.name=='.env' or path.name.startswith('.env.'):continue
                    paths.append(path)
    temporary=target.with_suffix('.tmp')
    manifest={'version':1,'mode':'full' if full else 'core','created_at':storage.now(),
              'excluded':'Segredos .env nunca são incluídos. Core omite exportações regeneráveis; full inclui a árvore data.',
              'consistency':'SQLite Backup API; arquivos conferidos individualmente, sem snapshot global dos workers.',
              'files':{}}
    try:
        with tempfile.TemporaryDirectory() as workspace:
            snapshot=Path(workspace)/'monitoring.sqlite3'
            with closing(sqlite3.connect(storage.DB_PATH.resolve().as_uri()+'?mode=ro',uri=True,timeout=15)) as source, \
                 closing(sqlite3.connect(snapshot)) as output:
                source.backup(output,pages=1000)
            manifest['database_rows']=database_check(snapshot)
            with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
                for path,name in [(snapshot,'data/monitoring.sqlite3'),*[(p,'data/'+p.relative_to(data).as_posix()) for p in sorted(set(paths))]]:
                    before=digest(path);archive.write(path,name)
                    if before!=digest(path):raise ValueError('Um artefato mudou durante o backup; tente novamente com os workers parados.')
                    manifest['files'][name]={'sha256':before,'bytes':path.stat().st_size}
                archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            temporary.replace(target)
        return {'archive':str(target),'files':len(manifest['files']),'database_rows':manifest['database_rows'],'mode':manifest['mode']}
    finally:
        temporary.unlink(missing_ok=True)


def restore(archive_path,destination):
    target=Path(destination).resolve()
    if target.exists():raise ValueError('Restaure em uma pasta nova; nenhum arquivo existente será sobrescrito.')
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive_path) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        if not isinstance(manifest.get('files'),dict) or 'data/monitoring.sqlite3' not in manifest['files']:
            raise ValueError('Manifesto de backup inválido.')
        for name,expected in manifest['files'].items():
            path=(target/name).resolve()
            if not name.startswith('data/') or not path.is_relative_to(target/'data') or '\\' in name:
                raise ValueError('Caminho inválido no arquivo de backup.')
            entry=archive.getinfo(name)
            if entry.file_size!=expected['bytes']:raise ValueError('Tamanho de artefato incompatível com o manifesto.')
            path.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(name) as source,path.open('wb') as output:
                for chunk in iter(lambda:source.read(1024*1024),b''):output.write(chunk)
            if digest(path)!=expected['sha256']:raise ValueError('Hash de artefato restaurado inválido.')
    counts=database_check(target/'data/monitoring.sqlite3')
    if counts!=manifest['database_rows']:raise ValueError('Contagens do banco restaurado divergem do backup.')
    result={'restored_to':str(target),'verified_files':len(manifest['files']),'database_rows':counts,'mode':manifest['mode']}
    (target/'restore-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    backup=sub.add_parser('create');backup.add_argument('--output',type=Path);backup.add_argument('--full',action='store_true')
    recover=sub.add_parser('restore');recover.add_argument('archive',type=Path);recover.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    result=create(args.output,args.full) if args.command=='create' else restore(args.archive,args.destination)
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
