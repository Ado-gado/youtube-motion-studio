from pathlib import Path, PurePosixPath
import copy
import hashlib
import json
import math
import os
import re
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from job_bundle import inspect_bundle, digest_file


def number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label}: допустимо от {low:g} до {high:g}')
    return value


def validate_editor(data, duration):
    data = copy.deepcopy(data)
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise ValueError('Неподдерживаемый формат motion-editor.json')
    texts = data.get('texts')
    if not isinstance(texts, list) or len(texts) > 200:
        raise ValueError('В motion-editor.json нужен список texts (до 200 надписей)')
    ids = set()
    for item in texts:
        if not isinstance(item, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(item.get('id', ''))):
            raise ValueError('У каждой надписи должен быть постоянный id')
        if item['id'] in ids:
            raise ValueError('Повторяется id надписи')
        ids.add(item['id'])
        item['label']=item.get('label',item['id'])
        if not isinstance(item['label'],str) or len(item['label'])>200:
            raise ValueError('Некорректное имя текстового слоя')
        if not isinstance(item.get('text'), str) or len(item['text']) > 10000:
            raise ValueError('Некорректный текст надписи')
        family = item.get('font', 'Lumios Brush')
        if not isinstance(family, str) or not family.strip() or len(family) > 120 or any(ord(c) < 32 for c in family):
            raise ValueError('Некорректное имя шрифта')
        item['font'] = family
        sources = item.get('fontSources', [family])
        if not isinstance(sources, list) or not 1 <= len(sources) <= 8 or any(not isinstance(s, str) or not s.strip() or len(s) > 120 or any(ord(c) < 32 for c in s) for s in sources):
            raise ValueError('Некорректные локальные имена шрифта')
        item['fontSources'] = sources
        item['weight'] = str(item.get('weight', '400'))
        if item['weight'] not in [str(x) for x in range(100, 1000, 100)]:
            raise ValueError('Некорректное начертание')
        for key, default, low, high in [('size', 80, 8, 1000), ('x', 100, -10000, 10000), ('y', 200, -10000, 10000), ('maxWidth', 1500, 10, 10000), ('lineHeight', 1.2, .5, 3), ('maxLines', 4, 1, 20)]:
            item[key] = number(item.get(key, default), low, high, key)
        item['start'] = number(item.get('start', 0), 0, duration, 'Начало')
        item['end'] = number(item.get('end', duration), 0, duration, 'Конец')
        span = item['end'] - item['start']
        if span <= 0:
            raise ValueError('Конец надписи должен быть позже начала')
        item['enter'] = number(item.get('enter', min(.65, span/2)), 0, span, 'Вход')
        item['exit'] = number(item.get('exit', min(.3, span/2)), 0, span, 'Выход')
        if item['enter'] + item['exit'] > span + .00001:
            raise ValueError('Вход и выход длиннее времени показа надписи')
        item['color'] = item.get('color', '#f3eddd')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', item['color']):
            raise ValueError('Цвет должен быть в формате #RRGGBB')
    return data


def font_config(config):
    unique = {}
    for item in config['texts']:
        key = (item['font'], item['weight'])
        if key in unique and unique[key]['sources'] != item['fontSources']:
            raise ValueError('Одинаковые шрифты должны иметь одинаковые fontSources')
        unique[key] = {'family': item['font'], 'sources': item['fontSources'], 'weight': item['weight'], 'style': 'normal'}
    return {'schema': 1, 'fonts': list(unique.values())} if unique else None


def read_archive(path, verify=True, cancel=None):
    path = Path(path).resolve()
    manifest = inspect_bundle(path)
    scene = PurePosixPath(manifest['render']['scene'])
    editor_name = (scene.parent / 'motion-editor.json').as_posix()
    with zipfile.ZipFile(path) as archive:
        if verify:
            for name, expected in manifest['files'].items():
                h = hashlib.sha256()
                with archive.open(name) as stream:
                    while chunk := stream.read(1024*1024):
                        if cancel and cancel.is_set():
                            raise InterruptedError('Импорт отменён')
                        h.update(chunk)
                if h.hexdigest() != expected:
                    raise ValueError('Повреждён архив: ' + name)
        config = None
        if editor_name in manifest['files']:
            if archive.getinfo(editor_name).file_size > 2*1024*1024:
                raise ValueError('Слишком большой motion-editor.json')
            config = validate_editor(json.loads(archive.read(editor_name).decode('utf-8-sig')), manifest['render']['duration'])
    return {'path': str(path), 'sha256': digest_file(path), 'manifest': manifest, 'editor_name': editor_name, 'config': config, 'bytes': path.stat().st_size}


def new_clip(source):
    return {'id': uuid.uuid4().hex, 'archive': source['path'], 'sha256': source['sha256'], 'title': source['manifest'].get('title') or Path(source['path']).stem,
            'render': copy.deepcopy(source['manifest']['render']), 'editor': copy.deepcopy(source['config'])}


def new_project():
    return {'schema': 1, 'type': 'documentary-motion-project', 'title': 'Новый проект', 'clips': []}


def save_project(project, path):
    path = Path(path).resolve()
    data = copy.deepcopy(project)
    for clip in data['clips']:
        try:
            clip['archive'] = os.path.relpath(clip['archive'], path.parent)
        except ValueError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.saving')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')
    temporary.replace(path)


def load_project(path):
    path = Path(path).resolve()
    if path.stat().st_size > 20*1024*1024:
        raise ValueError('Слишком большой файл проекта')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('schema') != 1 or data.get('type') != 'documentary-motion-project' or not isinstance(data.get('clips'), list):
        raise ValueError('Это не проект редактора Motion Studio')
    if len(data['clips']) > 10000:
        raise ValueError('Слишком много записей проекта')
    ids = set()
    for clip in data['clips']:
        if not isinstance(clip, dict) or not isinstance(clip.get('id'), str) or clip['id'] in ids:
            raise ValueError('Некорректные идентификаторы фрагментов')
        ids.add(clip['id'])
        if not re.fullmatch('[a-f0-9]{64}', str(clip.get('sha256', ''))):
            raise ValueError('В проекте нет контрольной суммы исходного ZIP')
        clip['archive'] = str((path.parent / clip['archive']).resolve())
        if clip.get('editor') is not None:
            clip['editor'] = validate_editor(clip['editor'], number(clip['render']['duration'], .01, 1800, 'Длительность'))
    return data


def check_clip_source(clip):
    source = read_archive(clip['archive'])
    if source['sha256'] != clip['sha256']:
        raise ValueError('Исходный ZIP изменился. Добавьте новую версию отдельно или восстановите оригинал.')
    if clip['render'] != source['manifest']['render']:
        raise ValueError('Параметры исходной сцены в проекте изменены. Добавьте архив заново.')
    if clip.get('editor') is not None:
        if source['config'] is None:
            raise ValueError('Архив не поддерживает редактирование текста')
        config = validate_editor(clip['editor'], clip['render']['duration'])
        if {x['id'] for x in config['texts']} != {x['id'] for x in source['config']['texts']}:
            raise ValueError('Набор текстовых слоёв не совпадает с исходником')
    return source
