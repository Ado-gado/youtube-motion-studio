from pathlib import Path
import re,json,sys
from runtime import ROOT,check_manifest

def audit():
    problems=check_manifest()
    for folder in ['scripts','skills']:
        for file in (ROOT/folder).rglob('*.py'):
            try:compile(file.read_text(encoding='utf8'),str(file),'exec')
            except Exception as e:problems.append(str(file.relative_to(ROOT))+': '+str(e))
    # Generated source has no user-specific filesystem paths; text must be valid UTF-8.
    for f in ROOT.rglob('*'):
        if f.name=='.install-report.json':continue
        if not f.is_file() or any(x in f.parts for x in ['.venv','.git','.agents','outputs','scenes','__pycache__']):continue
        if f.suffix not in ['.py','.md','.html','.json','.jsx','.txt']:continue
        try:s=f.read_text(encoding='utf8')
        except UnicodeError:problems.append(str(f.relative_to(ROOT))+': invalid UTF-8');continue
        if re.search(r'[CE]:[\\/](?:Users|Codex)',s):problems.append(str(f.relative_to(ROOT))+': old absolute path')
        if '\ufffd' in s:problems.append(str(f.relative_to(ROOT))+': replacement character')
    skill=ROOT/'skills/youtube-motion-design/SKILL.md'
    s=skill.read_text(encoding='utf8')
    if not s.startswith('---\nname: youtube-motion-design\n'):problems.append('invalid skill frontmatter')
    return {'version':(ROOT/'VERSION').read_text().strip(),'manifest':'pass' if not check_manifest() else 'fail','problems':problems,'files':len(json.loads((ROOT/'manifest.json').read_text())['files'])}
if __name__=='__main__':
    result=audit();print(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(bool(result['problems']))
