"""Prepare complete actual-output evidence. No automatic visual acceptance or editing."""
from pathlib import Path
import argparse
import hashlib
import json
from fractions import Fraction
import av
from PIL import Image, ImageDraw, ImageOps


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def validate_map(mapping, output_count, source_count):
    indices = mapping['output_indices']
    sources = mapping['source_indices']
    if len(indices) != len(sources) or not indices:
        raise ValueError('Source/output frame map length mismatch')
    if any(type(i) is not int or not 0 <= i < output_count for i in indices):
        raise ValueError('Selected frame is outside the ACTUAL output clock')
    if any(type(i) is not int or not 0 <= i < source_count for i in sources):
        raise ValueError('Source frame index out of range')
    if any(b < a for a,b in zip(indices,indices[1:])) or any(b <= a for a,b in zip(sources,sources[1:])):
        raise ValueError('Frame ownership must preserve action order, including shot boundaries')
    if not mapping.get('action_start_middle_end_review'):
        raise ValueError('Record source start/middle/end poses; do not infer trim from input prefix')
    cuts = mapping.get('source_cut_before', [])
    output_cuts = mapping.get('output_cut_before', [])
    if bool(cuts) != bool(output_cuts) or len(cuts) != len(output_cuts):
        raise ValueError('Source and output shot boundaries must both be measured')
    if cuts != sorted(set(cuts)) or output_cuts != sorted(set(output_cuts)):
        raise ValueError('Cut boundaries must be ordered and unique')
    if any(type(c) is not int or not 0 < c < source_count for c in cuts) or any(type(c) is not int or not 0 < c < output_count for c in output_cuts):
        raise ValueError('Cut boundary outside actual source/output frames')
    for src, out in zip(sources,indices):
        if sum(src >= c for c in cuts) != sum(out >= c for c in output_cuts):
            raise ValueError('Frame mapping crosses a measured source/output shot boundary')
    return indices


def video_info(path):
    pts = []
    hashes = []
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.codec_context.thread_count = 1
        for frame in container.decode(stream):
            pts.append(str(Fraction(frame.pts)*frame.time_base) if frame.pts is not None else None)
            # Statistics diagnose holds, never establish that an action is correct.
            hashes.append(hashlib.sha256(frame.to_ndarray(format='rgb24').tobytes()).hexdigest())
        return {'frames':len(pts),'width':stream.width,'height':stream.height,'fps':str(stream.average_rate),
            'pts':pts, 'unique_rgb_frames':len(set(hashes)), 'consecutive_identical_pairs':sum(a==b for a,b in zip(hashes,hashes[1:]))}


def pages(path, destination, rois=(), native=False, selected=None, columns=3, prefix='output'):
    thumbs = []; numbers = []; page_number = 0; count = 0; captured = {}
    with av.open(str(path)) as container:
        container.streams.video[0].codec_context.thread_count = 1
        for number, frame in enumerate(container.decode(video=0)):
            image = frame.to_image()
            if native:
                image.save(destination/f'{prefix}-{number:04d}-native.png')
            for name, box in rois:
                if not 0 <= box[0] < box[2] <= image.width or not 0 <= box[1] < box[3] <= image.height:
                    raise ValueError('ROI extends outside native frame')
                image.crop(tuple(box)).save(destination/f'{prefix}-{number:04d}-{name}.png')
            if selected is not None and number in selected:
                captured[number] = ImageOps.contain(image, (640,360))
            thumbs.append(ImageOps.pad(image, (640,360), color='#202020'))
            numbers.append(number); count += 1
            if len(thumbs) == 12:
                save_page(thumbs, numbers, destination/f'{prefix}-clock-{page_number:03d}.png', columns)
                thumbs=[]; numbers=[]; page_number+=1
    if thumbs:
        save_page(thumbs,numbers,destination/f'{prefix}-clock-{page_number:03d}.png',columns)
    return captured, count


def save_page(images, numbers, path, columns):
    page = Image.new('RGB',(columns*640, ((len(images)+columns-1)//columns)*384),'#202020')
    draw = ImageDraw.Draw(page)
    for index, (image, number) in enumerate(zip(images,numbers)):
        x=index%columns*640; y=index//columns*384
        page.paste(image,(x,y+24)); draw.text((x+5,y+4),f'actual frame {number}',fill='white')
    page.save(path)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--video',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--source',type=Path)
    ap.add_argument('--map',type=Path)
    ap.add_argument('--roi',type=Path,help='JSON list of {name,box}; manual native coordinates, every actual frame')
    ap.add_argument('--native-all',action='store_true')
    args=ap.parse_args(argv)
    info=video_info(args.video)
    if not info['frames']:
        raise ValueError('Empty output video')
    rois=[]
    for roi in read(args.roi) if args.roi else []:
        if not __import__('re').fullmatch('[A-Za-z0-9_-]+',roi['name']):
            raise ValueError('ROI name must be a plain filename component')
        rois.append((roi['name'],roi['box']))
    mapping=read(args.map) if args.map else None
    source_info=video_info(args.source) if args.source else None
    if mapping:
        if not args.source:
            raise ValueError('Frame map requires original source')
        validate_map(mapping, info['frames'], source_info['frames'])
    args.out.mkdir(parents=True,exist_ok=False)
    captured,count=pages(args.video,args.out,rois,args.native_all,
        set(mapping['output_indices']) if mapping else None)
    if count != info['frames']:
        raise ValueError('Output changed between metadata and full clock extraction')
    if mapping:
        original,_=pages(args.source,args.out,selected=set(mapping['source_indices']),prefix='source')
        # Each row displays measured source pose and the proposed retained output pose.
        for start in range(0,len(mapping['output_indices']),6):
            pairs=list(zip(mapping['source_indices'],mapping['output_indices']))[start:start+6]
            page=Image.new('RGB',(1280,384*len(pairs)),'#202020'); draw=ImageDraw.Draw(page)
            for row,(src,out) in enumerate(pairs):
                page.paste(original[src],(0,row*384+24)); page.paste(captured[out],(640,row*384+24))
                draw.text((5,row*384+4),f'source {src} -> actual output {out}',fill='white')
            page.save(args.out/f'action-map-{start:04d}.png')
    report={'video':str(args.video.resolve()),'video_sha256':sha(args.video),'actual_output_clock':info,
        'source':str(args.source.resolve()) if args.source else None,
        'source_sha256':sha(args.source) if args.source else None,'frame_map':mapping,
        'native_rois':[{'name':n,'box':b,'frame_indices':list(range(count))} for n,b in rois],
        'native_full_frames_prepared':args.native_all,'evidence':'prepared',
        'output_clock_visual_review':'pending','roi_identity_and_coverage_review':'pending',
        'source_action_review':'pending','actual1x':'pending'}
    (args.out/'evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'actual_output_frames':count,'evidence_directory':str(args.out.resolve()),'visual_acceptance':'pending'}))


if __name__=='__main__':
    main()
