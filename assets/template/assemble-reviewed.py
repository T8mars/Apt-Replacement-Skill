"""Single video encode, exact original-frame ownership, native-aspect fitting, original AAC audio."""
from pathlib import Path
from fractions import Fraction
import argparse,hashlib,json,os,subprocess,shutil
import ctypes
import av
from PIL import Image
from apt_media_tools import resolve_tool
R=Path(__file__).parent;P=R;E=R/'制作分析';FPS=Fraction(24000,1001)
FF=resolve_tool(P,'ffmpeg');PROBE=resolve_tool(P,'ffprobe')
ENC=str(Path(json.loads((P/'runtime.json').read_text(encoding='utf-8-sig')).get('encoder_path',FF)))
PASS={'002','004','007','017'};W,H=1920,1080
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
def launch(cmd,**kwargs):
    proc=subprocess.Popen(cmd,**kwargs)
    if os.name=='nt':
        # Restrict this task's own child processes only; no global computer settings.
        count=os.cpu_count();mask=sum(1<<i for i in range(max(0,count-4),count))
        fn=ctypes.windll.kernel32.SetProcessAffinityMask;fn.argtypes=[ctypes.c_void_p,ctypes.c_size_t];fn.restype=ctypes.c_int
        assert fn(int(proc._handle),mask),'Could not constrain own video process affinity'
    return proc
def table():
    rows=[]
    for line in (P/'补齐生成用/原始帧数.txt').read_text(encoding='utf-8-sig').splitlines():
        a=line.split()
        if len(a)==2 and a[0].endswith('.mp4'):rows.append((a[0][:3],int(a[1])))
    assert len(rows)==44 and sum(x[1] for x in rows)==2316
    return rows
