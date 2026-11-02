"""Strict non-scalar decoding preflight for every selected source, no video mutation."""
from pathlib import Path
import json,subprocess,concurrent.futures
from apt_media_tools import resolve_tool
R=Path(__file__).parent;E=R/'制作分析';P=R;rows=json.loads((E/'assembly-frame-plan.json').read_text())['segments'];FF=resolve_tool(P,'ffmpeg')
def check(row):
 p=subprocess.run([str(FF),'-nostdin','-v','error','-xerror','-threads','1','-i',row['input'],'-map','0:v:0','-an','-frames:v',str(row['keep']),'-threads','1','-f','null','-'],capture_output=True,timeout=180)
 return {'segment':row['segment'],'returncode':p.returncode,'stderr':p.stderr.decode('utf8',errors='replace'),'keep':row['keep'],'input_sha256':row['input_sha256']}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 results=list(pool.map(check,rows))
(E/'strict-normal-decoder-preflight.json').write_text(json.dumps({'ffmpeg':str(FF),'cpu_flags':'normal auto-detected CPU; scalar H264 CABAC compatibility failure diagnosed separately','strict_xerror':True,'segments':results},ensure_ascii=False,indent=2),encoding='utf8')
bad=[x for x in results if x['returncode'] or x['stderr']]
print('Strict normal-CPU decode:',len(results),'segments;',len(bad),'errors')
for x in bad:print(x['segment'],x['stderr'])
assert not bad
