import base64,time

class FrameCapture:
    """Canvas bitmap export is opt-in; DOM/CSS compositions keep screenshots."""
    def __init__(self,page,mode,width,height):
        self.page=page;self.element=page.locator('#scene');self.count=0;self.seek_seconds=0;self.capture_seconds=0;self.wall_seconds=0
        info=page.evaluate('''({width,height})=>{
            const c=document.querySelector('#scene');
            if(!(c instanceof HTMLCanvasElement))return {safe:false,reason:'not a canvas'};
            const ctx=c.getContext('2d');
            if(!ctx || !ctx.getContextAttributes || ctx.getContextAttributes().alpha!==false)return {safe:false,reason:'requires opaque 2D canvas'};
            if(c.width!==width || c.height!==height)return {safe:false,reason:'bitmap size differs'};
            for(let e=c;e;e=e.parentElement){
                const s=getComputedStyle(e);
                if(s.opacity!=='1' || s.filter!=='none' || s.transform!=='none' || s.clipPath!=='none' || s.mixBlendMode!=='normal')return {safe:false,reason:'CSS contributes to the image'};
            }
            const s=getComputedStyle(c);
            if(['borderTopWidth','borderLeftWidth','borderBottomWidth','borderRightWidth','paddingTop','paddingLeft','paddingBottom','paddingRight'].some(k=>parseFloat(s[k])!==0) || s.boxShadow!=='none')return {safe:false,reason:'canvas decoration'};
            return {safe:true,optIn:c.dataset.renderExport==='canvas'};
        }''',{'width':width,'height':height})
        if mode=='canvas' and not info['safe']:raise ValueError('Canvas capture is unsafe: '+info['reason'])
        self.mode='canvas' if mode=='canvas' or (mode=='auto' and info['safe'] and info.get('optIn')) else 'screenshot'

    def grab(self,t,png=False):
        wall=time.perf_counter()
        if self.mode=='canvas':
            r=self.page.evaluate('''async ({t,png})=>{
                const start=performance.now();await window.seek(t);const drawn=performance.now();
                const data=document.querySelector('#scene').toDataURL(png?'image/png':'image/jpeg',.95);
                return {data,seek:(drawn-start)/1000,capture:(performance.now()-drawn)/1000};
            }''',{'t':t,'png':png})
            self.seek_seconds+=r['seek'];self.capture_seconds+=r['capture'];data=base64.b64decode(r['data'].split(',',1)[1])
        else:
            start=time.perf_counter();self.page.evaluate('(t)=>window.seek(t)',t);self.seek_seconds+=time.perf_counter()-start
            start=time.perf_counter();data=self.element.screenshot(type='png') if png else self.element.screenshot(type='jpeg',quality=95)
            self.capture_seconds+=time.perf_counter()-start
        self.wall_seconds+=time.perf_counter()-wall;self.count+=1
        return data

    def stats(self):
        return {'mode':self.mode,'captured_frames':self.count,'seek_seconds':round(self.seek_seconds,3),'capture_seconds':round(self.capture_seconds,3),'wall_seconds':round(self.wall_seconds,3),'mean_frame_ms':round(1000*self.wall_seconds/max(1,self.count),2)}
