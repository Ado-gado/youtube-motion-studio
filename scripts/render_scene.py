from pathlib import Path
import argparse,json,threading,functools,http.server,subprocess,sys,io,time
from playwright.sync_api import sync_playwright
from PIL import Image,ImageDraw
from runtime import ROOT,ffmpeg_path,launch
from frame_capture import FrameCapture
from local_fonts import read_config,init_script,await_fonts

parser=argparse.ArgumentParser(description='Deterministic documentary scene exporter')
parser.add_argument('scene',type=Path)
parser.add_argument('--duration',type=float,required=True)
parser.add_argument('--fps',type=int,default=24)
parser.add_argument('--width',type=int,default=1920)
parser.add_argument('--height',type=int,default=1080)
parser.add_argument('--out',type=Path,default=ROOT/'outputs/video.mp4')
parser.add_argument('--audio',type=Path)
parser.add_argument('--probe-times',default='',help='Extra comma-separated timestamps around transitions')
parser.add_argument('--preview-only',action='store_true')
parser.add_argument('--scene-root',type=Path,default=ROOT,help='Serve only this isolated scene/job root')
parser.add_argument('--capture',choices=['auto','canvas','screenshot'],default='auto')
parser.add_argument('--gif-preview',action='store_true',help='Optional GIF; disabled by default')
args=parser.parse_args()
scene=args.scene.resolve();out=args.out.resolve();scene_root=args.scene_root.resolve()
if scene_root==Path(scene_root.anchor):raise SystemExit('Do not serve the filesystem root')
try:relative=scene.relative_to(scene_root)
except ValueError:raise SystemExit('Scene must be inside --scene-root')
if not scene.is_file():raise SystemExit('Missing scene file')
local_font_config=read_config(scene);local_font_report=[]
if args.duration<=0 or args.fps<1 or min(args.width,args.height)<2:raise SystemExit('Invalid duration, fps or dimensions')
if args.width%2 or args.height%2:raise SystemExit('H.264/yuv420p requires even dimensions')
if args.audio and not args.audio.is_file():raise SystemExit('Missing audio file')
out.parent.mkdir(parents=True,exist_ok=True)
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(scene_root)))
threading.Thread(target=server.serve_forever,daemon=True).start()
from urllib.parse import quote
url=f'http://127.0.0.1:{server.server_port}/{quote(relative.as_posix())}?capture'
errors=[];ff=ffmpeg_path();proc=None;started=time.perf_counter();network_blocked=[];encode_wait=0
try:
    with sync_playwright() as p:
        browser=launch(p);page=browser.new_page(viewport={'width':args.width,'height':args.height},device_scale_factor=1,service_workers='block')
        allowed_origin=f'http://127.0.0.1:{server.server_port}/'
        def local_assets_only(route):
            target=route.request.url
            if target.startswith(allowed_origin) or target.startswith(('data:','blob:')):route.continue_()
            else:network_blocked.append(target.split('?')[0]);route.abort()
        page.route('**/*',local_assets_only)
        page.on('pageerror',lambda e:errors.append(str(e)))
        if local_font_config:page.add_init_script(init_script(local_font_config))
        page.goto(url)
        if local_font_config:local_font_report=await_fonts(page)
        page.wait_for_function('window.READY===true || Boolean(window.ERROR)',timeout=60000)
        error=page.evaluate('window.ERROR || null')
        if error:raise RuntimeError('Scene failed: '+str(error))
        if local_font_config and not page.evaluate('window.MOTION_TEXT_LAYOUT_READY===true'):
            raise RuntimeError('Scene must await MOTION_LOCAL_FONTS_READY and recalculate text layout before setting MOTION_TEXT_LAYOUT_READY=true and READY=true. See LOCAL_FONTS.md.')
        page.evaluate('document.fonts.ready');page.wait_for_function("typeof window.seek==='function'")
        page.evaluate("async()=>{if(typeof window.pauseForExport==='function')await window.pauseForExport()}")
        frame=page.locator('#scene')
        assert frame.count()==1,'Expected one #scene output element'
        assert page.evaluate("document.querySelector('#scene').getBoundingClientRect().width") == args.width,'Scene output width differs from requested render'
        assert page.evaluate("document.querySelector('#scene').getBoundingClientRect().height") == args.height,'Scene output height differs from requested render'
        capture=FrameCapture(page,args.capture,args.width,args.height)
        print('Capture mode: '+capture.mode,flush=True)
        times=set([0,args.duration-1/args.fps,min(.5,args.duration/2),min(1,args.duration/2)])
        times.update(range(2,int(args.duration),2))
        if args.probe_times:times.update(float(x) for x in args.probe_times.split(','))
        times=sorted(t for t in times if 0<=t<args.duration)
        tiles=[]
        for n,t in enumerate(times):
            data=capture.grab(t)
            (out.parent/f'frame_{t:.3f}.jpg').write_bytes(data)
            tile=Image.open(io.BytesIO(data)).resize((480,270));tiles.append(tile)
        sheet=Image.new('RGB',(1920,((len(tiles)+3)//4)*290));draw=ImageDraw.Draw(sheet)
        for n,tile in enumerate(tiles):
            x,y=(n%4)*480,(n//4)*290;sheet.paste(tile,(x,y));draw.text((x+6,y+273),f'{times[n]:.3f}s',fill='white')
        sheet.save(out.parent/'contact-sheet.jpg')
        if page.evaluate("typeof window.exportTimeline==='function'"):
            timeline=page.evaluate('()=>window.exportTimeline()')
            (out.parent/'ae_timeline.json').write_text(json.dumps(timeline,ensure_ascii=False),encoding='utf8')
        if not args.preview_only:
            command=[ff,'-y','-v','error','-f','image2pipe','-framerate',str(args.fps),'-c:v','mjpeg','-i','-']
            if args.audio:command+=['-i',str(args.audio.resolve()),'-af','apad','-c:a','aac','-b:a','192k']
            else:command+=['-an']
            command+=['-t',str(args.duration),'-vf','scale=in_range=full:out_range=tv','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-color_range','tv','-movflags','+faststart',str(out)]
            proc=subprocess.Popen(command,stdin=subprocess.PIPE)
            for n in range(round(args.duration*args.fps)):
                data=capture.grab(n/args.fps)
                wait_started=time.perf_counter();proc.stdin.write(data);encode_wait+=time.perf_counter()-wait_started
                if n%72==0:print(f'{n}/{round(args.duration*args.fps)} frames',flush=True)
            proc.stdin.close()
            wait_started=time.perf_counter();result=proc.wait();encode_wait+=time.perf_counter()-wait_started
            if result:raise RuntimeError('FFmpeg encode failed')
        browser.close()
    if errors:raise RuntimeError('JavaScript errors: '+str(errors))
    if network_blocked:raise RuntimeError('Scene has unpackaged network dependencies: '+str(sorted(set(network_blocked))))
    checks={'mode':'stills_only' if args.preview_only else 'video','duration_requested':args.duration,'fps':args.fps,'dimensions':[args.width,args.height],'frames_expected':round(args.duration*args.fps),'frames':0 if args.preview_only else round(args.duration*args.fps),'js_errors':errors,'keyframes':times,'audio':bool(args.audio),'AE':'not run','visual_review':'requires inspection of contact sheet and the actual MP4','capture_profile':capture.stats(),'ffmpeg_backpressure_seconds':round(encode_wait,3)}
    if not args.preview_only:
        subprocess.run([ff,'-v','error','-i',str(out),'-f','null','-'],check=True)
        if args.gif_preview:subprocess.run([ff,'-y','-v','error','-i',str(out),'-filter_complex','fps=10,scale=720:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse=dither=bayer','-loop','0',str(out.parent/'preview.gif')],check=True)
        ffprobe=__import__('shutil').which('ffprobe')
        if ffprobe:
            checks['probe']=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_streams','-show_format','-of','json',str(out)]))
        else:
            import imageio_ffmpeg
            reader=imageio_ffmpeg.read_frames(str(out));checks['probe']=next(reader);reader.close()
            assert list(checks['probe']['size'])==[args.width,args.height]
            assert abs(checks['probe']['fps']-args.fps)<.01
        checks['decode']='pass'
    checks['local_fonts']=local_font_report
    checks['text_layout_ready']=bool(local_font_config)
    checks['total_seconds']=round(time.perf_counter()-started,3)
    (out.parent/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf8')
    print('Render checks passed. Inspect contact-sheet.jpg and the actual MP4 before delivery.',flush=True)
finally:
    if proc and proc.poll() is None:
        proc.kill();proc.wait()
    server.shutdown()
