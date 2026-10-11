"""Bind declared desktop fonts without copying their files into a scene job."""
from pathlib import Path
import json

CONFIG_NAME = 'local-fonts.json'


def validate_config(data):
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise ValueError('local-fonts.json: expected schema 1')
    fonts = data.get('fonts')
    if not isinstance(fonts, list) or not 1 <= len(fonts) <= 16:
        raise ValueError('local-fonts.json: expected 1 to 16 desktop fonts')
    result = []
    families = set()
    for item in fonts:
        if not isinstance(item, dict):
            raise ValueError('local-fonts.json: invalid font entry')
        family = item.get('family')
        sources = item.get('sources')
        if not isinstance(family, str) or not 1 <= len(family) <= 120 or any(ord(c) < 32 for c in family):
            raise ValueError('local-fonts.json: invalid family')
        if not isinstance(sources, list) or not 1 <= len(sources) <= 8 or any(
            not isinstance(s, str) or not 1 <= len(s) <= 120 or any(ord(c) < 32 for c in s) for s in sources
        ):
            raise ValueError('local-fonts.json: use local desktop face names in sources')
        weight = str(item.get('weight', '400'))
        style = item.get('style', 'normal')
        if weight not in [str(n) for n in range(100, 1000, 100)] or style not in ['normal', 'italic', 'oblique']:
            raise ValueError('local-fonts.json: invalid weight or style')
        key = (family.casefold(), weight, style)
        if key in families:
            raise ValueError('local-fonts.json: duplicate face')
        families.add(key)
        result.append({'family': family, 'sources': sources, 'weight': weight, 'style': style})
    return {'schema': 1, 'fonts': result}


def read_config(scene):
    path = Path(scene).resolve().parent / CONFIG_NAME
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError('Invalid local-fonts.json file')
    return validate_config(json.loads(path.read_text(encoding='utf-8-sig')))


def init_script(config):
    # Only local() sources are constructed. No font bytes or network URLs are used.
    encoded = json.dumps(validate_config(config), ensure_ascii=True)
    return '''(() => {
      const config = CONFIG;
      window.MOTION_LOCAL_FONTS_READY = (async () => {
        const report = [];
        for (const item of config.fonts) {
          const source = item.sources.map(name => 'local(' + JSON.stringify(name) + ')').join(', ');
          const face = new FontFace(item.family, source, {weight:item.weight, style:item.style});
          try { await face.load(); }
          catch (error) {
            throw new Error('Required desktop font unavailable: ' + item.family +
              '. Activate/install the genuine font on this PC (Adobe Fonts: Creative Cloud, Added Fonts, Install), then retry. No substitute was rendered.');
          }
          document.fonts.add(face);
          report.push({family:item.family, weight:item.weight, style:item.style, status:face.status, source:'desktop-local'});
        }
        window.MOTION_LOCAL_FONT_REPORT = report;
        return report;
      })();
      window.MOTION_LOCAL_FONTS_READY.catch(error => { window.MOTION_LOCAL_FONT_ERROR = String(error.message || error); });
    })();'''.replace('CONFIG', encoded, 1)


def await_fonts(page):
    return page.evaluate('async () => await window.MOTION_LOCAL_FONTS_READY')
