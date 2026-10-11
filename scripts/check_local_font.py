"""Check the real export browser, not a fallback-positive document.fonts.check()."""
import argparse
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from runtime import launch
from local_fonts import init_script, await_fonts, read_config


def main():
    parser = argparse.ArgumentParser(description='Verify a required desktop font without creating a video')
    parser.add_argument('--scene', type=Path)
    parser.add_argument('--family', default='Lumios Brush')
    parser.add_argument('--source', action='append')
    args = parser.parse_args()
    config = read_config(args.scene) if args.scene else {
        'schema': 1, 'fonts': [{'family': args.family, 'sources': args.source or (
            ['Lumios Brush', 'Lumios Brush Regular'] if args.family == 'Lumios Brush' else [args.family]
        ), 'weight': '400', 'style': 'normal'}]
    }
    if not config:
        raise ValueError('This scene has no local-fonts.json')
    with sync_playwright() as p:
        browser = launch(p)
        try:
            page = browser.new_page()
            page.add_init_script(init_script(config))
            page.goto('about:blank')
            report = await_fonts(page)
            print(json.dumps({'browser': browser.version, 'fonts': report, 'video_created': False}, indent=2))
        finally:
            browser.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
