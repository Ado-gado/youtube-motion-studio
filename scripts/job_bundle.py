"""Portable scene jobs; never execute scripts supplied by an archive."""
from pathlib import Path,PurePosixPath
import hashlib,json,math,re,stat,zipfile,unicodedata

MAX_BYTES=1024*1024*1024
ALLOWED={'.html','.js','.mjs','.css','.json','.txt','.md','.png','.jpg','.jpeg','.webp','.svg','.gif','.avif','.ttf','.otf','.woff','.woff2','.obj','.mtl','.gltf','.glb','.bin','.mp3','.wav','.ogg','.m4a','.aac','.mp4','.webm','.mov'}
RESERVED={'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}

def safe_name(name):
    if not isinstance(name,str) or not name or '\\' in name or '\x00' in name:raise ValueError('Invalid archive path')
    p=PurePosixPath(name)
    if p.is_absolute() or p.as_posix()!=name:raise ValueError('Use canonical relative archive paths')
    for part in name.split('/'):
        if part in ('.','..') or part.startswith('.') or part.endswith((' ','.')) or any(c in part for c in ':<>"|?*') or part.split('.')[0].upper() in RESERVED:raise ValueError('Unsafe archive path: '+name)
    if p.suffix.lower() not in ALLOWED:raise ValueError('Unsupported file type: '+name)
    return p

def digest_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def validate_manifest(data):
    if not isinstance(data,dict):raise ValueError('Invalid job manifest')
    if data.get('schema')!=1:raise ValueError('Unsupported motion job schema')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',str(data.get('job_id',''))):raise ValueError('Invalid job ID')
    files=data.get('files')
    if not isinstance(files,dict) or not files or len(files)>10000:raise ValueError('Invalid file manifest')
    folded=set()
    for name,h in files.items():
        safe_name(name);key=unicodedata.normalize('NFC',name).casefold()
        if key in folded:raise ValueError('Case/Unicode filename collision')
        folded.add(key)
        if not isinstance(h,str) or not re.fullmatch(r'[a-f0-9]{64}',h):raise ValueError('Invalid checksum')
    r=data.get('render')
    if not isinstance(r,dict) or any(k not in r for k in ['scene','duration','fps','width','height']):raise ValueError('Missing render parameters')
    entry=r['scene'];safe_name(entry)
    if entry not in files or not entry.endswith('.html'):raise ValueError('Missing HTML scene')
    duration=r['duration'];fps=r['fps'];width=r['width'];height=r['height']
    if not isinstance(duration,(int,float)) or isinstance(duration,bool) or not math.isfinite(duration) or not 0<duration<=1800:raise ValueError('Invalid duration')
    if not isinstance(fps,int) or isinstance(fps,bool) or not 1<=fps<=120:raise ValueError('Invalid fps')
    if any(not isinstance(v,int) or isinstance(v,bool) or not 2<=v<=7680 or v%2 for v in [width,height]) or width*height>34000000:raise ValueError('Invalid render size')
    if r.get('capture','auto') not in ['auto','canvas','screenshot']:raise ValueError('Invalid capture mode')
    if r.get('audio'):
        safe_name(r['audio'])
        if r['audio'] not in files:raise ValueError('Missing audio asset')
    return data

def inspect_bundle(archive):
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist()
        if len(infos)>10001 or sum(i.file_size for i in infos)>MAX_BYTES:raise ValueError('Job exceeds file/size limit')
        names=[]
        for i in infos:
            if i.is_dir() or stat.S_ISLNK(i.external_attr>>16) or i.flag_bits&1:raise ValueError('Directories, symlinks and encrypted entries are not supported')
            safe_name(i.filename);names.append(i.filename)
        if len(set(names))!=len(names):raise ValueError('Duplicate ZIP entries')
        if 'motion-job.json' not in names:raise ValueError('Not a motion scene job: missing motion-job.json')
        if z.getinfo('motion-job.json').file_size>2*1024*1024:raise ValueError('Manifest too large')
        data=validate_manifest(json.loads(z.read('motion-job.json').decode('utf8')))
        if set(names)!=set(data['files'])|{'motion-job.json'}:raise ValueError('Archive contents differ from manifest')
        if 'motion-job.json' in data['files']:raise ValueError('Manifest cannot include itself')
    return data

def unpack_bundle(archive,destination):
    data=inspect_bundle(archive);destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        for name,expected in data['files'].items():
            out=destination.joinpath(*safe_name(name).parts);out.resolve().relative_to(destination)
            out.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256()
            with z.open(name) as src,out.open('xb') as dst:
                for chunk in iter(lambda:src.read(1024*1024),b''):h.update(chunk);dst.write(chunk)
            if h.hexdigest()!=expected:raise ValueError('Checksum mismatch: '+name)
        (destination/'motion-job.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    return data