def strict_rgb_frames(row):
    # Preserve strict errors, use the decoder's normal CPU path: forced scalar
    # H264 CABAC failed on001/008 while normal decoding passes. FFV1 local
    # repair pixel proofs remain separately verified with their canonical path.
    cmd=[FF,'-nostdin','-v','error','-xerror','-threads','1','-filter_threads','1',
        '-i',row.get('decode_input',row['input']),'-map','0:v:0','-an','-sn','-dn','-frames:v',str(row['keep']),
        '-vf',f'scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1',
        '-threads','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1']
    with launch(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as decoder:
        size=W*H*3
        for i in range(row['keep']):
            block=bytearray()
            while len(block)<size:
                chunk=decoder.stdout.read(size-len(block))
                if not chunk:break
                block.extend(chunk)
            if len(block)!=size:
                error=decoder.stderr.read().decode('utf8',errors='replace')
                raise ValueError(f"Missing actual frame {row['segment']}:{i}: {error}")
            yield block
        assert not decoder.stdout.read(1),'Unexpected frames after exact keep limit'
        error=decoder.stderr.read().decode('utf8',errors='replace')
        assert decoder.wait()==0,f"Strict decode failed {row['segment']}: {error}"
def assembly_plan():
    selection=read(E/'selected-candidates.json');rows=[];start=0
    staged=read(E/'lossless-assembly-inputs.json')['inputs'] if (E/'lossless-assembly-inputs.json').exists() else {}
    for n,keep in table():
        if n in PASS:
            path=next((P/'补齐生成用').glob(n+' *.mp4'));item={'passthrough':True}
        else:
            item=selection['segments'][n];path=Path(item['output'])
            assert item['native_review']=='passed',f'{n} not reviewed at native resolution'
            assert item.get('action_review')=='passed',f'{n} source motion not reviewed'
            assert item.get('output_clock_review')=='passed',f'{n} complete output clock not reviewed'
            expected_refs=[sha(P/'替换用参考图/一号.png'),sha(P/'替换用参考图/二号.png')]
            assert item.get('reference_identity_sha256')==expected_refs,f'{n} belongs to other identities'
            assert item['output_sha256']==sha(path),f'{n} changed output'
            with av.open(str(path)) as c:
                c.streams.video[0].codec_context.thread_count=1
                assert sum(1 for _ in c.decode(video=0))==keep,f'{n} selection must contain exact retained frames, not context/holds'
        rows.append({'segment':n,'input':str(path),'input_sha256':sha(path),'keep':keep,
            'first_frame':start,'end_frame_exclusive':start+keep,'start_seconds':str(Fraction(start)/FPS),
            'end_seconds':str(Fraction(start+keep)/FPS),'passthrough':n in PASS,
            'candidate':item.get('attempt'),'actual1x':item.get('actual1x','pending')})
        if n in staged:
            owner=staged[n];assert sha(owner['decode_input'])==owner['decode_sha256']
            assert owner.get('original_sha256',owner['decode_sha256'])==rows[-1]['input_sha256']
            rows[-1].update({'decode_input':owner['decode_input'],'decode_sha256':owner['decode_sha256'],'lossless_transport':'source decoded-frame hashes verified' if 'decoded_framemd5' in owner else 'selected lossless derivative reused'})
        start+=keep
    return rows
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--plan-only',action='store_true');args=ap.parse_args()
    E.mkdir(exist_ok=True);rows=assembly_plan();write(E/'assembly-frame-plan.json',{'canvas':[W,H],'fps':str(FPS),'frames':2316,
        'duration':str(Fraction(2316)/FPS),'fit':'aspect-preserving black letterbox, no content crop', 'segments':rows})
    if args.plan_only:print('All44 owners resolved, 2316frames; ready for one video encode.');return
    outdir=P/'完成分段/最终组装';outdir.mkdir(parents=True,exist_ok=True)
    silent=outdir/'APT_swap_review_silent.mp4';temp=outdir/'APT_swap_review_silent.part.mp4'
    assert not silent.exists() and not temp.exists(),'Preserve previous assembly; pick a new immutable version'
    logpath=E/'single-encode-ffmpeg.log'
    with logpath.open('wb') as log:
        proc=launch([ENC,'-nostdin','-v','error','-n','-filter_threads','1','-f','rawvideo','-pixel_format','rgb24',
            '-video_size',f'{W}x{H}','-framerate',str(FPS),'-i','pipe:0','-an',
            '-c:v','libx264','-threads','4','-preset','slow','-crf','10','-pix_fmt','yuv420p',
            '-fps_mode','passthrough','-video_track_timescale','24000','-movflags','+faststart',str(temp)],stdin=subprocess.PIPE,stderr=log)
        sent=0
        try:
            for row in rows:
                count=0
                for pixels in strict_rgb_frames(row):
                    proc.stdin.write(pixels);count+=1;sent+=1
                if count!=row['keep']:raise ValueError(f"Missing actual frames {row['segment']}: {count}/{row['keep']}")
                print(f"{row['segment']}: exact{count}frames, total{sent}",flush=True)
            proc.stdin.close();code=proc.wait()
            assert code==0 and sent==2316,'Encoding failed; retain partial for diagnosis'
        except BaseException:
            if proc.stdin and not proc.stdin.closed:proc.stdin.close()
            proc.terminate();proc.wait();raise
    os.replace(temp,silent)
    output=outdir/'APT_final_Made-by-wuwukasi.mp4';assert not output.exists()
    lic=(P/'LICENSE.txt').read_text(encoding='utf-8-sig').strip()
    metadata=['-metadata','title=APT_final (Made by wuwukasi)','-metadata','artist=wuwukasi',
        '-metadata','comment=Made by wuwukasi','-metadata','copyright=Made by wuwukasi',
        '-metadata','description='+lic]
    # AAC stream-copy preserves the supplied audio; one terminal AAC packet may extend less than one packet.
    cmd=[FF,'-nostdin','-v','error','-n','-i',str(silent),'-i',str(P/'原片音轨.m4a'),
        '-map','0:v:0','-map','1:a:0','-c','copy','-t',f'{float(Fraction(2316)/FPS):.7f}',
        *metadata,'-movflags','+faststart',str(output)]
    subprocess.run(cmd,check=True,capture_output=True)
    decode_checks=[]
    for attempt in range(3):
        check=subprocess.run([FF,'-nostdin','-v','error','-xerror','-threads','1','-i',str(output),
            '-map','0:v:0','-map','0:a:0','-threads','1','-f','null','-'],capture_output=True)
        decode_checks.append({'attempt':attempt+1,'returncode':check.returncode,'stderr':check.stderr.decode('utf8',errors='replace')})
        if check.returncode==0 and not check.stderr:break
    write(E/'final-strict-decode-attempts.json',decode_checks)
    assert check.returncode==0 and not check.stderr,'Final strict decode did not pass'
    count=0;pts=[]
    with av.open(str(output)) as c:
        stream=c.streams.video[0];stream.codec_context.thread_count=1
        assert stream.width==W and stream.height==H and stream.average_rate==FPS
        for frame in c.decode(stream):pts.append(Fraction(frame.pts)*frame.time_base);count+=1
    assert count==2316 and all(t==Fraction(i)/FPS for i,t in enumerate(pts))
    license_copy=outdir/'LICENSE.txt'
    if license_copy.exists():assert sha(license_copy)==sha(P/'LICENSE.txt'),'Existing output license differs'
    else:shutil.copy2(P/'LICENSE.txt',license_copy)
    write(E/'assembly-verification.json',{'path':str(output),'sha256':sha(output),'frames':count,'fps':str(FPS),
        'duration_seconds':str(Fraction(count)/FPS),'canvas':[W,H],'exact_pts':'passed','complete_strict_decode':'passed','decoder_cpu_mode':'normal auto-detected CPU; forced scalar H264 compatibility issue excluded',
        'video_encodes':1,'original_audio':'AAC stream-copy from supplied original master, front matching interval',
        'native_segment_reviews':'passed','actual1x_full_film':'pending','native_joins':'pending'})
    print(str(output),flush=True)
if __name__=='__main__':main()
