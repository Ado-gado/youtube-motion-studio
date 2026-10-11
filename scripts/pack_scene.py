from pathlib import Path
import argparse,json,zipfile,uuid,re,hashlib
from datetime import datetime,timezone
from runtime import ROOT
from job_bundle import ALLOWED,MAX_BYTES,safe_name,validate_manifest,inspect_bundle

def main():
    p=argparse.ArgumentParser(description='Export one requested scene and its local assets for PC rendering; no video render')
    p.add_argument('scene',type=Path);p.add_argument('--duration',type=float,required=True)
    p.add_argument('--fps',type=int,default=24);p.add_argument('--width',type=int,default=1920);p.add_argument('--height',type=int,default=1080)
    p.add_argument('--audio',type=Path);p.add_argument('--out',type=Path);p.add_argument('--title',default='scene');p.add_argument('--account-label',default='')
    p.add_argument('--scene-root',type=Path,default=ROOT);p.add_argument('--include',type=Path,action='append',default=[])
    p.add_argument('--capture',choices=['auto','canvas','screenshot'],default='auto');a=p.parse_args()
    if a.scene.is_symlink() or a.scene_root.is_symlink():raise ValueError('Do not include symlinks')
    root=a.scene_root.resolve();scene=a.scene.resolve();scene.relative_to(root)
    if root==Path(root.anchor) or not scene.is_file() or scene.suffix!='.html':raise ValueError('Choose an HTML scene within its project, not the filesystem root')
    candidates=set()
    for folder in [scene.parent,root/'fonts',*a.include]:
        if folder.is_symlink():raise ValueError('Do not include symlinks')
        folder=folder.resolve();folder.relative_to(root)
        if not folder.exists():
            if folder==root/'fonts':continue
            raise ValueError('Missing included asset: '+str(folder))
        paths=[folder] if folder.is_file() else folder.rglob('*')
        for f in paths:
            if f.is_symlink():raise ValueError('Do not include symlinks')
            if not f.is_file() or any(part.startswith('.') or part in ['node_modules','__pycache__'] for part in f.relative_to(root).parts):continue
            if f.suffix.lower() in ALLOWED:candidates.add(f.resolve())
    if a.audio:
        if a.audio.is_symlink():raise ValueError('Do not include symlinks')
        audio=a.audio.resolve();audio.relative_to(root)
        if not audio.is_file():raise ValueError('Missing audio')
        candidates.add(audio)
    if scene not in candidates:raise ValueError('Scene not included')
    if sum(f.stat().st_size for f in candidates)>MAX_BYTES:raise ValueError('Scene bundle exceeds 1 GiB')
    slug=re.sub(r'[^a-zA-Z0-9_-]+','-',a.title).strip('-')[:40] or 'scene'
    job_id=slug+'-'+uuid.uuid4().hex[:12]
    out=a.out.resolve() if a.out else ROOT/'outputs/bundles'/('motion-job-'+job_id+'.zip')
    out.parent.mkdir(parents=True,exist_ok=True)
    manifest={'schema':1,'job_id':job_id,'title':a.title,'account_label':a.account_label,'created_utc':datetime.now(timezone.utc).isoformat(),'render':{'scene':scene.relative_to(root).as_posix(),'duration':a.duration,'fps':a.fps,'width':a.width,'height':a.height,'capture':a.capture},'files':{}}
    if a.audio:manifest['render']['audio']=audio.relative_to(root).as_posix()
    partial=out.with_suffix('.zip.part')
    with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for f in sorted(candidates):
            name=f.relative_to(root).as_posix();safe_name(name);h=hashlib.sha256()
            if name=='motion-job.json':raise ValueError('Reserved manifest filename')
            with f.open('rb') as src,z.open(name,'w') as dst:
                for chunk in iter(lambda:src.read(1024*1024),b''):h.update(chunk);dst.write(chunk)
            manifest['files'][name]=h.hexdigest()
        validate_manifest(manifest);z.writestr('motion-job.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    inspect_bundle(partial);partial.replace(out)
    print(json.dumps({'bundle':str(out),'job_id':job_id,'files':len(manifest['files']),'bytes':out.stat().st_size,'video_rendered':False},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
