"""Sequential exports. Only one scene is extracted; temporary files are disposable."""
from collections import deque
from pathlib import Path
import copy
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from .model import ROOT, check_clip_source, font_config
from job_bundle import unpack_bundle
from runtime import ffmpeg_path


class Cancelled(Exception): pass


def kill_tree(process):
    if process.poll() is not None: return
    if os.name == 'nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        os.killpg(process.pid,signal.SIGKILL)
    process.wait(timeout=15)


def run_process(command, cancel, line_callback=None):
    options = {'creationflags':subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
    process = subprocess.Popen(list(map(str,command)),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',**options)
    lines = queue.Queue(); tail = deque(maxlen=25)
    def reader():
        for line in process.stdout:
            lines.put(line.rstrip())
        process.stdout.close()
    thread = threading.Thread(target=reader,daemon=True); thread.start()
    try:
        while process.poll() is None or not lines.empty() or thread.is_alive():
            if cancel.is_set():
                kill_tree(process); raise Cancelled('Рендер отменён')
            try: line=lines.get(timeout=.1)
            except queue.Empty: continue
            tail.append(line)
            if line_callback: line_callback(line)
        if process.returncode:
            raise RuntimeError('\n'.join(tail))
    finally:
        if process.poll() is None: kill_tree(process)
        thread.join(timeout=2)


def safe_temp_root():
    root=(ROOT/'EDITOR_WORK/temp').resolve(); root.relative_to(ROOT.resolve()); root.mkdir(parents=True,exist_ok=True)
    return root


def render_project(clips, destination, cancel, notify, size=None, fps=None):
    if not clips: raise ValueError('Добавьте хотя бы один фрагмент')
    clips=copy.deepcopy(clips); destination=Path(destination).resolve()
    if destination.suffix.lower()!='.mp4': raise ValueError('Выберите файл MP4')
    destination.parent.mkdir(parents=True,exist_ok=True)
    partial=destination.with_name(destination.stem+'.rendering-'+uuid.uuid4().hex[:8]+'.mp4')
    temp_root=safe_temp_root(); ff=ffmpeg_path()
    common_size=size or (clips[0]['render']['width'],clips[0]['render']['height'])
    common_fps=fps or clips[0]['render']['fps']
    has_audio=any(bool(clip['render'].get('audio')) for clip in clips)
    normalize_all=has_audio or any((c['render']['width'],c['render']['height'])!=tuple(common_size) or c['render']['fps']!=common_fps for c in clips)
    try:
        with tempfile.TemporaryDirectory(prefix='render-',dir=temp_root) as job_dir:
            job=Path(job_dir); job.resolve().relative_to(temp_root); normalized=[]; reports=[]; notices={'ASSETS':[],'CREDITS':[]}
            for index,clip in enumerate(clips):
                if cancel.is_set(): raise Cancelled('Рендер отменён')
                notify('render_progress',index/len(clips)*90,f'{index+1}/{len(clips)} · {clip["title"]}')
                source=check_clip_source(clip)
                with zipfile.ZipFile(source['path']) as archive:
                    required=sum(info.file_size for info in archive.infolist())+256*1024*1024
                if shutil.disk_usage(temp_root).free<required:
                    raise RuntimeError('Недостаточно места для временной распаковки текущей сцены')
                with tempfile.TemporaryDirectory(prefix='scene-',dir=job) as scene_dir:
                    Path(scene_dir).resolve().relative_to(job.resolve())
                    scene_root=Path(scene_dir)/'source'
                    unpack_bundle(clip['archive'],scene_root)
                    r=source['manifest']['render']; scene=scene_root/r['scene']
                    for kind in notices:
                        notice=scene.parent/(kind+'.md')
                        if notice.is_file():notices[kind].append(f'## {index+1}. {clip["title"]}\n\n'+notice.read_text(encoding='utf-8-sig'))
                    if clip.get('editor') is not None:
                        (scene.parent/'motion-editor.json').write_text(json.dumps(clip['editor'],ensure_ascii=False),encoding='utf8')
                        fonts=font_config(clip['editor'])
                        if fonts:
                            (scene.parent/'local-fonts.json').write_text(json.dumps(fonts),encoding='utf8')
                        elif (scene.parent/'local-fonts.json').exists():
                            (scene.parent/'local-fonts.json').unlink()
                    raw=Path(scene_dir)/'raw/video.mp4'
                    executable=Path(sys.executable)
                    if executable.name.lower()=='pythonw.exe':executable=executable.with_name('python.exe')
                    command=[executable,'-X','utf8',ROOT/'scripts/render_scene.py',scene,'--scene-root',scene_root,'--duration',r['duration'],'--fps',r['fps'],'--width',r['width'],'--height',r['height'],'--capture',r.get('capture','auto'),'--lean','--out',raw]
                    if r.get('audio'): command+=['--audio',scene_root/r['audio']]
                    def progress(line):
                        match=re.match(r'(\d+)/(\d+) frames',line)
                        if match:
                            part=int(match[1])/max(1,int(match[2]))
                            notify('render_progress',(index+part*.8)/len(clips)*90,f'{index+1}/{len(clips)} · {clip["title"]}')
                    run_process(command,cancel,progress)
                    checks=json.loads((raw.parent/'checks.json').read_text(encoding='utf8'))
                    if checks.get('decode')!='pass': raise RuntimeError('Фрагмент не прошёл проверку экспорта')
                    reports.append({'title':clip['title'],'duration':r['duration'],'fonts':checks.get('local_fonts',[])})
                    final_clip=job/f'clip-{index:05d}.mp4'
                    w,h=common_size
                    if not normalize_all:
                        shutil.move(str(raw),str(final_clip))
                    else:
                        command=[ff,'-y','-v','error','-i',raw]
                        if has_audio and not r.get('audio'): command+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
                        command+=['-map','0:v:0','-vf',f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={common_fps},setsar=1','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p']
                        if has_audio:
                            command+=['-map','0:a:0' if r.get('audio') else '1:a:0','-af','apad','-ar','48000','-ac','2','-c:a','aac','-b:a','192k']
                        else: command+=['-an']
                        command+=['-t',str(r['duration']),'-video_track_timescale','24000',final_clip]
                        run_process(command,cancel)
                    normalized.append(final_clip)
                # scene_dir and its extracted assets are removed here, before the next ZIP.
            notify('render_progress',93,'Соединение фрагментов')
            if len(normalized)==1:
                shutil.copyfile(normalized[0],partial)
            else:
                listing=job/'concat.txt'
                listing.write_text('\n'.join("file '"+p.name+"'" for p in normalized),encoding='utf8')
                run_process([ff,'-y','-v','error','-f','concat','-safe','1','-i',listing,'-c','copy','-movflags','+faststart',partial],cancel)
            notify('render_progress',97,'Проверка готового MP4')
            run_process([ff,'-v','error','-i',partial,'-f','null','-'],cancel)
            if cancel.is_set(): raise Cancelled('Рендер отменён')
            partial.replace(destination)
            report={'schema':1,'clips':reports,'duration_requested':sum(c['render']['duration'] for c in clips),'size':list(common_size),'fps':common_fps,'audio':has_audio,'decode':'pass','temporary_sources_retained':False,'visual_review':'Просмотрите готовый MP4'}
            destination.with_suffix('.checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            for kind,entries in notices.items():
                destination.with_suffix('.'+kind+'.md').write_text('\n\n'.join(entries) if entries else 'В исходных архивах нет '+kind+'.md. Проверьте материалы перед публикацией.\n',encoding='utf8')
            return destination
    finally:
        if partial.exists(): partial.unlink()
