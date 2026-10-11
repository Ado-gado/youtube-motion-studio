from pathlib import Path
import argparse,json,zipfile,math
from runtime import ROOT
arg=argparse.ArgumentParser();arg.add_argument('scene',type=Path);arg.add_argument('timeline',type=Path);arg.add_argument('out',type=Path);a=arg.parse_args()
scene=a.scene.resolve();scene.relative_to(ROOT);data=json.loads(a.timeline.read_text(encoding='utf8'))
for key in ['width','height','fps','duration','paper','texts','layers']:
    if key not in data:raise SystemExit('Manifest missing '+key)
images={}
for layer in data['layers']:
    if layer['type'] not in ['image','text','rect','path']:raise SystemExit('Native AE unsupported layer: '+layer['type'])
    if layer['type']=='image':
        rel=Path(layer['file'])
        if rel.is_absolute() or '..' in rel.parts:raise SystemExit('Use local relative image paths for AE')
        src=(scene.parent/rel).resolve();src.relative_to(ROOT)
        if not src.is_file():raise SystemExit('Missing '+str(src))
        images[rel.as_posix()]=src
    for time,state in layer['samples']:
        if not math.isfinite(time) or any(not math.isfinite(state[k]) for k in ['x','y','scale','rot','opacity','reveal']):raise SystemExit('Non-finite keyframe')
a.out.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(a.out,'w',zipfile.ZIP_DEFLATED) as z:
    z.writestr('ae_timeline.json',json.dumps(data,ensure_ascii=False))
    z.write(ROOT/'scripts/build_after_effects.jsx','build_after_effects.jsx')
    for rel,src in images.items():z.write(src,rel)
    for font in (ROOT/'fonts').glob('*'):z.write(font,'fonts/'+font.name)
    if (scene.parent/'ASSETS.md').exists():z.write(scene.parent/'ASSETS.md','ASSETS.md')
    z.writestr('README.txt','Install the fonts, then run build_after_effects.jsx in After Effects using File > Scripts > Run Script File. Native RU/EN text is editable. Save As .aep. This builder has not been run in AE here. Compare the render and font warnings; complex effects may differ.')
print('AE bundle written; native AE execution remains untested')
