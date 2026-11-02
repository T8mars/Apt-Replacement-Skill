"""Local APT run preparation and installation checks. Never calls RunningHub."""
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, sys

SKILL=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(SKILL/'assets/template'))
from apt_media_tools import resolve_tool


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')


def private_home():
    # Shared account state must not depend on whether the skill is installed
    # under .agents/skills or .codex/skills.
    return Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex').resolve()


def original_rows(template):
    text=(template/'补齐生成用/原始帧数.txt').read_text(encoding='utf-8-sig')
    return [(n,int(count)) for n,count in re.findall(r'(?m)^(\d{3})\.mp4\s+(\d+)\s*$',text)]


def check(skill=SKILL,source_only=False):
    skill=Path(skill).resolve();template=skill/'assets/template'
    manifest=read(skill/'manifest.json')
    assets=read(skill/'release-assets.json')['files'] if (skill/'release-assets.json').is_file() else {}
    missing=[]
    for relative,digest in manifest['files'].items():
        path=skill/relative
        if not path.resolve().is_relative_to(skill) or path.is_symlink():raise ValueError('Unsafe installed path')
        if not path.is_file():
            if source_only and relative in assets:
                missing.append(relative);continue
            raise FileNotFoundError('Complete skill asset missing: '+relative+'. Download the complete ZIP from GitHub Releases.')
        h=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
        if h.hexdigest()!=digest:raise ValueError('Installed member changed: '+relative)
    if source_only:
        return {'name':'apt-character-replacement','status':'source-code-verified','files_verified':len(manifest['files'])-len(missing),
                'release_assets_missing':len(missing),'complete_install_required':bool(missing),'cloud_calls':0}
    rows=original_rows(template)
    if [n for n,c in rows]!=[f'{i:03d}' for i in range(1,45)] or sum(c for n,c in rows)!=2316:
        raise ValueError('Original source ownership table differs from44segments/2316frames')
    for n,c in rows:
        videos=list((template/'补齐生成用').glob(n+' *.mp4'))
        if len(videos)!=1 or not (template/f'补齐生成用/{n}.txt').is_file():raise ValueError('Missing/ambiguous source '+n)
        count=int(videos[0].stem.split()[1])
        if count<c or count/24>10:raise ValueError('Source/padded count invalid '+n)
    for name in ['rh_batch.py','apt_runtime.py','apt_media_tools.py','rh_core.py','review_media.py','assemble-reviewed.py','validate_prompts.py','原片音轨.m4a','替换用参考图/一号.png','替换用参考图/二号.png']:
        if not (template/name).is_file():raise ValueError('Missing template dependency '+name)
    tools={name:resolve_tool(template,name) for name in ['ffmpeg','ffprobe']}
    return {'name':'apt-character-replacement','display_name':'APT全自动人物替换复刻','segments':44,
            'generation_segments':40,'passthrough':['002','004','007','017'],'original_frames':2316,
            'concurrency':int((template/'并发数.txt').read_text().strip()),'files_verified':len(manifest['files']),
            'media_tools':tools,'cloud_calls':0,'status':'installed-template-verified'}


def initialize(project,references=None,key_file=None,skill=SKILL):
    project=Path(project).resolve();skill=skill.resolve();template=skill/'assets/template'
    if project.is_relative_to(skill) or skill.is_relative_to(project):raise ValueError('Use a run outside the skill folder')
    if project.exists() and any(project.iterdir()):raise FileExistsError('Use a new empty run directory')
    refs=[Path(p).resolve() for p in references or []]
    if refs and len(refs)!=2:raise ValueError('Exactly two current reference images required')
    if any(not p.is_file() for p in refs):raise FileNotFoundError('Reference image missing')
    if key_file:
        key_file=Path(key_file).resolve()
        if key_file.is_relative_to(skill) or key_file.is_relative_to(project):raise ValueError('Key must stay outside skill and run')
        if not key_file.is_file():raise FileNotFoundError('Private key file missing')
    else:
        home=private_home()
        choices=[home/'private/apt-character-replacement/api_key.txt',home/'private/r2va-character-replacement/api_key.txt']
        key_file=next((p for p in choices if p.is_file()),choices[0])
    key_file=key_file.resolve()
    if key_file.is_relative_to(skill) or key_file.is_relative_to(project):raise ValueError('Key must stay outside skill and run')
    check(skill)
    size=sum(p.stat().st_size for p in template.rglob('*') if p.is_file())
    existing=project.parent
    while not existing.exists():existing=existing.parent
    if shutil.disk_usage(existing).free<size+256*1024*1024:raise OSError('Insufficient space for a complete independent run')
    shutil.copytree(template,project,dirs_exist_ok=True)
    shutil.copytree(skill/'references',project/'技能参考',dirs_exist_ok=True)
    (project/'提示词').mkdir(exist_ok=True);(project/'完成分段').mkdir(exist_ok=True)
    for image,name in zip(refs,['一号.png','二号.png']):shutil.copy2(image,project/'替换用参考图'/name)
    home=private_home()
    (project/'制作分析').mkdir(exist_ok=True)
    write(project/'runtime.json',{'api_key_file':str(key_file),'reference_selection':'provided-two' if refs else 'pending',
        'installed_skill_directory':str(skill),'ledger_file':str(home/'private/video-replacement-skill-factory/tasks.sqlite'),
        'account_alias':'default','production_authorized':False,'production_request':'','approved_segments':[],
        'ffmpeg_path':resolve_tool(project,'ffmpeg'),'ffprobe_path':resolve_tool(project,'ffprobe'),
        'cloud_submitted':False})
    return {'project':str(project),'status':'prepared-not-submitted','references':'provided-two' if refs else 'pending',
            'api_key_file':str(key_file),'cloud_calls':0}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('command',choices=['check','init'])
    ap.add_argument('--project');ap.add_argument('--references',nargs=2);ap.add_argument('--key-file')
    ap.add_argument('--source-only',action='store_true',help='Verify source checkout; report missing complete-package assets')
    args=ap.parse_args()
    if args.command=='init':
        if args.source_only:ap.error('--source-only is only valid with check')
        if not args.project:ap.error('init requires --project')
        result=initialize(args.project,args.references,args.key_file)
    else:result=check(source_only=args.source_only)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
