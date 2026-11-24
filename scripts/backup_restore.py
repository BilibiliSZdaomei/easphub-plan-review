"""Consistent SQLite backup with file hashes; restore only into an empty directory."""
import argparse,hashlib,json,sqlite3,tempfile,zipfile,os,sys
from contextlib import closing
from pathlib import Path
from datetime import datetime,timezone

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def backup(data,destination):
    data=Path(data).resolve();source=data/'plan-review.sqlite3'
    if not source.is_file():raise ValueError('没有找到计划审核数据库')
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    target=destination/('plan-review-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.zip')
    with tempfile.TemporaryDirectory(prefix='plan-review-backup-') as temp:
        tempdb=Path(temp)/'plan-review.sqlite3'
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as origin,closing(sqlite3.connect(tempdb)) as saved:
            origin.backup(saved)
            if saved.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('数据库完整性检查失败')
        files={'plan-review.sqlite3':tempdb}
        if (data/'files').exists():
            files.update({'files/'+p.name:p for p in (data/'files').iterdir() if p.is_file() and not p.is_symlink() and not p.name.endswith('.tmp')})
        manifest={'format':1,'created_at':datetime.now(timezone.utc).isoformat(),'database':'SQLite','files':{k:digest(v) for k,v in files.items()}}
        with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED) as z:
            for name,path in files.items():z.write(path,name)
            z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return {'backup':str(target),'files':len(files),'sha256':digest(target)}

def restore(archive,target):
    target=Path(target).resolve()
    if target.exists() and any(target.iterdir()):raise ValueError('恢复目录必须为空。不会覆盖运行中的数据库或现有文件。')
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or sum(i.file_size for i in z.infolist())>2*1024**3:raise ValueError('备份包结构或大小无效')
        manifest=json.loads(z.read('manifest.json'))
        if manifest.get('format')!=1 or set(names)!=set(manifest['files'])|{'manifest.json'}:raise ValueError('备份清单不匹配')
        if 'plan-review.sqlite3' not in manifest['files']:raise ValueError('备份缺少数据库')
        # Validate every name before any extraction. Never use extractall.
        for name in manifest['files']:
            p=(target/name).resolve()
            if not p.is_relative_to(target) or '\\' in name or ':' in name or name.startswith('/'):raise ValueError('备份包含非法路径')
            if hashlib.sha256(z.read(name)).hexdigest()!=manifest['files'][name]:raise ValueError('文件校验失败：'+name)
        target.mkdir(parents=True,exist_ok=True)
        for name in manifest['files']:
            p=target/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(name))
    with closing(sqlite3.connect(target/'plan-review.sqlite3')) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('恢复后的数据库完整性检查失败')
        db.execute('DELETE FROM sessions');db.commit()
        counts={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ['users','snapshots','batches','versions','audit','jobs']}
    return {'restored_to':str(target),'integrity':'ok','counts':counts,'sessions_cleared':True,'files_verified':len(manifest['files'])}

if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    b=sub.add_parser('backup');b.add_argument('--data',default=str(Path(os.getenv('LOCALAPPDATA',Path.home()))/'PlanReview'/'data'));b.add_argument('--destination',required=True)
    r=sub.add_parser('restore');r.add_argument('--archive',required=True);r.add_argument('--target',required=True)
    args=p.parse_args()
    try:result=backup(args.data,args.destination) if args.action=='backup' else restore(args.archive,args.target);print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as e:print(str(e),file=sys.stderr);sys.exit(1)
