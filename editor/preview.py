import json
import queue
import threading
import zipfile
from pathlib import Path, PurePosixPath
from playwright.sync_api import sync_playwright
from .model import check_clip_source, font_config
from .archive_server import ArchiveServer
from runtime import launch
from local_fonts import init_script, await_fonts
from frame_capture import FrameCapture


class PreviewWorker(threading.Thread):
    def __init__(self, output):
        super().__init__(daemon=True)
        self.output = output
        self.requests = queue.Queue()
        self.stopping = threading.Event()
        self.browser = self.server = self.page = self.capture = None
        self.current_key = None
        self.source_key = self.source = None

    def frame(self, clip, seconds, token):
        self.requests.put(('frame', clip, seconds, token))

    def pause(self):
        event = threading.Event()
        self.requests.put(('close', event))
        return event

    def stop(self):
        self.stopping.set(); self.requests.put(('stop',))

    def close_scene(self):
        if self.browser:
            self.browser.close(); self.browser = None
        if self.server:
            self.server.close(); self.server = None
        self.page = self.capture = self.current_key = None

    def open_scene(self, p, clip):
        path = Path(clip['archive'])
        stat = path.stat()
        source_key = (str(path), stat.st_size, stat.st_mtime_ns, clip['sha256'])
        key = (source_key, json.dumps(clip.get('editor'), sort_keys=True, ensure_ascii=False))
        if key == self.current_key:
            return
        self.close_scene()
        if source_key != self.source_key:
            self.source = check_clip_source(clip); self.source_key = source_key
        self.server = ArchiveServer(self.source, clip.get('editor'))
        r = self.source['manifest']['render']
        self.browser = launch(p)
        self.page = self.browser.new_page(viewport={'width':r['width'], 'height':r['height']}, device_scale_factor=1, service_workers='block')
        errors, blocked = [], []
        def route(req):
            if req.request.url.startswith((self.server.origin, 'data:', 'blob:')):
                req.continue_()
            else:
                blocked.append(req.request.url.split('?')[0]); req.abort()
        self.page.route('**/*', route)
        self.page.on('pageerror', lambda err: errors.append(str(err)))
        fonts = font_config(clip['editor']) if clip.get('editor') is not None else None
        if clip.get('editor') is None:
            name = str(PurePosixPath(r['scene']).parent/'local-fonts.json')
            if name in self.source['manifest']['files']:
                with zipfile.ZipFile(path) as archive:
                    fonts = json.loads(archive.read(name).decode('utf-8-sig'))
        if fonts:
            self.page.add_init_script(init_script(fonts))
        self.page.goto(self.server.url, timeout=30000)
        if fonts: await_fonts(self.page)
        self.page.wait_for_function('window.READY===true || Boolean(window.ERROR)', timeout=30000)
        error = self.page.evaluate('window.ERROR || null')
        if error: raise RuntimeError(str(error))
        if errors or blocked:
            raise RuntimeError('; '.join(errors + ['Ресурс не включён в ZIP: '+u for u in blocked]))
        self.page.evaluate('document.fonts.ready')
        self.page.evaluate("async()=>{if(typeof window.pauseForExport==='function')await window.pauseForExport()}")
        if clip.get('editor') is not None:
            if not self.page.evaluate('window.MOTION_EDITOR_APPLIED===true && window.MOTION_TEXT_LAYOUT_READY===true'):
                raise RuntimeError('Сцена не применяет motion-editor.json. Попросите Emergent подключить runtime/motion-editor.js по EDITOR_SCENES.md.')
        self.capture = FrameCapture(self.page, r.get('capture', 'auto'), r['width'], r['height'])
        self.current_key = key

    def run(self):
        try:
            with sync_playwright() as p:
                while not self.stopping.is_set():
                    request = self.requests.get()
                    if request[0] == 'frame':
                        # Drop superseded seeks; never drop a close/stop request.
                        while not self.requests.empty():
                            next_request = self.requests.get()
                            request = next_request
                            if request[0] != 'frame': break
                    if request[0] == 'stop': break
                    if request[0] == 'close':
                        self.close_scene(); request[1].set(); continue
                    _, clip, seconds, token = request
                    try:
                        self.open_scene(p, clip)
                        seconds = max(0, min(seconds, clip['render']['duration']-1/clip['render']['fps']))
                        data = self.capture.grab(seconds, png=True)
                        self.output.put(('preview', token, data, seconds))
                    except Exception as error:
                        self.close_scene()
                        self.output.put(('preview_error', token, str(error)))
                self.close_scene()
        except Exception as error:
            self.output.put(('fatal_preview', str(error)))
