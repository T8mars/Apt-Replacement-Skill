"""APT-only publication guard for Git trees and complete licensed release bundles."""
from pathlib import Path,PurePosixPath
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

REPO='https://github.com/T8mars/Apt-Replacement-Skill'
NAME='apt-character-replacement'
MEDIA={'.mp4','.m4a','.png','.jpg','.jpeg'}
SECRETS=[re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{24,})\b'),
    re.compile(rb'''(?i)(?:api[_-]?key|access[_-]?token|secret[_-]?key)\s*["']?\s*[:=]\s*["'][A-Za-z0-9_-]{24,}["']'''),
    re.compile(rb'(?i)[?&](?:q-signature|x-amz-signature|x-cos-signature)=[a-f0-9]{24,}')]


def git(*args):
    result=subprocess.run(['git',*args],capture_output=True)
    if result.returncode:raise ValueError('Could not read APT Git metadata/tree')
    return result.stdout


def remote_ok(value):
    return value.strip().removesuffix('.git').rstrip('/') in (REPO,'git@github.com:T8mars/Apt-Replacement-Skill')


def private_path(name):
    parts=PurePosixPath(name).parts;lower=[p.casefold() for p in parts]
    return (not parts or name.startswith('/') or ':' in name or '\\' in name or '..' in parts or
        any(p=='roadmap.md' or p.startswith(('api_key','api-key','apikey','.env')) for p in lower) or
        any(p in ('private','_private','__pycache__','candidates','完成分段','制作分析') for p in lower) or
        lower[-1] in ('runtime.json','rh_state.json','production-status.json','approved-queue.json') or
        PurePosixPath(name).suffix.casefold() in {'.exe','.dll','.pyc','.sqlite','.db','.zip','.7z','.pem','.key'} or
        (lower[-1]=='skill.md' and name!='SKILL.md'))


def known_keys():
    result=[];value=os.environ.get('RH_API_KEY','').strip()
    if value:result.append(value.encode())
    home=Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex')
    for sub in ['apt-character-replacement','r2va-character-replacement']:
        folder=home/'private'/sub
        if folder.is_dir():
            for path in folder.glob('*key*.txt'):
                value=path.read_text(encoding='utf-8-sig').strip()
                if len(value)>=16:result.append(value.encode())
    return result


def check_files(files,complete=False,keys=()):
    errors=[]
    try:
        manifest=json.loads(files['manifest.json']);assets=json.loads(files['release-assets.json'])['files']
        meta=json.loads(files['meta.json']);policy=json.loads(files['publish-policy.json'])
        if manifest['name']!=NAME or meta['name']!=NAME or manifest['version']!=meta['version'] or policy['repository']!=REPO:
            errors.append('Wrong APT repository/name/version')
        declared_media={n for n in manifest['files'] if PurePosixPath(n).suffix.casefold() in MEDIA}
        if set(assets)!=declared_media:errors.append('Release asset inventory must exactly cover original media')
        for name,item in assets.items():
            if (not name.startswith('assets/template/') or item['sha256']!=manifest['files'].get(name) or
                item['sha256']!=manifest['original_package_sha256'].get(name.removeprefix('assets/template/'))):
                errors.append(name+': original-package asset provenance mismatch')
        expected=set(manifest['files'])|{'manifest.json'}
        if not complete:expected-=set(assets)
        if set(files)!=expected:errors.append('Publication does not exactly match APT manifest members')
        for name,data in files.items():
            if private_path(name):errors.append(name+': forbidden private/executable publication path')
            media=PurePosixPath(name).suffix.casefold() in MEDIA
            if media:
                original=name.removeprefix('assets/template/')
                digest=hashlib.sha256(data).hexdigest()
                if (not complete or name not in assets or assets[name]['sha256']!=digest or
                    assets[name]['size_bytes']!=len(data) or manifest['original_package_sha256'].get(original)!=digest):
                    errors.append(name+': media must be original-package bytes inside the complete licensed bundle only')
            elif any(k and k in data for k in keys) or any(p.search(data) for p in SECRETS):
                errors.append(name+': possible credential/signed URL; value suppressed')
            if name!='manifest.json' and hashlib.sha256(data).hexdigest()!=manifest['files'].get(name):
                errors.append(name+': manifest hash mismatch')
        if files['LICENSE.txt']!=files['assets/template/LICENSE.txt']:
            errors.append('Original author license must be retained unchanged')
        if hashlib.sha256(files['LICENSE.txt']).hexdigest()!=manifest['original_package_sha256']['LICENSE.txt']:
            errors.append('Original package license changed')
        readme=files['README.md']
        for value in [b'https://space.bilibili.com/670281046',b'https://space.bilibili.com/385085361',b'English guide',b'T8star',b'wuwukasi']:
            if value not in readme:errors.append('README is missing bilingual attribution/usage content')
    except (KeyError,ValueError,TypeError):errors.append('Publication metadata is missing/invalid')
    return sorted(set(errors))


def read_source(source,complete=False):
    source=Path(source).resolve();manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8-sig'))
    assets=json.loads((source/'release-assets.json').read_text(encoding='utf-8-sig'))['files']
    names=set(manifest['files'])|{'manifest.json'}
    if not complete:names-=set(assets)
    result={}
    for name in names:
        path=(source/name).resolve()
        if not path.is_relative_to(source) or path.is_symlink():raise ValueError('Unsafe source member')
        result[name]=path.read_bytes()
    errors=check_files(result,complete,known_keys())
    if errors:raise ValueError('\n'.join(errors))
    return result


def tree(revision=None):
    if revision is None:
        names=git('ls-files','--cached','-z').decode().split('\0')
        return {n:git('show',':'+n) for n in names if n}
    names=git('ls-tree','-r','--name-only','-z',revision).decode().split('\0')
    return {n:git('show',revision+':'+n) for n in names if n}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--staged',action='store_true');ap.add_argument('--revision')
    ap.add_argument('--pre-push',nargs=2);ap.add_argument('--source',type=Path);ap.add_argument('--complete',action='store_true');args=ap.parse_args()
    try:
        if args.source:
            files=read_source(args.source,args.complete)
            print('APT source/bundle publication verified:',len(files),'members; no cloud calls.');return 0
        if not remote_ok(git('remote','get-url','origin').decode()):raise ValueError('Wrong APT repository origin')
        revisions=[args.revision] if args.revision else [None]
        if args.pre_push:
            remote,url=args.pre_push
            if remote!='origin' or not remote_ok(url):raise ValueError('Wrong APT push destination')
            revisions=[]
            for line in sys.stdin.read().splitlines():
                local_ref,local_sha,remote_ref,remote_sha=line.split()
                if set(local_sha)=={'0'}:continue
                args_for_rev=(local_sha,'--not','--remotes=origin') if set(remote_sha)=={'0'} else (remote_sha+'..'+local_sha,)
                revisions+=git('rev-list',*args_for_rev).decode().splitlines()
            if not revisions:revisions=['HEAD']
        errors=[]
        for revision in dict.fromkeys(revisions):errors+=check_files(tree(revision),keys=known_keys())
        if errors:raise ValueError('\n'.join(sorted(set(errors))))
        print('APT publication verified: exact repository/manifest, attribution and private-data exclusions.');return 0
    except (OSError,ValueError) as error:
        print('APT publication blocked: '+str(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
