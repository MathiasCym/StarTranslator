"""Read-only Word/WPS PDF snapshots, displayed without browser reflow."""
import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .glossary import store

VERSION = 'word-native-1'


def _run(mode, source, output, page=1):
    shell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-STA', '-ExecutionPolicy', 'Bypass',
        '-File', str(Path(__file__).with_name('word_render.ps1')), '-Mode', mode,
        '-InputFile', str(source), '-OutputFile', str(output), '-Page', str(page)],
        capture_output=True, timeout=90 if mode == 'export' else 30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('API_KEY','TOKEN','SECRET'))})
    if result.returncode or not output.is_file():
        # COM diagnostics can contain private paths; the compatible viewer is
        # still available and explicitly identifies its different renderer.
        raise ValueError('本机 Word/WPS 未能生成页面。')


def preview(source, folder, digest, page=1):
    """Return (HTML, page count), or None when native rendering is unavailable."""
    if os.name != 'nt': return None
    if type(page) is not int or page < 1: raise ValueError('预览页码超出范围。')
    folder.mkdir(parents=True, exist_ok=True)
    stamp = folder / 'manifest.json'
    pdf = folder / 'document.pdf'
    try: state = json.loads(stamp.read_text('utf-8'))
    except (OSError, ValueError): state = {}
    valid = state.get('key') == VERSION + '\n' + digest
    if valid and not state.get('available') and time.time() - state.get('created', 0) < 300: return None
    try:
        if not valid or not state.get('available') or not pdf.is_file():
            with tempfile.TemporaryDirectory(prefix='word-native-', dir=folder) as temp:
                work = Path(temp)
                snapshot = work / 'document.docx'
                import shutil
                shutil.copyfile(source, snapshot)
                if store.fingerprint(snapshot) != digest: raise ValueError('文件在读取期间发生变化，请重试预览。')
                exported = work / 'document.pdf'
                _run('export', snapshot, exported)
                from pypdf import PdfReader
                reader = PdfReader(exported)
                sizes = [(float(p.mediabox.width), float(p.mediabox.height)) for p in reader.pages]
                if not sizes or any(w <= 0 or h <= 0 for w, h in sizes): raise ValueError('页面尺寸无效。')
                # New PDF and hash become visible together under the caller's
                # per-document render lock. Discard only our old page images.
                os.replace(exported, pdf)
                for image in folder.glob('page-*.png'): image.unlink(missing_ok=True)
                state = {'key':VERSION + '\n' + digest, 'available':True, 'sizes':sizes}
                store.atomic_json(stamp, state)
        total = len(state['sizes'])
        if page > total: raise IndexError('预览页码超出范围。')
        image = folder / f'page-{page}.png'
        if not image.is_file():
            with tempfile.TemporaryDirectory(prefix='word-page-', dir=folder) as temp:
                rendered = Path(temp) / 'page.png'
                _run('page', pdf, rendered, page)
                from PIL import Image
                with Image.open(rendered) as picture: picture.verify()
                os.replace(rendered, image)
        width, height = state['sizes'][page-1]
        data = base64.b64encode(image.read_bytes()).decode('ascii')
        raw = ('<html><head><meta charset="utf-8"><style>'
               '.page{position:relative;background:white;overflow:hidden}'
               '.page img{display:block;width:100%;height:100%}</style></head>'
               '<body data-star-renderer="native-word"><div class="page-wrapper">'
               f'<div class="page" style="width:{width*4/3}px;height:{height*4/3}px">'
               f'<img alt="Word/WPS 实际页面" src="data:image/png;base64,{data}">'
               '</div></div></body></html>')
        return raw, total
    except IndexError as error:
        raise ValueError(str(error)) from error
    except Exception as error:
        if state.get('key')==VERSION+'\n'+digest and state.get('available') and pdf.is_file():
            raise ValueError('实际页面图像未能载入，请重试或切换文字对照。') from error
        store.atomic_json(stamp, {'key':VERSION + '\n' + digest, 'available':False, 'created':time.time()})
        return None
