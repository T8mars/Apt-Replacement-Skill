"""APT production adapter. check/prepare/status are offline; run uses immutable approvals."""
from pathlib import Path
from fractions import Fraction
import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import rh_core as rh
import rh_batch as source
from apt_media_tools import resolve_tool

P = Path(__file__).resolve().parent
TERMINAL = ('DOWNLOADED', 'VISUAL_FAILED', 'RESULTS_MISSING')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(temp, path)


def private_path(value):
    path = Path(value).resolve()
    skill = read(P/'runtime.json').get('installed_skill_directory')
    if path.is_relative_to(P) or skill and path.is_relative_to(Path(skill).resolve()):
        raise ValueError('Credentials and account ledger must stay outside run and skill')
    return path


def ledger_path():
    return private_path(read(P/'runtime.json').get('ledger_file') or rh.default_private()/'tasks.sqlite')


def key():
    if os.environ.get('RH_API_KEY', '').strip():
        return os.environ['RH_API_KEY'].strip()
    path = private_path(os.environ.get('RH_API_KEY_FILE') or read(P/'runtime.json')['api_key_file'])
    value = path.read_text(encoding='utf-8-sig').strip()
    if not value:
        raise ValueError('Private RunningHub key is empty')
    return value


def original_segment(entry):
    segment = entry.get('source_segment', entry['window_id'])
    if segment not in source.CAST:
        raise ValueError('Unknown generation segment, or passthrough segment')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', entry['window_id']):
        raise ValueError('Candidate ID must be a plain directory name')
    return segment


def input_digest(project, entry):
    project = Path(project).resolve()
    segment = original_segment(entry)
    files = [entry['video_path'], entry['prompt_path'], entry['schema_path'],
             *entry['reference_paths'], f'补齐生成用/{segment}.txt']
    files += [f'替换用参考图/{role}号.png' for role in source.CAST[segment]]
    original = list((project/'补齐生成用').glob(segment+' *.mp4'))
    if len(original) != 1:
        raise ValueError('Ambiguous source segment')
    files.append(original[0].relative_to(project).as_posix())
    if entry.get('source_contract_path'):
        contract = read(rh.asset(project, entry['source_contract_path']))
        files += [entry['source_contract_path'], *contract.get('dependency_paths', [])]
    return rh.digest_object({'files': {name: rh.sha(rh.asset(project, name)) for name in sorted(set(files))},
        'contract': {k: v for k, v in entry.items() if k not in ('input_digest', 'semantic_review', 'retry_after')},
        'cast': source.CAST[segment], 'application_config': source.app_config()})


def validate(project, entry, require_approval=True):
    project = Path(project).resolve()
    if project != P:
        raise ValueError('Run path mismatch')
    cfg = read(P/'runtime.json')
    segment = original_segment(entry)
    if cfg.get('reference_selection') != 'provided-two':
        raise ValueError('Current two identities have not been selected')
    roles = source.CAST[segment]
    expected = [f'替换用参考图/{role}号.png' for role in roles]
    if len(entry['reference_paths']) != len(expected):
        raise ValueError('Partial edge roles still require their reference slot')
    if entry['profile']['kind'] != 'legacy-ai-app':
        raise ValueError('This adapter only implements the verified RunningHub AI application')
    if source.app_config()['模式'] != 'ai':
        raise ValueError('CN endpoint requires a separately verified transport; do not silently use AI')
    app = '2107845954833907713' if len(roles) == 2 else '2107844752011010050'
    if entry['profile']['app_id'] != app:
        raise ValueError('Application does not match role count')
    rh.legacy_resolution_nodes(entry['profile'])
    fields = {(str(x['nodeId']), x['fieldName']) for x in read(rh.asset(P, entry['schema_path']))['data']['nodeInfoList']}
    required = {('137','image'), ('138','value'), ('321','video'), ('326','value')}
    required |= {(n['nodeId'], n['fieldName']) for n in rh.legacy_resolution_nodes(entry['profile'])}
    if len(roles) == 2:
        required.add(('139','image'))
    if not required <= fields:
        raise ValueError('Public schema no longer supports required fields')
    for uploaded, full in zip(entry['reference_paths'], expected):
        if uploaded == full:
            continue
        crop = entry.get('reference_crops', {}).get(uploaded, {})
        if crop.get('source_path') != full or crop.get('source_sha256') != rh.sha(rh.asset(P, full)):
            raise ValueError('Reference crop lost original identity/order provenance')
        from PIL import Image
        with Image.open(rh.asset(P, full)) as original, Image.open(rh.asset(P, uploaded)) as actual:
            box = crop['crop']
            if len(box) != 4 or not all(type(x) is int for x in box) or not 0 <= box[0] < box[2] <= original.width or not 0 <= box[1] < box[3] <= original.height:
                raise ValueError('Invalid raw-pixel crop')
            wanted = original.convert('RGB').crop(tuple(box))
            if actual.size != wanted.size or actual.convert('RGB').tobytes() != wanted.tobytes():
                raise ValueError('Reference crop is not exact original pixels')
    frames = entry['generation_frames']
    fps = Fraction(str(entry['generation_fps']))
    if type(frames) is not int or frames <= 0 or fps <= 0 or Fraction(frames)/fps > 10:
        raise ValueError('COMPLETE input, including context/holds, must be <=10seconds')
    original = next((P/'补齐生成用').glob(segment+' *.mp4'))
    if rh.asset(P, entry['video_path']) != original:
        if not entry.get('source_contract_path'):
            raise ValueError('Derived input requires its source/action contract')
        contract = read(rh.asset(P, entry['source_contract_path']))
        if contract.get('source_segment') != segment or not contract.get('method') or not contract.get('action_frames'):
            raise ValueError('Derived input must declare source, method and real action frames')
        if contract.get('source_action_review') != 'passed':
            raise ValueError('Context/holds/pose guides require explicit source action review')
    digest = input_digest(P, entry)
    if entry.get('input_digest') != digest:
        raise ValueError('Inputs changed; prepare and review the new immutable candidate')
    if require_approval:
        review = entry.get('semantic_review') or {}
        if cfg.get('production_authorized') is not True or not cfg.get('production_request'):
            raise ValueError('Record the existing user production request first')
        if entry['window_id'] not in cfg.get('approved_segments', []):
            raise ValueError('Candidate is not in the current approved queue')
        if review.get('status') != 'passed' or review.get('input_digest') != digest or not review.get('notes'):
            raise ValueError('Current digest-bound semantic review is missing')
    return digest


