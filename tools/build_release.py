"""Build a complete licensed APT skill ZIP; never includes local executables or credentials."""
from pathlib import Path
import argparse
import hashlib
import zipfile
import verify_publish as guard


def build(source,output):
    source=Path(source).resolve();output=Path(output).resolve()
    if output.is_relative_to(source) or output.exists():raise ValueError('Use a new ZIP path outside the skill folder')
    files=guard.read_source(source,complete=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=4) as archive:
        for index,(name,data) in enumerate(sorted(files.items())):
            archive.writestr('apt-character-replacement/'+name,data)
            if index%20==0:print('Packaged',index+1,'of',len(files),'verified members',flush=True)
    # Independently read/decompress every member and compare its expected bytes.
    with zipfile.ZipFile(output) as archive:
        if len(archive.namelist())!=len(files):raise ValueError('Archive member count differs')
        for name,data in files.items():
            if hashlib.sha256(archive.read('apt-character-replacement/'+name)).digest()!=hashlib.sha256(data).digest():
                raise ValueError('Archive member changed: '+name)
    h=hashlib.sha256()
    with output.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    checksum=output.parent/'SHA256SUMS.txt';checksum.write_text(h.hexdigest()+'  '+output.name+'\n',encoding='utf8')
    print('Complete licensed skill ZIP verified:',output.name,output.stat().st_size,'bytes; SHA256',h.hexdigest(),flush=True)
    return {'path':str(output),'sha256':h.hexdigest(),'members':len(files),'bytes':output.stat().st_size}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',required=True,type=Path);ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args();build(args.source,args.output)


if __name__=='__main__':main()
