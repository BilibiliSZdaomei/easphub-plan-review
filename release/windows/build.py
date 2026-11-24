"""Build an offline Windows x64 desktop ZIP from a clean release checkout.

Run with a Windows CPython 3.12 x64 virtual environment installed from
requirements-lock.txt. --ui must point to the prebuilt /plan-review frontend.
"""
import argparse
import base64
import contextlib
from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import sys
import tarfile
import tempfile
import zipfile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

PYTHON_VERSION = '3.12.16'
RUNTIME_ASSET = 'cpython-3.12.16+20261123-x86_64-pc-windows-msvc-install_only_stripped.tar.gz'
RUNTIME_SHA256 = '75988f49393727d7e53b673d50088e7f809a629dd37cb59da3756479bc6ea5c1'
RUNTIME_URL = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261123/' + RUNTIME_ASSET


def pinned_versions(source):
    lines = (source/'requirements-lock.txt').read_text(encoding='utf-8-sig').splitlines()
    return {canonicalize_name(line.split('==')[0]): line.split('==')[1]
            for line in lines if '==' in line and not line.lstrip().startswith('#')}


def production_distributions(source):
    pins = pinned_versions(source)
    lines = (source/'requirements.txt').read_text(encoding='utf-8-sig').splitlines()
    pending = [Requirement(line) for line in lines if line.strip() and not line.startswith('#')]
    selected = {}
    while pending:
        requirement = pending.pop()
        if requirement.marker and not requirement.marker.evaluate({'extra': ''}):
            continue
        name = canonicalize_name(requirement.name)
        dist = metadata.distribution(name)
        if pins.get(name) != dist.version or dist.version not in requirement.specifier:
            raise ValueError(f'{name} must satisfy {requirement} and match requirements-lock.txt')
        if name in selected:
            continue
        selected[name] = dist
        pending.extend(Requirement(child) for child in (dist.requires or []))
    return selected


def include_stdlib(relative):
    skip = {'site-packages', 'dist-packages', '__pycache__', 'test', 'tests',
            'ensurepip', 'idlelib', 'turtledemo', 'tkinter', 'lib2to3', 'venv'}
    return not skip.intersection(relative.parts) and relative.suffix not in {'.pyc', '.pyo', '.pth'}


