"""Select one provider per production and keep paid attempts recoverable."""
import argparse
from contextlib import contextmanager
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import tempfile

import rh_core as core

REVISION = 'wfr_ff47d851972485d1a6a0'
PROVIDERS = ('rh', 'zhenzhen', 'chenyu')


def api(provider):
    if provider == 'zhenzhen':
        import zhenzhen_runner as module
    elif provider == 'chenyu':
        import chenyu_runner as module
    else:
        raise ValueError('Expected zhenzhen or chenyu')
    return module


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def selected(root):
    marker = root / 'channel.json'
    name = read(marker)['provider'] if marker.is_file() else 'rh'
    if name not in PROVIDERS:
        raise ValueError('Unknown production channel')
    return name


def private_file(root, path):
    path = Path(path).expanduser().resolve()
    excluded = [root.resolve()]
    if (root / 'runtime.json').is_file():
        installed = read(root / 'runtime.json').get('installed_skill_directory')
        if installed:
            excluded.append(Path(installed).resolve())
    if any(path.is_relative_to(folder) for folder in excluded):
        raise ValueError('Store private files outside production and skill folders')
    return path


def configure(root, provider, key_file=None):
    if provider not in PROVIDERS or provider == 'rh' and key_file:
        raise ValueError('Use native RH credentials for the rh route')
    config = {'provider': provider}
    if key_file:
        config['key_file'] = str(private_file(root, key_file))
    marker = root / 'channel.json'
    if marker.exists():
        if read(marker) != config:
            raise ValueError('Create a new production to switch channels or credentials')
        return
    if provider != 'rh':
        for name in ('rh_state.json', 'production-status.json'):
            state = root / name
            if state.is_file() and read(state).get('tasks'):
                raise ValueError('Existing paid tasks belong to this production; start a new one')
        # A crash can precede the first status snapshot.
        cfg_file = root / 'runtime.json'
        if cfg_file.is_file():
            import sqlite3
            cfg = read(cfg_file)
            db = Path(cfg.get('ledger_file') or core.default_private() / 'tasks.sqlite')
            if db.is_file():
                from contextlib import closing
                with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True)) as conn:
                    if conn.execute('SELECT 1 FROM attempts WHERE project=? LIMIT 1', (str(root.resolve()),)).fetchone():
                        raise ValueError('This production already has an RH billing record')
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as temp:
        path = Path(temp.name)
        temp.write(json.dumps(config, ensure_ascii=False, indent=2).encode())
    try:
        os.link(path, marker)
    except FileExistsError:
        if read(marker) != config:
            raise ValueError('Another process selected a different channel')
    finally:
        path.unlink(missing_ok=True)


def profile(name):
    module = api(name)
    if name == 'chenyu':
        return {'kind': module.KIND, 'workflow_id': module.WORKFLOW,
                'revision_id': REVISION, 'output_name': module.OUTPUT}
    return {'kind': module.KIND, 'model': module.MODEL, 'resolution': '1088p', 'ratio': 'auto'}


def wire_frames(root, entry, roles):
    name = selected(root)
    if entry['profile']['kind'] != api(name).KIND:
        raise ValueError('Queue profile and production channel disagree')
    fps = Fraction(str(entry['generation_fps']))
    frames = entry['generation_frames']
    if type(frames) is not int or frames < 1 or fps not in (24, Fraction(24000, 1001)) or frames / fps > 10:
        raise ValueError('Source must be a positive, at most 10-second 24/23.976 fps template shot')
    if name == 'chenyu' and entry['profile'].get('revision_id') != REVISION:
        raise ValueError('Chenyu revision differs from the verified workflow')
    target = api(name).frame_count(frames)
    window = {'generation_frames': target, 'generation_fps': 24, 'duration': str(Fraction(target, 24))}
    api(name).validate_window(entry['profile'], window, roles)
    return target


def tool(root, name):
    from apt_media_tools import resolve_tool
    return resolve_tool(root,name)


