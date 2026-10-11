from pathlib import Path
import os,shutil,subprocess,json,re
ROOT=Path(__file__).resolve().parents[1]
def browser_path():
    override=os.environ.get('MOTION_CHROMIUM')
    if override:
        if not Path(override).is_file(): raise RuntimeError('MOTION_CHROMIUM points to a missing file')
        return override
    candidates=[shutil.which(x) for x in ['chromium','chromium-browser','google-chrome','chrome']]
    candidates += ['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
    return next((str(x) for x in candidates if x and Path(x).is_file()),None)
def ffmpeg_path():
    found=shutil.which('ffmpeg')
    if found:return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()
def launch(p):
    binary=browser_path()
    return p.chromium.launch(headless=True,executable_path=binary,args=['--disable-dev-shm-usage']) if binary else p.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
def check_manifest():
    import hashlib
    expected=json.loads((ROOT/'manifest.json').read_text(encoding='utf8'))
    wrong=[]
    for rel,digest in expected['files'].items():
        f=ROOT/rel
        if not f.is_file():wrong.append(rel);continue
        raw=f.read_bytes()
        if rel=='AGENTS.md':raw=re.sub(r'<!-- motion-studio:start -->.*?<!-- motion-studio:end -->','',raw.decode('utf8'),flags=re.S).rstrip().encode('utf8')
        if hashlib.sha256(raw).hexdigest()!=digest and rel not in expected.get('mutable',[]):wrong.append(rel)
    return wrong
