"""Resolve local FFmpeg tools without bundling or downloading executables."""
from pathlib import Path
import json
import os
import shutil


def resolve_tool(root, name):
    if name not in ('ffmpeg','ffprobe'):
        raise ValueError('Unsupported media tool')
    root=Path(root).resolve()
    config=root/'runtime.json'
    settings=json.loads(config.read_text(encoding='utf-8-sig')) if config.is_file() else {}
    explicit=settings.get(name+'_path') or os.environ.get('APT_'+name.upper())
    if explicit:
        target=Path(explicit).expanduser().resolve()
        if not target.is_file():
            raise FileNotFoundError('Configured '+name+' executable is missing; update the local tool path')
        return str(target)
    for filename in (name+'.exe',name):
        bundled=root/'ffmpeg'/filename
        if bundled.is_file():
            return str(bundled)
    found=shutil.which(name)
    if found:
        return str(Path(found).resolve())
    raise FileNotFoundError(name+' is required. Install FFmpeg and add both ffmpeg/ffprobe to PATH; see README.')
