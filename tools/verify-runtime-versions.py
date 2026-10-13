"""Verify build pins against the primary package index, without uploading data."""
import json
from pathlib import Path
from urllib.request import urlopen
root=Path(__file__).resolve().parents[1]
pins=[]
for entry in sorted((root/'python-runtime/Lib/site-packages').glob('*.dist-info')):
    name,version=entry.name[:-10].rsplit('-',1)
    name=name.replace('_','-')
    for attempt in range(3):
        try:
            with urlopen('https://pypi.org/pypi/'+name+'/'+version+'/json',timeout=15) as response:
                result=json.load(response)
            pins.append({'name':name,'version':version,'available':bool(result.get('urls'))});break
        except Exception as e:
            if attempt==2:pins.append({'name':name,'version':version,'available':False,'error':type(e).__name__})
destination=root/'dist/qa/release-200';destination.mkdir(parents=True,exist_ok=True)
(destination/'runtime-pins.json').write_text(json.dumps(pins,indent=2),encoding='utf-8')
print(json.dumps(pins))
if all(pin['available'] for pin in pins):
    (root/'requirements-runtime.txt').write_text('\n'.join(pin['name']+'=='+pin['version'] for pin in pins)+'\n',encoding='utf-8')