def build(args):
    if sys.platform != 'win32' or platform.machine().upper() not in {'AMD64', 'X86_64'} or sys.version_info[:2] != (3,12):
        raise SystemExit('Run using Windows x64 CPython 3.12')
    source = args.source.resolve()
    ui = args.ui.resolve()
    manifest = json.loads((ui/'app-build.json').read_text(encoding='utf-8-sig'))
    source_version = json.loads((source/'frontend/package.json').read_text(encoding='utf-8-sig'))['version']
    if not (manifest.get('version') == source_version == args.version):
        raise ValueError('Frontend build, source and release versions must match')
    if manifest['base_path'] != '/plan-review' or manifest['account_mode'] != 'managed':
        raise ValueError('Expected a managed /plan-review frontend')
    output = args.output.resolve()
    if source in output.parents or output == source:
        raise ValueError('Use an output path outside the release checkout')
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    runtime = args.python_archive.resolve()
    if sha256(runtime.read_bytes()).hexdigest() != RUNTIME_SHA256:
        raise ValueError(f'Wrong Python runtime archive; use {RUNTIME_URL}')
    lock = source/'requirements-lock.txt'
    distros = production_distributions(source)
    launcher = Path(__file__).resolve().parent
    prefix = 'PlanReview-Windows-x64/'
    names = set()

    def add_file(archive, path, name, *, windows_text=False):
        name = Path(name).as_posix()
        if name in names:
            raise ValueError(f'duplicate path {name}')
        names.add(name)
        if windows_text:
            content = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\n', '\r\n')
            encoding = 'utf-8-sig' if path.suffix.lower() in ('.ps1', '.txt') else 'ascii'
            archive.writestr(prefix + name, content.encode(encoding))
        else:
            archive.write(path, prefix + name)

    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=output.stem+'-', suffix='.partial', delete=False) as handle:
        temp = Path(handle.name)
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            runtime_files = {'python.exe','python3.dll','python312.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'}
            with tarfile.open(runtime,'r:gz') as archive:
                for member in archive:
                    if not member.isfile():
                        continue
                    relative = Path(member.name).relative_to('python')
                    if len(relative.parts) == 1:
                        if relative.name not in runtime_files:
                            continue
                    elif relative.parts[0] == 'DLLs':
                        if relative.name.startswith(('_test', '_ctypes_test', '_tkinter', 'tk86', 'tcl86')):
                            continue
                    elif relative.parts[0] == 'Lib' and include_stdlib(relative):
                        pass
                    else:
                        continue
                    name = 'runtime/'+relative.as_posix()
                    if name in names:
                        raise ValueError(f'duplicate runtime path {name}')
                    names.add(name)
                    z.writestr(prefix+name,archive.extractfile(member).read())
            if not all('runtime/'+name in names for name in runtime_files):
                raise ValueError('Incomplete Python runtime')
            for name, dist in sorted(distros.items()):
                if not dist.files:
                    raise ValueError(f'No installation manifest for {name}')
                for entry in sorted(dist.files):
                    parts = entry.parts
                    if (entry.is_absolute() or '..' in parts or '__pycache__' in parts or
                        Path(entry).suffix in ('.pyc','.pyo') or entry.name in ('direct_url.json','RECORD')):
                        continue
                    path = Path(dist.locate_file(entry))
                    if not path.is_file():
                        raise FileNotFoundError(path)
                    if not entry.hash or entry.hash.mode != 'sha256':
                        raise ValueError(f'Missing wheel hash for {name}/{entry}')
                    actual = base64.urlsafe_b64encode(sha256(path.read_bytes()).digest()).rstrip(b'=').decode()
                    if actual != entry.hash.value:
                        raise ValueError(f'Installed wheel file changed: {name}/{entry}')
                    add_file(z, path, 'runtime/Lib/site-packages/'+entry.as_posix())
            for file in ('alembic.ini','deploy/warehouses.example.json','scripts/prepare_desktop.py','scripts/bootstrap.py'):
                add_file(z, source/file, file)
            for path in sorted((source/'backend').glob('*.py')):
                add_file(z,path,path.relative_to(source))
            for filename in ('plan-review-v2.xlsx', 'replenishment-plan.xlsx'):
                template = source/'backend'/'templates'/filename
                add_file(z,template,template.relative_to(source))
            for path in sorted((source/'migrations').rglob('*')):
                if path.is_file() and path.suffix in ('.py','.mako'):
                    add_file(z,path,path.relative_to(source))
            for path in sorted(ui.rglob('*')):
                if path.is_file():
                    if (path.suffix not in ('.js','.html','.css','.svg','.webp','.woff2','.json','.txt')
                            or path.name.lower() == 'signature.png'):
                        raise ValueError(f'Unexpected frontend asset {path.name}')
                    add_file(z,path,'frontend/dist/'+path.relative_to(ui).as_posix())
            for filename in ('initialize-desktop.ps1','show-initial-admin.ps1'):
                add_file(z,source/'scripts'/filename,'scripts/'+filename,windows_text=True)
            for filename in ('Start.cmd','Admin.cmd','README.windows.txt'):
                add_file(z,launcher/filename,filename,windows_text=True)
            add_file(z,launcher/'Verify.cmd','Verify.cmd',windows_text=True)
            add_file(z,launcher/'Admin.cmd','查看初始管理员.cmd',windows_text=True)
            for filename in ('start.ps1','verify-package.ps1','runtime.ps1','portable-server.py'):
                add_file(z,launcher/filename,'scripts/'+filename,windows_text=filename.endswith('.ps1'))
            z.writestr(prefix+'versions.json',json.dumps({
                'version':args.version,'platform':'windows-x64','python':PYTHON_VERSION,
                'python_source':RUNTIME_URL,'python_archive_sha256':RUNTIME_SHA256,
                'requirements_lock_sha256':sha256(lock.read_bytes()).hexdigest(),
                'packages':{name:dist.version for name,dist in sorted(distros.items())}
            },indent=2)+'\n')
        with zipfile.ZipFile(temp, 'a', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            files = {}
            for entry in z.infolist():
                with z.open(entry) as content:
                    files[entry.filename.removeprefix(prefix)] = sha256(content.read()).hexdigest()
            z.writestr(prefix+'package-files.json',json.dumps(files,ensure_ascii=True,sort_keys=True)+'\n')
        temp.replace(output)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--ui', type=Path, required=True)
    parser.add_argument('--python-archive',type=Path,required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', default='2.1.0')
    build(parser.parse_args())
