"""One local queue for scene archives from any Emergent account. No web app."""
from pathlib import Path
from contextlib import contextmanager
import argparse,json,os,shutil,subprocess,sys,time,uuid,urllib.request,urllib.parse,signal
from datetime import datetime,timezone
from runtime import ROOT
from job_bundle import MAX_BYTES,digest_file,inspect_bundle,unpack_bundle

DEFAULT_QUEUE=ROOT/'LOCAL_RENDER'

def stamp():return datetime.now(timezone.utc).isoformat()

def prepare(queue):
    queue=Path(queue).resolve()
    if queue==Path(queue.anchor):raise ValueError('Choose a project queue, not filesystem root')
    for part in ['inbox','work','ready','logs']:(queue/part).mkdir(parents=True,exist_ok=True)
    return queue

@contextmanager
def worker_lock(queue):
    f=(queue/'worker.lock').open('a+b')
    if f.tell()==0:f.write(b'0');f.flush()
    f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl;fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:f.close();raise RuntimeError('Worker already running')
    try:yield
    finally:
        f.seek(0)
        if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
        else:fcntl.flock(f,fcntl.LOCK_UN)
        f.close()

def running(queue):
    try:
        with worker_lock(queue):return False
    except RuntimeError:return True

def load_state(queue):
    p=queue/'status.json'
    return json.loads(p.read_text(encoding='utf8')) if p.exists() else {'jobs':{},'seen':{}}

def save_state(queue,state):
    state['updated_utc']=stamp();tmp=queue/'status.json.part'
    tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(queue/'status.json')

def emit(queue,event,**fields):
    data={'time':stamp(),'event':event,**fields}
    with (queue/'events.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(data,ensure_ascii=False)+'\n')
    print(json.dumps(data,ensure_ascii=False),flush=True)

def enqueue_file(queue,source):
    if Path(source).is_symlink():raise ValueError('Do not submit symlinks')
    source=Path(source).resolve()
    if not source.is_file() or source.is_symlink() or source.stat().st_size>MAX_BYTES:raise ValueError('Invalid or oversized scene archive')
    inspect_bundle(source);sha=digest_file(source);target=queue/'inbox'/('motion-job-'+sha+'.zip')
    if source!=target and not target.exists():
        tmp=target.with_suffix('.zip.part');shutil.copyfile(source,tmp)
        if digest_file(tmp)!=sha:raise ValueError('Source changed during copy')
        tmp.replace(target)
    return target

def download(queue,url):
    parts=urllib.parse.urlsplit(url)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password:raise ValueError('Use an HTTPS archive link without embedded credentials')
    temp=queue/'inbox'/('download-'+uuid.uuid4().hex+'.part')
    request=urllib.request.Request(url,headers={'User-Agent':'Documentary-Motion-Local-Renderer'})
    try:
        with urllib.request.urlopen(request,timeout=45) as response,temp.open('xb') as dst:
            if urllib.parse.urlsplit(response.url).scheme!='https':raise ValueError('Unsafe redirect')
            count=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk:break
                count+=len(chunk)
                if count>MAX_BYTES:raise ValueError('Download exceeds 1 GiB')
                dst.write(chunk)
        inspect_bundle(temp);sha=digest_file(temp);target=queue/'inbox'/('motion-job-'+sha+'.zip')
        if target.exists():temp.unlink()
        else:temp.replace(target)
        return target
    except Exception:
        if temp.exists():temp.unlink()
        raise

class Worker:
    def __init__(self,queue,downloads=None):
        self.queue=queue;self.downloads=Path(downloads).resolve() if downloads else None;self.state=load_state(queue)
        for job in self.state['jobs'].values():
            if job['status']=='rendering':job['status']='pending'

    def discover(self):
        retry=self.queue/'RETRY_ERRORS'
        if retry.exists():
            count=0
            for job in self.state['jobs'].values():
                if job['status']=='error':job['status']='pending';count+=1
            save_state(self.queue,self.state);retry.unlink()
            emit(self.queue,'retry_requested',jobs=count)
        folders=[self.queue/'inbox']+([self.downloads] if self.downloads and self.downloads.exists() else [])
        changed=False
        for folder in folders:
            for source in sorted(folder.glob('motion-job-*.zip')):
                if not source.is_file() or source.is_symlink():continue
                try:st=source.stat()
                except OSError:continue
                if time.time()-st.st_mtime<2:continue
                key=str(source.resolve());fingerprint=[st.st_size,st.st_mtime_ns]
                if self.state['seen'].get(key)==fingerprint:continue
                try:
                    archive=enqueue_file(self.queue,source);sha=digest_file(archive)
                    if sha not in self.state['jobs']:
                        manifest=inspect_bundle(archive)
                        self.state['jobs'][sha]={'status':'pending','archive':str(archive),'job_id':manifest['job_id'],'title':manifest.get('title','scene'),'account_label':manifest.get('account_label',''),'received_utc':stamp()}
                        emit(self.queue,'queued',job_id=manifest['job_id'])
                except Exception as e:emit(self.queue,'rejected_archive',filename=source.name,error=str(e))
                self.state['seen'][key]=fingerprint;changed=True
        if changed:save_state(self.queue,self.state)

    def render_next(self):
        pending=next(((sha,j) for sha,j in self.state['jobs'].items() if j['status']=='pending'),None)
        if not pending:return False
        sha,job=pending;job['status']='rendering';job['started_utc']=stamp();save_state(self.queue,self.state)
        work=self.queue/'work'/(job['job_id']+'-'+sha[:8]+'-'+uuid.uuid4().hex[:6])
        output=self.queue/'ready'/(job['job_id']+'-'+sha[:8]);output.mkdir(parents=True,exist_ok=True)
        log=self.queue/'logs'/(job['job_id']+'-'+sha[:8]+'.log')
        try:
            data=unpack_bundle(Path(job['archive']),work);r=data['render']
            command=[sys.executable,'-X','utf8',str(ROOT/'scripts/render_scene.py'),str(work/r['scene']),'--scene-root',str(work),'--duration',str(r['duration']),'--fps',str(r['fps']),'--width',str(r['width']),'--height',str(r['height']),'--capture',r.get('capture','auto'),'--out',str(output/'video.mp4')]
            if r.get('audio'):command+=['--audio',str(work/r['audio'])]
            emit(self.queue,'rendering',job_id=job['job_id'])
            options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
            with log.open('w',encoding='utf8') as stream:
                child=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,**options)
                try:code=child.wait(timeout=max(300,min(7200,r['duration']*180)))
                except subprocess.TimeoutExpired:
                    if child.poll() is None:
                        if os.name=='nt':subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],stdout=stream,stderr=subprocess.STDOUT)
                        else:os.killpg(child.pid,signal.SIGKILL)
                        child.wait()
                    raise RuntimeError('Render timed out; inspect the local log')
            if code:raise RuntimeError('Renderer failed; see '+str(log))
            checks=json.loads((output/'checks.json').read_text(encoding='utf8'))
            if checks.get('decode')!='pass' or not (output/'video.mp4').is_file():raise RuntimeError('No validated MP4 produced')
            job.update(status='done',video=str(output/'video.mp4'),checks=str(output/'checks.json'),work=str(work),completed_utc=stamp())
            emit(self.queue,'done',job_id=job['job_id'],video=job['video'])
        except Exception as e:
            job.update(status='error',error=str(e),work=str(work),log=str(log));emit(self.queue,'error',job_id=job['job_id'],error=str(e))
        save_state(self.queue,self.state);return True