def probe(root, path):
    result = subprocess.check_output([tool(root, 'ffprobe'), '-v', 'error', '-count_frames',
        '-show_entries', 'stream=codec_type,avg_frame_rate,nb_read_frames', '-of', 'json', str(path)])
    streams = json.loads(result)['streams']
    video = next(s for s in streams if s['codec_type'] == 'video')
    return int(video['nb_read_frames']), Fraction(video['avg_frame_rate']), any(s['codec_type']=='audio' for s in streams)


@contextmanager
def submission_video(root, entry, target):
    video = core.asset(root, entry['video_path'])
    frames, fps, audio = probe(root, video)
    if (frames, fps) != (entry['generation_frames'], Fraction(str(entry['generation_fps']))):
        raise ValueError('Decoded source differs from its approved frame count or frame rate')
    if frames == target and fps == 24:
        yield video
        return
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'motion.mp4'
        filters = f'settb=1/24,setpts=N,tpad=stop_mode=clone:stop={target-frames},trim=end_frame={target},setpts=N'
        cmd = [tool(root,'ffmpeg'), '-v','error','-nostdin','-i',str(video),'-map','0:v:0',
               '-filter_threads','1','-vf',filters,'-r','24','-c:v','libx264','-crf','16','-pix_fmt','yuv420p']
        if audio:
            cmd += ['-map','0:a:0','-af',f'apad,atrim=duration={target/24:.9f}','-c:a','aac']
        subprocess.run(cmd + ['-movflags','+faststart',str(path)], check=True)
        if probe(root, path)[:2] != (target, 24):
            raise ValueError('Prepared motion does not cover the complete frame plan')
        yield path


def ledger_path(root, provider):
    return private_file(root, core.default_private() / (provider + '.sqlite'))


def account_for(provider, alias='default'):
    return alias if provider == 'rh' else provider + ':' + alias


def make_runner(root, ledger, account, verifier=None):
    name = selected(root)
    config = read(root / 'channel.json')
    env, filename = ('CHENYU_API_KEY_FILE','chenyu_workflow.key') if name == 'chenyu' else ('ZZ_API_KEY_FILE','seedance_charswap.key')
    path = private_file(root, config.get('key_file') or os.environ.get(env) or core.codex_home()/'secrets'/filename)
    key = path.read_text(encoding='utf-8-sig').strip()
    if not key or len(key.splitlines()) != 1:
        raise ValueError('Expected one private credential in the selected key file')
    transport = api(name).Transport(key)
    if verifier:
        transport._verify_download = verifier
    return AlternateRunner(ledger, transport, account)


