"""Background final-file review evidence and byte-identical original AAC prefix check."""
from pathlib import Path
import json,hashlib,av
from PIL import Image,ImageDraw
R=Path(__file__).parent;E=R/'制作分析';P=R
v=json.loads((E/'assembly-verification.json').read_text());plan=json.loads((E/'assembly-frame-plan.json').read_text());out=Path(v['path']);assert hashlib.sha256(out.read_bytes()).hexdigest()==v['sha256']
d=E/'final-assembly-review';d.mkdir(exist_ok=False);rows=plan['segments'];needed={0,2315}
for row in rows:needed.update([row['first_frame'],row['first_frame']+1,row['end_frame_exclusive']-2,row['end_frame_exclusive']-1])
frames={}
with av.open(str(out)) as c:
 c.streams.video[0].codec_context.thread_count=1
 for i,f in enumerate(c.decode(video=0)):
  if i in needed:frames[i]=f.to_image()
assert len(frames)==len(needed)
for start in range(0,43,6):
 indices=list(range(start,min(start+6,43)));page=Image.new('RGB',(1536,len(indices)*242),'#202020');dr=ImageDraw.Draw(page)
 for j,k in enumerate(indices):
  cut=rows[k]['end_frame_exclusive'];nums=[cut-2,cut-1,cut,cut+1]
  for col,n in enumerate(nums):page.paste(frames[n].resize((384,216)),(col*384,j*242+26))
  dr.text((4,j*242+4),f"Join {rows[k]['segment']} -> {rows[k+1]['segment']}; final frames {nums}; {float(__import__('fractions').Fraction(rows[k+1]['start_seconds'])):.3f}s",fill='white')
 page.save(d/f'joins-{start:02d}.png')
for n in ['001','003','009','011','023','030','040','041','044']:
 row=next(x for x in rows if x['segment']==n)
 for name,index in [('first',row['first_frame']),('last',row['end_frame_exclusive']-1)]:frames[index].save(d/f'{n}-{name}-native.png')
def audio_packets(path):
 with av.open(str(path)) as c:
  stream=c.streams.audio[0];extra=stream.codec_context.extradata
  packets=[hashlib.sha256(bytes(p)).hexdigest() for p in c.demux(stream) if p.size]
 return extra,packets
oe,op=audio_packets(out);se,sp=audio_packets(P/'原片音轨.m4a');assert oe==se and op==sp[:len(op)]
report={'path':str(out),'sha256':v['sha256'],'all43_join_boards':'prepared, visual inspection pending','native_final_samples':'18 actual1920x1080 endpoint frames prepared','original_audio_packet_prefix':'byte-identical AAC packet prefix verified','audio_packet_count':len(op),'actual1x_full_film':'pending user playback; no desktop opened'}
(d/'review-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print('All43 join boards and18native samples ready; original AAC packet prefix verified.')
