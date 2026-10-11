/* Scene text contract v1. Local asset; no network services, no UI. */
(() => {
  const clamp = x => Math.max(0, Math.min(1, x));
  const ease = x => 1 - (1-clamp(x)) ** 3;
  async function load(path = 'motion-editor.json') {
    const response = await fetch(path);
    if (!response.ok) throw new Error('Не найден ' + path);
    const config = await response.json();
    if (config.schema !== 1 || !Array.isArray(config.texts)) throw new Error('Неподдерживаемый motion-editor.json');
    if (window.MOTION_LOCAL_FONTS_READY) await window.MOTION_LOCAL_FONTS_READY;
    else {
      const loaded = new Set();
      for (const item of config.texts) {
        const key = item.font + ':' + (item.weight || '400');
        if (loaded.has(key)) continue;
        const source = (item.fontSources || [item.font]).map(x => 'local(' + JSON.stringify(x) + ')').join(',');
        const face = new FontFace(item.font, source, {weight:String(item.weight || '400')});
        try { await face.load(); }
        catch (e) { throw new Error('На этом компьютере недоступен шрифт «' + item.font + '». Выберите установленный шрифт в редакторе.'); }
        document.fonts.add(face); loaded.add(key);
      }
    }
    const items = new Map(config.texts.map(item => [item.id, item]));
    const cache = new Map();
    function layout(ctx, item, options) {
      const spec = {...item, ...options};
      const key = JSON.stringify(spec);
      if (cache.has(key)) return cache.get(key);
      const size = spec.size || 80, width = spec.maxWidth || 1500;
      const font = `${spec.weight || '400'} ${size}px ${JSON.stringify(spec.font)}`;
      ctx.save(); ctx.font = font;
      const lines = [];
      for (const paragraph of spec.text.split('\n')) {
        let line = '';
        for (const word of paragraph.split(/\s+/).filter(Boolean)) {
          if (ctx.measureText(word).width > width) {
            ctx.restore(); throw new Error('Слово не помещается в надпись «' + (spec.label || spec.id) + '». Уменьшите размер шрифта или измените текст.');
          }
          const next = line ? line + ' ' + word : word;
          if (ctx.measureText(next).width > width && line) { lines.push(line); line = word; }
          else line = next;
        }
        lines.push(line);
      }
      if (lines.length > (spec.maxLines || 4)) {
        ctx.restore(); throw new Error('Слишком много строк в надписи «' + (spec.label || spec.id) + '». Уменьшите размер или измените текст.');
      }
      const step = size * (spec.lineHeight || 1.2);
      const metrics = lines.map(line => ctx.measureText(line));
      const left = Math.min(0, ...metrics.map(m => -m.actualBoundingBoxLeft));
      const right = Math.max(0, ...metrics.map(m => m.actualBoundingBoxRight));
      const top = Math.min(...metrics.map((m,i) => i*step-m.actualBoundingBoxAscent));
      const bottom = Math.max(...metrics.map((m,i) => i*step+m.actualBoundingBoxDescent));
      ctx.restore();
      const result = {spec, font, lines, step, left, right, top, bottom};
      cache.set(key, result); return result;
    }
    function drawText(ctx, id, seconds, options = {}) {
      const item = items.get(id);
      if (!item) throw new Error('Неизвестный текстовый слой: ' + id);
      if (!item.text || seconds < item.start || seconds >= item.end) return;
      const l = layout(ctx, item, options), spec = l.spec;
      const input = item.enter > 0 ? ease((seconds-item.start)/item.enter) : 1;
      const output = item.exit > 0 ? clamp((item.end-seconds)/item.exit) : 1;
      const x = spec.x || 0, y = spec.y || 0;
      const rise = (l.bottom-l.top+12)*(1-input);
      const shift = (1-output)*Math.min(24,spec.size*.3);
      const shadow = spec.shadow || {color:'rgba(0,0,0,.65)',blur:10,x:2,y:6};
      const padding = Math.max(5, (shadow.blur || 0)*2 + Math.abs(shadow.y || 0));
      if (input === 1 && output === 1 && spec.checkBounds !== false) {
        const transform = ctx.getTransform();
        const corners = [[x+l.left,y+l.top],[x+l.right,y+l.top],[x+l.right,y+l.bottom],[x+l.left,y+l.bottom]].map(([a,b]) => new DOMPoint(a,b).matrixTransform(transform));
        if (corners.some(p => p.x < 3 || p.y < 3 || p.x > ctx.canvas.width-3 || p.y > ctx.canvas.height-3))
          throw new Error('Надпись «' + (spec.label || id) + '» выходит за кадр. Измените размер или положение.');
      }
      ctx.save(); ctx.font=l.font; ctx.textAlign='left'; ctx.textBaseline='alphabetic';
      ctx.fillStyle=spec.color || '#f3eddd'; ctx.globalAlpha*=output;
      if (input < 1) {
        ctx.beginPath(); ctx.rect(x+l.left-padding,y+l.top-padding,l.right-l.left+2*padding,l.bottom-l.top+2*padding);ctx.clip();
      }
      ctx.shadowColor=shadow.color || 'transparent';ctx.shadowBlur=shadow.blur || 0;
      ctx.shadowOffsetX=shadow.x || 0;ctx.shadowOffsetY=shadow.y || 0;
      l.lines.forEach((line,i) => ctx.fillText(line,x,y+i*l.step+rise-shift));
      ctx.restore();
    }
    window.MOTION_EDITOR_APPLIED = true;
    window.MOTION_TEXT_LAYOUT_READY = true;
    return {config, drawText, get:id => items.get(id)};
  }
  window.MotionEditor = {load, version:1};
})();