def media_check(entry):
    import av
    path = rh.asset(P, entry['video_path'])
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.codec_context.thread_count = 1
        timestamps = [Fraction(frame.pts)*frame.time_base if frame.pts is not None else None for frame in container.decode(stream)]
        fps = Fraction(str(entry['generation_fps']))
        if len(timestamps) != entry['generation_frames'] or stream.average_rate != fps:
            raise ValueError('Actual full input frame clock differs from declared clock')
        if not timestamps or any(t is None for t in timestamps) or any(t-timestamps[0] != Fraction(i)/fps for i,t in enumerate(timestamps)):
            raise ValueError('Complete input PTS must follow its declared constant frame clock')
        if timestamps[-1]-timestamps[0]+1/fps > 10:
            raise ValueError('Actual input duration exceeds10seconds')
    with av.open(str(path)) as container:
        if not container.streams.audio or next(container.decode(audio=0), None) is None:
            raise ValueError('Input must have decodable audio, including derived/cropped inputs')
    result = subprocess.run([resolve_tool(P,'ffmpeg'), '-nostdin','-v','error','-xerror','-threads','1',
        '-i',str(path),'-map','0:v:0','-map','0:a:0','-threads','1','-f','null','-'], capture_output=True, timeout=180)
    if result.returncode or result.stderr.strip():
        raise ValueError('Complete input strict decode failed')


class StrictTransport(rh.Transport):
    @staticmethod
    def _verify_download(path):
        for _ in range(3):
            result = subprocess.run([resolve_tool(P,'ffmpeg'),'-nostdin','-v','error','-xerror',
                '-threads','1','-i',str(path),'-map','0:v:0','-threads','1','-f','null','-'], capture_output=True, timeout=180)
            if result.returncode == 0 and not result.stderr.strip():
                return
        raise ValueError('Strict download decode failed; preserve original paid task ID')


class FreshAssetRunner(rh.Runner):
    def upload(self, path, semantics):
        # Temporary node321 handles have expired before the old six-hour TTL.
        # Only NEW submissions upload fresh bytes. recover() never submits.
        return self.transport.upload(path)


def latest(ledger, account, window):
    return ledger.db.execute('SELECT * FROM attempts WHERE account=? AND project=? AND window=? ORDER BY created DESC,rowid DESC LIMIT 1',
        (account, str(P), window)).fetchone()


