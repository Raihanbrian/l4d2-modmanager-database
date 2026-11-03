"""Prepare an unpublished source ZIP from an explicit, privacy-reviewed allowlist."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import tomllib
import zipfile

ROOT_FILES=('.gitattributes','LICENSE','.gitignore','pyproject.toml','requirements-build.txt','Start-Alpha.cmd','Build-Portable.ps1',
 'L4D2ModDatabase.spec','README.md','RELEASE_NOTES.md','POST_RELEASE_BACKLOG.md','M3_SCHEMA_PROPOSAL.md','M3_SAMPLE_DATA.md','UI_DATA_PRESENTATION_CONTRACT.md')
TOOL_FILES=('create_demo.py','validate_collection.py','validate_conflicts.py','portable_entry.py','smoke_portable.py','review_fixture.py','prepare_source.py')
PUBLIC_DOCS=('DEVELOPMENT.md','PRIVACY.md','LICENSING.md','CONFLICTS.md','RELEASING.md','BETA_CHECKLIST.md')
ISSUE_FILES=('bug_report.yml',)
BAD_NAME=re.compile(r'(?:preferences|credential|secret|settings\.local|user-settings|\.env)',re.I)
PRIVATE_PATH=re.compile(r'(?:C:[/\\]+Users[/\\]+User(?:[/\\]|\b)|D:[/\\]+Portofolio[/\\])',re.I)


def source_files(root):
    names=list(ROOT_FILES)+['tools/'+n for n in TOOL_FILES]+['docs/'+n for n in PUBLIC_DOCS]+['.github/ISSUE_TEMPLATE/'+n for n in ISSUE_FILES]
    for folder in ('l4d2_mod_db','tests'):
        names.extend(p.relative_to(root).as_posix() for p in sorted((root/folder).glob('*.py')) if not BAD_NAME.search(p.name))
    names.extend(p.relative_to(root).as_posix() for p in sorted((root/'release').rglob('*')) if p.is_file() and p.suffix in ('.txt','.terms'))
    # Only new synthetic screenshots are public; actual-collection captures are excluded.
    names.extend(p.relative_to(root).as_posix() for p in sorted((root/'docs/screenshots/m64').glob('*')) if p.suffix in ('.png','.jpg'))
    names.extend('examples/m3-demo/'+name for name in ('m3_demo.sqlite3','fictional_records.json','README.md'))
    result=[]
    for name in sorted(set(names)):
        path=root/name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe or missing public source input: '+name)
        for part in (path,*path.parents):
            if part==root:break
            if getattr(part.lstat(),'st_file_attributes',0)&0x400:raise ValueError('Reparse input refused: '+name)
        if path.suffix in ('.py','.md','.txt','.json','.yml','.toml','.ps1','.spec','.cmd') and PRIVATE_PATH.search(path.read_text(encoding='utf8')):raise ValueError('Owner-specific path in public source: '+name)
        result.append(path)
    return tuple(result)


def prepare(root,output):
    files=source_files(root);version=tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
    prefix='L4D2WorkshopCollectionManager-'+version+'-source';output.mkdir(exist_ok=True,parents=True)
    archive_path=output/(prefix+'.zip');manifest=[]
    with zipfile.ZipFile(archive_path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            data=path.read_bytes();name=path.relative_to(root).as_posix()
            info=zipfile.ZipInfo(prefix+'/'+name,(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=(stat.S_IFREG|0o644)<<16
            archive.writestr(info,data);manifest.append(dict(path=name,sha256=hashlib.sha256(data).hexdigest()))
        info=zipfile.ZipInfo(prefix+'/PUBLIC_SOURCE_MANIFEST.json',(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
        archive.writestr(info,json.dumps(dict(version=version,files=manifest,license='MIT'),indent=2).encode())
    checksum=hashlib.sha256(archive_path.read_bytes()).hexdigest();archive_path.with_suffix('.zip.sha256').write_text(checksum+'  '+archive_path.name+'\n',encoding='ascii')
    return dict(archive=str(archive_path),sha256=checksum,files=len(files),license_pending=False,published=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',default='dist');args=parser.parse_args()
    print(json.dumps(prepare(Path(__file__).resolve().parents[1],Path(args.output)),indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
