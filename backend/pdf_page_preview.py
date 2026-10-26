"""Read-only, lazy page images of the original PDF, independent of translation."""
import base64
import json
import os
import tempfile
from pathlib import Path
from .glossary import store

VERSION = 'pdf-page-1'


def _render(source, target, page):
    # The existing page-mode helper uses Windows.Data.Pdf only: the Word COM
    # export branch is never entered for an original PDF.
    if os.name != 'nt':
        raise ValueError('当前环境无法读取原 PDF 页面，可切换文字对照。')
    from .word_native_preview import _run
    try:
        _run('page', source, target, page)
    except Exception as error:
        raise ValueError('原 PDF 页面未能载入，请重试；文字对照仍可查看。') from error


def preview(source, folder, digest, page):
    from pypdf import PdfReader
    from PIL import Image
    if type(page) is not int or page < 1:
        raise ValueError('预览页码超出范围。')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = folder / 'manifest.json'
    key = VERSION + '\n' + digest
    try:
        state = json.loads(stamp.read_text('utf-8'))
    except (OSError, ValueError):
        state = {}
    image = folder / f'page-{page}.png'
    valid = state.get('key') == key
    total = state.get('total', 0) if valid else 0
    if total and page > total:
        raise ValueError('预览页码超出范围。')
    if not valid or not image.is_file():
        try:
            with Path(source).open('rb') as stream:
                document = PdfReader(stream)
                if document.is_encrypted and not document.decrypt(''):
                    raise ValueError('原 PDF 已加密，请先使用可读取的 PDF 生成对照。')
                total = len(document.pages)
                if not 1 <= page <= total:
                    raise ValueError('预览页码超出范围。')
            with tempfile.TemporaryDirectory(prefix='pdf-page-',dir=folder) as temp:
                rendered = Path(temp)/'page.png'
                _render(source, rendered, page)
                with Image.open(rendered) as picture:
                    width, height = picture.size
                    picture.verify()
                png = rendered.read_bytes()
        except ValueError:
            raise
        except Exception as error:
            raise ValueError('原 PDF 页面未能载入，请重试；文字对照仍可查看。') from error
        if store.fingerprint(source) != digest:
            raise ValueError('文件在读取期间发生变化，请重试预览。')
        # Write a complete image before publishing its content-bound cache key.
        fd, temp = tempfile.mkstemp(dir=folder, suffix='.png.tmp')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(png)
            if not valid:
                for old in folder.glob('page-*.png'):
                    old.unlink(missing_ok=True)
            os.replace(temp, image)
            store.atomic_json(stamp, {'key': key, 'total': total})
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    else:
        try:
            with Image.open(image) as picture:
                width, height = picture.size
                picture.verify()
        except Exception as error:
            image.unlink(missing_ok=True)
            raise ValueError('原 PDF 页面缓存无法读取，请重试预览。') from error
        png = image.read_bytes()
    data = base64.b64encode(png).decode('ascii')
    raw = ('<html><head><meta charset="utf-8"><style>'
           '.page{position:relative;overflow:hidden;background:white}'
           '.page img{display:block;width:100%;height:100%}</style></head>'
           '<body data-star-renderer="original-pdf"><div class="page-wrapper">'
           f'<div class="page" style="width:{width}px;height:{height}px">'
           f'<img alt="原 PDF 第 {page} 页" src="data:image/png;base64,{data}">'
           '</div></div></body></html>')
    return raw, total
