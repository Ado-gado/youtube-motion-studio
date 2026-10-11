"""Read scene assets straight from the ZIP; no permanent extraction for preview."""
import http.server
import json
import mimetypes
import threading
import urllib.parse
import zipfile
from pathlib import PurePosixPath
from .model import font_config


class ArchiveServer:
    def __init__(self, source, config=None):
        self.source = source
        self.overrides = {}
        self.set_config(config)
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self): self.serve(False)
            def do_HEAD(self): self.serve(True)
            def serve(self, head):
                name = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip('/')
                if name not in owner.source['manifest']['files'] and name not in owner.overrides:
                    self.send_error(404); return
                try:
                    with zipfile.ZipFile(owner.source['path']) as archive:
                        override = owner.overrides.get(name)
                        size = len(override) if override is not None else archive.getinfo(name).file_size
                        start, end = 0, size-1
                        partial = self.headers.get('Range')
                        if partial:
                            import re
                            match = re.fullmatch(r'bytes=(\d*)-(\d*)', partial)
                            if not match or not (match[1] or match[2]):
                                self.send_error(416); return
                            if match[1]:
                                start = int(match[1]); end = min(int(match[2]), end) if match[2] else end
                            else:
                                start = max(0, size-int(match[2]))
                            if start > end or start >= size:
                                self.send_error(416); return
                        self.send_response(206 if partial else 200)
                        mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
                        if name.endswith('.js'): mime = 'application/javascript'
                        self.send_header('Content-Type', mime)
                        self.send_header('Content-Length', str(max(0, end-start+1)))
                        self.send_header('Accept-Ranges', 'bytes')
                        self.send_header('Cache-Control', 'no-store')
                        if partial: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                        self.end_headers()
                        if head: return
                        if override is not None:
                            self.wfile.write(override[start:end+1]); return
                        with archive.open(name) as stream:
                            if start: stream.seek(start)
                            remaining = end-start+1
                            while remaining > 0:
                                chunk = stream.read(min(256*1024, remaining))
                                if not chunk: break
                                self.wfile.write(chunk); remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError): pass

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f'http://127.0.0.1:{self.server.server_port}/'
        self.url = self.origin + urllib.parse.quote(source['manifest']['render']['scene']) + '?capture'

    def set_config(self, config):
        self.overrides = {}
        if config is not None:
            parent = PurePosixPath(self.source['manifest']['render']['scene']).parent
            self.overrides[self.source['editor_name']] = json.dumps(config, ensure_ascii=False).encode('utf8')
            fonts = font_config(config)
            if fonts:
                self.overrides[(parent/'local-fonts.json').as_posix()] = json.dumps(fonts).encode('utf8')

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
