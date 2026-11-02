"""Offline tiny-frame end-to-end assembly and canonical RGB verification."""
from pathlib import Path
from fractions import Fraction
import contextlib
import importlib.util
import io
import json
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
import av
from PIL import Image

T=Path(__file__).resolve().parent.parent/'assets/template'
sys.path.insert(0,str(T))
from apt_media_tools import resolve_tool
FF=resolve_tool(T,'ffmpeg')


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')


def main():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory).resolve();e=root/'制作分析';e.mkdir();src=root/'补齐生成用';src.mkdir()
        refs=root/'替换用参考图';refs.mkdir()
        Image.new('RGB',(16,16),'blue').save(refs/'一号.png');Image.new('RGB',(16,16),'green').save(refs/'二号.png')
        shutil.copy2(T/'补齐生成用/原始帧数.txt',src/'原始帧数.txt')
        shutil.copy2(T/'LICENSE.txt',root/'LICENSE.txt');write(root/'runtime.json',{})
        spec=importlib.util.spec_from_file_location('assembly_test_module',T/'assemble-reviewed.py')
        # Its import only reads runtime configuration; the installed template is never encoded.
        # Provide globals through a compiled module after binding the fake source file to this fixture.
        copied=root/'assemble-reviewed.py';shutil.copy2(T/'assemble-reviewed.py',copied)
        spec=importlib.util.spec_from_file_location('assembly_test_module',copied)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.W=64;module.H=36;module.FF=FF;module.ENC=FF
        rows=module.table();assert len(rows)==44 and sum(c for n,c in rows)==2316
        identities=[module.sha(refs/'一号.png'),module.sha(refs/'二号.png')]
        selection={}
        for number,keep in rows:
            path=src/f'{number} {keep}.mp4'
            # Deliberately a 2:1 source; final 16:9 must add bars, not stretch.
            with av.open(str(path),'w',format='matroska') as container:
                stream=container.add_stream('ffv1',rate=24);stream.width=64;stream.height=32;stream.pix_fmt='yuv420p'
                for index in range(keep):
                    image=Image.new('RGB',(64,32),(35+index%100,100,70))
                    frame=av.VideoFrame.from_image(image);frame.pts=index;frame.time_base=Fraction(1,24)
                    for packet in stream.encode(frame):container.mux(packet)
                for packet in stream.encode():container.mux(packet)
            if number not in module.PASS:
                selection[number]={'output':str(path),'output_sha256':module.sha(path),'attempt':'offline-fixture',
                    'native_review':'passed','action_review':'passed','output_clock_review':'passed',
                    'reference_identity_sha256':identities,'actual1x':'pending'}
        write(e/'selected-candidates.json',{'segments':selection})
        subprocess.run([FF,'-nostdin','-v','error','-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
            '-t','97','-c:a','aac','-threads','1','-n',str(root/'原片音轨.m4a')],check=True,capture_output=True,timeout=30)
        with patch.object(sys,'argv',['assemble-reviewed.py']),contextlib.redirect_stdout(io.StringIO()):
            module.main()
        verification=read(e/'assembly-verification.json');assert verification['frames']==2316
        assert verification['exact_pts']=='passed' and verification['video_encodes']==1
        assert verification['canvas']==[64,36] and verification['actual1x_full_film']=='pending'
        assert module.sha(Path(verification['path']).parent/'LICENSE.txt')==module.sha(root/'LICENSE.txt')
        with av.open(verification['path']) as container:
            frame=next(container.decode(video=0)).to_ndarray(format='rgb24')
            assert frame[0,:,:].mean()<8 and frame[-1,:,:].mean()<8,'Aspect-preserving bars missing'
            assert frame[18,:,:].mean()>30,'Image missing between bars'
        copied_inspector=root/'inspect-final-assembly.py';shutil.copy2(T/'inspect-final-assembly.py',copied_inspector)
        with contextlib.redirect_stdout(io.StringIO()):runpy.run_path(str(copied_inspector),run_name='__main__')
        report=read(e/'final-assembly-review/review-evidence.json')
        assert report['original_audio_packet_prefix'].startswith('byte-identical')
        assert len(list((e/'final-assembly-review').glob('joins-*.png')))==8
        # The selected identity contract must reject a different new target image.
        Image.new('RGB',(16,16),'red').save(refs/'一号.png')
        try:module.assembly_plan()
        except AssertionError as error:assert 'other identities' in str(error)
        else:raise AssertionError('Previous identity selection silently reused')
        # Verify both successful and failing canonical RGB paths using real media decoding.
        pngs=root/'canonical';pngs.mkdir()
        for index in range(3):Image.new('RGB',(64,32),(index*40,90,110)).save(pngs/f'{index:03d}.png')
        rgb=root/'rgb-lossless.mkv'
        subprocess.run([FF,'-nostdin','-v','error','-framerate','24','-i',str(pngs/'%03d.png'),
            '-c:v','ffv1','-threads','1','-level','3','-pix_fmt','bgr0','-n',str(rgb)],check=True,capture_output=True,timeout=30)
        cmd=[sys.executable,'-B','-X','utf8',str(T/'verify_rgb.py'),'--pngs',str(pngs),'--video',str(rgb),
             '--out',str(root/'rgb-proof.json')]
        subprocess.run(cmd,check=True,capture_output=True,timeout=30)
        assert read(root/'rgb-proof.json')['passed']
        Image.new('RGB',(64,32),'red').save(pngs/'001.png')
        result=subprocess.run(cmd,capture_output=True,timeout=30)
        assert result.returncode!=0 and not read(root/'rgb-proof.json')['passed']
        print('PASS:44 owners/2316PTS; single encode; aspect bars; original AAC;43joins; identity reuse rejected; RGB positive/negative proofs. No API calls.')


if __name__=='__main__':main()
