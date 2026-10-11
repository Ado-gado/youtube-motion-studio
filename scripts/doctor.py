import json,subprocess,sys
from runtime import ROOT,ffmpeg_path,launch
from playwright.sync_api import sync_playwright
from PIL import Image

def doctor():
    if sys.version_info<(3,10):raise RuntimeError('Python 3.10+ required')
    ff=ffmpeg_path()
    result=subprocess.run([ff,'-v','error','-f','lavfi','-i','color=c=black:s=64x64:r=24:d=0.1','-c:v','libx264','-pix_fmt','yuv420p','-f','null','-'],capture_output=True,text=True)
    if result.returncode:raise RuntimeError('FFmpeg H.264 encoder unavailable: '+result.stderr[-800:])
    with sync_playwright() as p:
        browser=launch(p);page=browser.new_page(viewport={'width':64,'height':64})
        page.set_content('<canvas width=64 height=64></canvas>')
        page.evaluate("document.querySelector('canvas').getContext('2d').fillRect(0,0,64,64)")
        shot=page.locator('canvas').screenshot()
        assert len(shot)>20
        info={'python':sys.version.split()[0],'browser':browser.version,'ffmpeg':ff,'canvas':'pass','h264':'pass','AE':'not tested','Emergent':'not tested'}
        browser.close()
    return info
if __name__=='__main__':
    try:print(json.dumps(doctor(),ensure_ascii=False,indent=2))
    except Exception as e:print('DOCTOR FAILED: '+str(e),file=sys.stderr);sys.exit(1)
