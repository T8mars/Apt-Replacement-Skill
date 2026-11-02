"""Compare every canonical PNG RGB byte with independent strict FFmpeg video decoding."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
from PIL import Image
from apt_media_tools import resolve_tool


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pngs',required=True,type=Path)
    ap.add_argument('--video',required=True,type=Path)
    ap.add_argument('--ffmpeg',type=Path)
    ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args()
    args.ffmpeg=args.ffmpeg or Path(resolve_tool(Path(__file__).resolve().parent,'ffmpeg'))
    files=sorted(args.pngs.glob('*.png'))
    if not files:raise ValueError('No ordered canonical PNG frames')
    expected=[]; dimensions=None
    for path in files:
        with Image.open(path) as image:
            if dimensions is None:dimensions=image.size
            if image.size!=dimensions:raise ValueError('Mixed PNG dimensions')
            expected.append(hashlib.sha256(image.convert('RGB').tobytes()).hexdigest())
    # Compare normal CPU decode against the saved plan; encoder scalar settings are independent.
    with subprocess.Popen([str(args.ffmpeg),'-nostdin','-v','error','-xerror','-threads','1','-i',str(args.video),
        '-map','0:v:0','-an','-threads','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE) as proc:
        actual=[]; size=dimensions[0]*dimensions[1]*3
        while True:
            block=proc.stdout.read(size)
            if not block:break
            if len(block)!=size:raise ValueError('Incomplete RGB frame')
            actual.append(hashlib.sha256(block).hexdigest())
        error=proc.stderr.read(); code=proc.wait()
    passed=not code and not error.strip() and expected==actual
    report={'passed':bool(passed),'expected_frames':len(expected),'decoded_frames':len(actual),'dimensions':dimensions,
        'expected_rgb_sha256':expected,'decoded_rgb_sha256':actual,'decoder':str(args.ffmpeg.resolve()),
        'decoder_cpu':'normal','strict_returncode':code,'visual_acceptance':'not established'}
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    if not passed:raise ValueError('Canonical RGB verification failed; do not select this derivative')
    print('All canonical RGB frames match; visual review remains separate.')


if __name__=='__main__':main()
