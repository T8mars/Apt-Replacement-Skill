"""Isolate strict H264 decoding from final x264 pressure, prove decoded-frame identity."""
from pathlib import Path
import json,subprocess,hashlib,concurrent.futures,av
from apt_media_tools import resolve_tool
R=Path(__file__).parent;E=R/'制作分析';P=R;FF=resolve_tool(P,'ffmpeg');rows=json.loads((E/'assembly-frame-plan.json').read_text())['segments'];d=E/'lossless-assembly-inputs';d.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def hashes(path,keep):
 for attempt in range(3):
  p=subprocess.run([str(FF),'-nostdin','-v','error','-xerror','-threads','1','-i',str(path),'-map','0:v:0','-an','-frames:v',str(keep),'-threads','1','-f','framemd5','-'],capture_output=True,timeout=180)
  if p.returncode==0 and not p.stderr:break
  print('Local strict-read retry',Path(path).name,attempt+1,flush=True)
 assert p.returncode==0 and not p.stderr,p.stderr.decode(errors='replace')
 vals=[x.rsplit(',',1)[-1].strip() for x in p.stdout.decode().splitlines() if not x.startswith('#')];assert len(vals)==keep
 return vals
def prepare(row):
 path=Path(row['input']);assert sha(path)==row['input_sha256']
 checkpoint=d/(row['segment']+'-'+row['input_sha256'][:16]+'-verified.json')
 if checkpoint.exists():
  saved=json.loads(checkpoint.read_text());assert saved['original_sha256']==row['input_sha256'] and sha(saved['decode_input'])==saved['decode_sha256'];return row['segment'],saved
 with av.open(str(path)) as c:codec=c.streams.video[0].codec_context.name
 if codec=='ffv1':return row['segment'],{'decode_input':str(path),'decode_sha256':row['input_sha256'],'method':'Already proven lossless selected derivative; no new conversion.'}
 out=d/(row['segment']+'-'+row['input_sha256'][:16]+'.mkv')
 if out.exists() and not checkpoint.exists():
  raise ValueError('Unverified leftover intermediate: preserve it and inspect before reuse')
 if not out.exists():
  cmd=[str(FF),'-nostdin','-v','error','-xerror','-threads','1','-i',str(path),'-map','0:v:0','-an','-frames:v',str(row['keep']),'-c:v','ffv1','-threads','1','-level','3','-n',str(out)]
  p=subprocess.run(cmd,capture_output=True,timeout=240);assert p.returncode==0 and not p.stderr,p.stderr.decode(errors='replace')
 original=hashes(path,row['keep']);decoded=hashes(out,row['keep']);assert original==decoded,(row['segment'],'decoded pixel owner mismatch')
 print(row['segment'],'lossless decoded-frame hashes match',len(original),flush=True)
 result={'decode_input':str(out),'decode_sha256':sha(out),'original_input':str(path),'original_sha256':row['input_sha256'],'frames':row['keep'],'decoded_framemd5':original,'method':'Native pixel format FFV1; decoded source frame hashes match, strict decoder errors enabled; no lossy encode.'}
 checkpoint.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');return row['segment'],result
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:result=dict(pool.map(prepare,rows))
(E/'lossless-assembly-inputs.json').write_text(json.dumps({'inputs':result,'strict_errors':True,'lossy_encodes':0},ensure_ascii=False,indent=2),encoding='utf8')
print('All44 lossless assembly inputs verified; no cloud calls.')