class AlternateRunner(core.Runner):
    def submit_one(self, project, entry, validator):
        root = Path(project).resolve()
        name = selected(root)
        if self.transport.provider != name or not self.account.startswith(name + ':'):
            raise ValueError('Transport/account channel mismatch')
        digest = validator(root, entry)
        prior = self.ledger.db.execute('SELECT digest,state FROM attempts WHERE account=? AND project=? AND window=? ORDER BY created DESC,rowid DESC LIMIT 1',
            (self.account,str(root),entry['window_id'])).fetchone()
        if prior:
            if prior['digest'] != digest:
                raise ValueError('Create a new candidate ID for changed inputs')
            if prior['state'] not in ('DEFERRED','EXECUTION_FAILED','VISUAL_FAILED'):
                return None
        module = api(name)
        refs = [core.asset(root, path) for path in entry['reference_paths']]
        target = wire_frames(root, entry, entry['reference_paths'])
        prompt = core.asset(root, entry['prompt_path']).read_text(encoding='utf-8-sig')
        selected_profile = entry['profile']
        quote = self.transport.inspect_route(selected_profile,len(refs)) if name == 'chenyu' else None
        with submission_video(root, entry, target) as motion:
            if name == 'zhenzhen':
                module.validate_files(refs, motion)
            images = [self.transport.upload(ref) for ref in refs]
            body = module.payload(selected_profile, prompt, images, self.transport.upload(motion), target)
        if name == 'zhenzhen':
            quote = self.transport.estimate(body)
            estimate = module.data_of(quote)
            if not isinstance(estimate, dict) or not estimate or estimate.get('confirmation_required') or quote.get('error') or estimate.get('error'):
                raise ValueError('Provider estimate unavailable or requires confirmation')
        if validator(root,entry) != digest:
            raise ValueError('Inputs changed during upload')
        path = module.SUBMIT if name == 'chenyu' else module.GENERATIONS
        intent = dict(path=path, body=body, estimate=quote, key_fingerprint=self.key_fingerprint())
        aid = self.ledger.reserve(self.account,root,entry['window_id'],digest,entry.get('retry_after'),
                                  request=json.dumps(intent,ensure_ascii=False))
        if aid:
            self.post(aid,intent)
        return aid

    def recover(self, aid, defer_download=False):
        row = self.ledger.row(aid)
        intent = json.loads(row['request'])
        if row['account'] != self.account or intent.get('key_fingerprint') != self.key_fingerprint():
            raise ValueError('Recover this paid attempt using its original account credential')
        return super().recover(aid, defer_download=defer_download)

    def post(self, aid, intent):
        try:
            result = self.transport.submit(intent['path'],intent['body'])
        except core.ApiFailure as exc:
            if exc.code in ('400','401','402','403','422') + core.DEFERRED_CODES:
                self.submission_rejected(aid,exc.code)
                if exc.code in ('401','402','403'):
                    self.ledger.stop(self.account)
            else:
                self.ledger.update(aid,state='SUBMISSION_UNKNOWN')
            return
        except Exception:
            self.ledger.update(aid,state='SUBMISSION_UNKNOWN')
            return
        if result.get('taskId'):
            self.ledger.update(aid,state='RUNNING',task_id=str(result['taskId']),receipt=json.dumps(result),next_poll=self.ledger.clock()+5)
        else:
            self.ledger.update(aid,state='SUBMISSION_UNKNOWN',receipt=json.dumps(result))

    def reconcile(self, root, aid, task_id):
        row = self.ledger.row(aid)
        if not row or row['project'] != str(root.resolve()) or row['account'] != self.account or row['state'] not in ('SUBMITTING','SUBMISSION_UNKNOWN'):
            raise ValueError('Expected an unresolved attempt in this production and account')
        intent = json.loads(row['request'])
        if intent['key_fingerprint'] != self.key_fingerprint():
            raise ValueError('Use the same credential as the original submission')
        if self.transport.provider == 'chenyu' and not task_id:
            self.post(aid, intent)
        elif self.transport.provider == 'zhenzhen' and task_id:
            receipt = self.transport.query(task_id)
            if receipt.get('taskId') != task_id or receipt.get('status') not in ('QUEUED','RUNNING','SUCCESS','FAILED'):
                raise ValueError('Provider did not confirm this task ID')
            if self.ledger.db.execute('SELECT 1 FROM attempts WHERE account=? AND task_id=?',(self.account,task_id)).fetchone():
                raise ValueError('Task ID already bound to an attempt')
            self.ledger.update(aid,state='RUNNING',task_id=task_id,next_poll=0)
        else:
            raise ValueError('Chenyu replays the original idempotency key; Zhenzhen requires a verified task ID')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    select = commands.add_parser('select')
    select.add_argument('--provider', choices=PROVIDERS, required=True)
    select.add_argument('--key-file')
    rec = commands.add_parser('reconcile')
    rec.add_argument('--attempt',required=True)
    rec.add_argument('--task-id')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.command == 'select':
        configure(root,args.provider,args.key_file)
        print('Provider:',selected(root))
        return
    name = selected(root)
    if name == 'rh':
        raise ValueError('Use the native RunningHub recovery procedure')
    config = read(root/'runtime.json') if (root/'runtime.json').is_file() else {}
    ledger = core.Ledger(ledger_path(root,name))
    try:
        make_runner(root,ledger,account_for(name,config.get('account_alias','default'))).reconcile(root,args.attempt,args.task_id)
    finally:
        ledger.close()


if __name__ == '__main__':
    main()
