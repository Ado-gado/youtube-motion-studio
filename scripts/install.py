from pathlib import Path
import sys,subprocess,venv,argparse,shutil,json,re,os
from runtime import ROOT,check_manifest,browser_path

parser=argparse.ArgumentParser(description='Install this studio only inside the selected project')
parser.add_argument('--project-root',type=Path,default=Path.cwd())
parser.add_argument('--browser',choices=['auto','chromium','system'],default='auto')
args=parser.parse_args()
if sys.version_info<(3,10):raise SystemExit('Python 3.10+ required')
project=args.project_root.resolve()
if str(project)==project.anchor:raise SystemExit('Choose a project directory, not filesystem root')
wrong=check_manifest()
if wrong:raise SystemExit('Source package checksum mismatch: '+', '.join(wrong))
env=ROOT/'.venv'
python=env/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
if not python.is_file() or not (env/'pyvenv.cfg').is_file():
    venv.EnvBuilder(with_pip=True).create(env)
subprocess.run([str(python),'-m','pip','install','--no-cache-dir','-r',str(ROOT/'requirements.txt')],check=True)
if args.browser=='system' and not browser_path():raise SystemExit('No system Chromium found')
if args.browser=='chromium' or (args.browser=='auto' and not browser_path()):
    subprocess.run([str(python),'-m','playwright','install','chromium'],check=True)
check=subprocess.run([str(python),str(ROOT/'scripts/doctor.py')],capture_output=True,text=True)
if check.returncode:
    print(check.stderr,file=sys.stderr)
    if sys.platform.startswith('linux'):print('If libraries are missing, run '+str(python)+' -m playwright install --with-deps chromium',file=sys.stderr)
    raise SystemExit(check.returncode)
# Environment is working before touching project instructions.
source=ROOT/'skills/youtube-motion-design';dest=project/'.agents/skills/youtube-motion-design'
marker=dest/'.motion-studio-managed'
if dest.exists() and not marker.exists():
    raise SystemExit('An unrelated youtube-motion-design skill already exists; choose another project or migrate it explicitly. Environment has been prepared, existing skill preserved.')
shutil.copytree(source,dest,dirs_exist_ok=True);marker.write_text(str(ROOT),encoding='utf8')
agent_file=project/'AGENTS.md';old=agent_file.read_text(encoding='utf8') if agent_file.exists() else ''
block='<!-- motion-studio:start -->\nDocumentary motion package: `'+os.path.relpath(ROOT,project)+'`. Before motion work read its STYLE.md, FEEDBACK.md, HANDOFF.md, WORKFLOW.md and skills/youtube-motion-design/SKILL.md. Deliver the current requested motion graphics as a finished MP4. Do not create websites, apps, dashboards, editors, unrelated content or sample/test videos unless explicitly requested. Installation runs doctor/audit only; no Gagarin/example render. Use V2 motion principles, not its subject, assets, wording or layout. Keep working sources in the project. The latest user instruction wins.\n<!-- motion-studio:end -->'
block=block.replace('Keep working sources in the project.', 'Keep working sources in the project. For the author-selected local-render mode read LOCAL_RENDER.md: cloud hands off a verified motion-job ZIP and the PC queue produces the MP4; no full cloud render unless requested. Do not call the archive a finished video.')
block=block.replace('The latest user instruction wins.', 'For every text scene read TEXT_LAYOUT.md. Never accidentally clip fully revealed text: preserve complete glyphs, descenders, diacritics and all lines across masks, containers, camera framing and object overlaps. This applies to every subject, font, language and output format. Recalculate layout after text or font changes; check the current scene before packaging and in the final MP4. Temporary reveal masks must finish with a complete readable state. The latest user instruction wins.')
pat=r'<!-- motion-studio:start -->.*?<!-- motion-studio:end -->'
new=re.sub(pat,lambda _:block,old,flags=re.S) if re.search(pat,old,re.S) else old.rstrip()+'\n\n'+block+'\n'
agent_file.write_text(new,encoding='utf8')
report={'version':(ROOT/'VERSION').read_text().strip(),'package':str(ROOT),'project':str(project),'doctor':json.loads(check.stdout),'installed_skill':str(dest)}
(ROOT/'.install-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print('Installed local studio '+report['version']+'; doctor passed. Read START_HERE.md. No demo video is required; wait for the current video brief.')
