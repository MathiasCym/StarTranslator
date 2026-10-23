"""Lazy, content-bound PowerPoint page images using the model-review renderer."""
import base64
import json
import os
import tempfile
import time
from pathlib import Path
from PIL import Image
from .glossary import store

VERSION='pptx-native-1'


def preview(source,folder,digest,page,total):
    if os.name!='nt':return None
    if type(page) is not int or not 1<=page<=total:raise ValueError('预览页码超出范围。')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    stamp=folder/'manifest.json';key=VERSION+'\n'+digest
    try:state=json.loads(stamp.read_text('utf-8'))
    except (OSError,ValueError):state={}
    valid=state.get('key')==key
    if valid and not state.get('available') and time.time()-state.get('created',0)<300:return None
    image=folder/f'page-{page}.png'
    try:
        if not valid:
            for old in folder.glob('page-*.png'):old.unlink(missing_ok=True)
        if not valid or not image.is_file():
            from .pptx_visual_review import render_pages
            with tempfile.TemporaryDirectory(prefix='ppt-page-',dir=folder) as temp:
                manifest=render_pages(source,Path(temp),native_only=True,page=page)
                if (manifest.get('native') is not True or manifest.get('total')!=total
                        or len(manifest.get('pages',[]))!=1):raise ValueError('实际页面不完整。')
                rendered=manifest['pages'][0]['image']
                with Image.open(rendered) as picture:picture.verify()
                if store.fingerprint(source)!=digest:raise ValueError('文件在读取期间发生变化。')
                os.replace(rendered,image)
                state={'key':key,'available':True,'total':total}
                store.atomic_json(stamp,state)
        with Image.open(image) as picture:width,height=picture.size
        data=base64.b64encode(image.read_bytes()).decode('ascii')
        raw=('<html><head><meta charset="utf-8"><style>.slide{position:relative;overflow:hidden}'
             '.slide img{display:block;width:100%;height:100%}</style></head>'
             '<body data-star-renderer="native-pptx"><div class="slide-container">'
             f'<div class="slide" style="width:{width}px;height:{height}px">'
             f'<img alt="PowerPoint 实际页面" src="data:image/png;base64,{data}">'
             '</div></div></body></html>')
        return raw,total
    except Exception as error:
        # After native success, do not silently swap renderer on a later page.
        if valid and state.get('available'):
            raise ValueError('PowerPoint 实际页面未能载入，请重试或切换文字对照。') from error
        store.atomic_json(stamp,{'key':key,'available':False,'created':time.time()})
        return None