def tick(ledger, runner, entries, account='default'):
    # Query -> refill paid execution slots -> transfer. Large downloads do not starve generation.
    rows = ledger.db.execute('SELECT id FROM attempts WHERE account=? AND project=? AND state IN (?,?,?,?,?,?)',
        (account, str(P), *rh.POLLABLE)).fetchall()
    for row in rows:
        runner.recover(row['id'], defer_download=True)
    unknown = ledger.db.execute("SELECT 1 FROM attempts WHERE account=? AND state IN ('SUBMITTING','SUBMISSION_UNKNOWN')", (account,)).fetchone()
    if not unknown:
        for entry in entries:
            a = ledger.account(account)
            if a['stopped'] or a['cooldown'] > ledger.clock() or ledger.summary(account)['active'] >= 3:
                break
            prior = latest(ledger, account, entry['window_id'])
            if prior and prior['digest'] != entry['input_digest']:
                raise ValueError('Never mutate an existing candidate ID; use a new candidate revision')
            if prior and prior['state'] in (*rh.ACTIVE, *rh.POLLABLE, *TERMINAL):
                continue
            try:
                aid = runner.submit_one(P, entry, validate)
                if aid and ledger.row(aid)['state'] in ('SUBMITTING','SUBMISSION_UNKNOWN'):
                    unknown = True
                    break
            except rh.ApiFailure as error:
                if error.code in rh.DEFERRED_CODES:
                    ledger.cooldown(account)
                    break
                if error.code in ('401','402','403','1913'):
                    ledger.stop(account)
                raise
            except (urllib.error.URLError, TimeoutError):
                ledger.cooldown(account)
                break
    rows = ledger.db.execute("SELECT id FROM attempts WHERE account=? AND project=? AND state IN ('RESULTS_READY','DOWNLOAD_FAILED') AND next_poll<=?",
        (account, str(P), ledger.clock())).fetchall()
    for row in rows:
        runner.recover(row['id'])
    return bool(unknown)


def snapshot(ledger, account='default'):
    rows = ledger.db.execute('SELECT id,window,state,task_id,output,digest,query_errors,download_errors FROM attempts WHERE account=? AND project=? ORDER BY created,rowid', (account,str(P))).fetchall()
    tasks = {r['window']: dict(r) for r in rows}
    a = ledger.account(account)
    state = {'tasks': tasks, 'account_cap': a['cap'], 'account_active': ledger.summary(account)['active'],
        'account_stopped': bool(a['stopped']), 'cooldown_seconds': max(0,int(a['cooldown']-ledger.clock())),
        'updated_epoch': ledger.clock()}
    write(P/'production-status.json', state)
    return state


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=['prepare','check','status','run'])
    ap.add_argument('--once', action='store_true')
    args = ap.parse_args(argv)
    if args.command in ('prepare','check'):
        queue = read(P/'approved-queue.json')
        ids = [entry['window_id'] for entry in queue['jobs']]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate candidate ID')
        for entry in queue['jobs']:
            if args.command == 'prepare':
                entry['input_digest'] = input_digest(P, entry)
                entry['semantic_review'] = {'status':'pending', 'input_digest':entry['input_digest']}
            validate(P, entry, require_approval=args.command == 'check')
            media_check(entry)
        if args.command == 'prepare':
            write(P/'approved-queue.json', queue)
        print(json.dumps({'jobs':len(ids), 'cloud_calls':0, 'semantic_review':'pending' if args.command=='prepare' else 'passed'}))
        return
    cfg = read(P/'runtime.json')
    account = cfg.get('account_alias', 'default')
    ledger = rh.Ledger(ledger_path())
    try:
        if ledger.account(account)['cap'] != 3:
            raise ValueError('Shared account concurrency must be exactly three')
        if args.command == 'status':
            print(json.dumps(snapshot(ledger, account), ensure_ascii=False))
            return
        # Queue may only grow by appending complete, independently reviewed candidates.
        import msvcrt
        with (P/'.dispatcher.lock').open('a+b') as lock:
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            runner = FreshAssetRunner(ledger, StrictTransport(key()), account)
            loaded = []
            while True:
                entries = read(P/'approved-queue.json')['jobs']
                if entries[:len(loaded)] != loaded:
                    raise ValueError('Loaded queue entries changed; keep accepted inputs immutable')
                for entry in entries[len(loaded):]:
                    digest = validate(P, entry)
                    prior = latest(ledger, account, entry['window_id'])
                    if prior and prior['digest'] != digest:
                        raise ValueError('Accepted candidate inputs changed')
                    # Unchanged accepted inputs already passed the complete media check.
                    # Restarts rehash them, then recover the same paid task promptly.
                    if not prior or not prior['task_id']:
                        media_check(entry)
                    if any(old['window_id'] == entry['window_id'] for old in loaded):
                        raise ValueError('Duplicate candidate ID')
                    loaded.append(entry)
                unknown = tick(ledger, runner, entries, account)
                state = snapshot(ledger, account)
                print(json.dumps({'active':state['account_active'], 'cap':3, 'cooldown':state['cooldown_seconds'],
                    'states':{n:r['state'] for n,r in state['tasks'].items()}}, ensure_ascii=False), flush=True)
                if args.once or unknown or state['account_stopped'] or not entries:
                    return
                if all(state['tasks'].get(e['window_id'], {}).get('state') in TERMINAL for e in entries):
                    return
                # Three repeated execution failures call for inspection, not a visual retry limit.
                if any(ledger.db.execute('SELECT 1 FROM failures WHERE account=? AND project=? AND window=? AND count>=3',
                    (account,str(P),e['window_id'])).fetchone() for e in entries):
                    return
                time.sleep(12)
    finally:
        ledger.close()


if __name__ == '__main__':
    main()