def main():
    p=argparse.ArgumentParser(description='Local scene queue; handles archives from any account without account login')
    sub=p.add_subparsers(dest='cmd',required=True)
    watch=sub.add_parser('watch');watch.add_argument('--downloads',type=Path);watch.add_argument('--once',action='store_true')
    start=sub.add_parser('start');start.add_argument('--downloads',type=Path)
    submit=sub.add_parser('submit');src=submit.add_mutually_exclusive_group(required=True);src.add_argument('--file',type=Path);src.add_argument('--url')
    inspect=sub.add_parser('inspect');inspect.add_argument('archive',type=Path);inspect.add_argument('--extract',type=Path)
    sub.add_parser('status');sub.add_parser('stop');sub.add_parser('retry-errors')
    for action in sub.choices.values():action.add_argument('--queue',type=Path,default=DEFAULT_QUEUE)
    a=p.parse_args();queue=prepare(a.queue)
    if a.cmd=='inspect':
        data=unpack_bundle(a.archive,a.extract) if a.extract else inspect_bundle(a.archive)
        print(json.dumps({'job_id':data['job_id'],'render':data['render'],'files':len(data['files']),'checksums_verified':bool(a.extract),'video_rendered':False},ensure_ascii=False,indent=2));return
    if a.cmd=='submit':
        archive=download(queue,a.url) if a.url else enqueue_file(queue,a.file)
        print('Queued archive: '+str(archive));return
    if a.cmd=='stop':
        (queue/'STOP').write_text('Stop after the current job\n',encoding='utf8');print('Stop requested; current video will finish first.');return
    if a.cmd=='retry-errors':
        (queue/'RETRY_ERRORS').write_text('Retry failed jobs after their cause has been fixed\n',encoding='utf8')
        print('Failed jobs will be retried by the worker; completed videos are unchanged. Start the worker if it is stopped.');return
    if a.cmd=='status':
        state=load_state(queue);counts={s:sum(j['status']==s for j in state['jobs'].values()) for s in ['pending','rendering','done','error']}
        print(json.dumps({'running':running(queue),'queue':str(queue),'ready':str(queue/'ready'),'counts':counts,'jobs':list(state['jobs'].values())},ensure_ascii=True,indent=2));return
    if a.cmd=='start':
        if running(queue):print('Worker is already running. Videos: '+str(queue/'ready'));return
        command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),'watch','--queue',str(queue)]
        if a.downloads:command+=['--downloads',str(a.downloads.resolve())]
        log=queue/'logs'/('worker-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
        options={'creationflags':subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
        # File handles, not pipes: the launching PowerShell/terminal can exit.
        with log.with_suffix('.log').open('w',encoding='utf8') as stdout,log.with_suffix('.stderr').open('w',encoding='utf8') as stderr:
            child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,cwd=ROOT,close_fds=True,**options)
        for _ in range(20):
            if child.poll() is not None:raise RuntimeError('Worker stopped; inspect '+str(log.with_suffix('.stderr')))
            if running(queue):break
            time.sleep(.1)
        if not running(queue):raise RuntimeError('Worker did not acquire its lock; inspect local logs')
        print('Worker started. Downloads: '+str(a.downloads)+'. Videos: '+str(queue/'ready'));return
    with worker_lock(queue):
        stop=queue/'STOP'
        if stop.exists():stop.unlink()
        worker=Worker(queue,a.downloads);save_state(queue,worker.state);emit(queue,'worker_started',downloads=str(a.downloads) if a.downloads else None)
        while not stop.exists():
            worker.discover()
            if worker.render_next():continue
            if a.once:break
            time.sleep(2)
        emit(queue,'worker_stopped')

if __name__=='__main__':main()
