"""Private, transactional paragraph checkpoints, independent of exported files."""
import copy
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from .glossary.store import data_dir


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


@lru_cache(maxsize=2)
def policy(stage):
    names = ['writing_policy.py', 'document_context.py', 'pptx_content.py', 'llm/client.py', 'text_integrity.py']
    if stage in ('translation-zh', 'review-zh'):names+=['reverse_translation.py','text_translation.py','replacer/styled_text.py','extract/office.py','replacer/pptx_package.py']
    elif stage=='pdf-image':names+=['pdf_image_text.py','pdf_image_ocr.py','image_ocr.ps1','translation_policy.py']
    elif stage=='pdf-output':names+=['pdf_quality.py','word_native_preview.py','word_render.ps1','pdf_image_ocr.py','image_ocr.ps1']
    else:
        names += (['translation.py', 'translation_policy.py', 'translation_batch.py', 'translation_residual.py', 'replacer/styled_text.py', 'extract/office.py', 'replacer/pptx_package.py']
                  if stage == 'translation' else ['matcher/__init__.py', 'matcher/judge.py', 'matcher/batch.py'])
    # Checkout line endings must not change the meaning of a resumable policy.
    return digest([hashlib.sha256((Path(__file__).parent/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in names])


def context_identity(glossary, references, client, reference_path=None):
    def normal(path): return os.path.normcase(os.path.abspath(path))
    current=normal(reference_path) if reference_path else None
    return {'glossary': digest([entry.to_dict() for entry in glossary.entries]),
        'references': sorted((os.path.normcase(os.path.abspath(path)),
            [(seg.locator, seg.text) for seg in segments]) for path, segments in getattr(references, 'by_path', {}).items()),
        'model': {key: getattr(client, key, '') for key in ('provider', 'base_url', 'model', 'api_format')},
        'pairing': sorted(('@current' if current==normal(key) else normal(key),normal(value))
                          for key,value in getattr(references, 'pairs', {}).items())}


class Checkpoint:
    def __init__(self, stage, identity):
        self.stage, self.scope = stage, digest({'policy': policy(stage), 'input': identity})
        self.path = data_dir()/'task-checkpoints.sqlite3'
        self.lock, self.values, self.resumed = threading.Lock(), {}, 0
        self.available, self.warning = True, ''
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connection() as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE IF NOT EXISTS checkpoints (scope TEXT NOT NULL, stage TEXT NOT NULL, item_key TEXT NOT NULL, value TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(scope,stage,item_key))')
                db.execute('CREATE TABLE IF NOT EXISTS checkpoint_scopes (scope TEXT PRIMARY KEY, origin TEXT NOT NULL)')
                db.execute('INSERT OR REPLACE INTO checkpoint_scopes VALUES (?,?)',(self.scope,str(identity.get('source',''))))
                rows = db.execute('SELECT item_key,value FROM checkpoints WHERE scope=? AND stage=?', (self.scope,stage)).fetchall()
                # Explicit compatibility with the shipped 2.0.11–2.0.14 translators.
                # Source/model/glossary/references/styles remain in the identity;
                # every resumed paragraph still passes today's content checks.
                if stage=='translation':
                    for old_policy in ('697989bcd6621c21d2512fde97c2aa4d63f81808dd31d97f136ade66a48032e6',
                            '9151ff216813ae95cbbd4f78bd4194828243ec6017623064543ee9cd05bd6649',
                            'e70d058be4e421fe6cc5ed3f7fee27bdd31e342576ce3d47145039279f088bf5',
                            '2dbc35c2e107202d597ff58e7d2bf3baff4ac9e807e2afd4dcc7e40a98e1a664',
                            '20631795cfac42022cdebcb50c6f52e8d44cdf72d7dfbc51129d27399cd58c47',
                            'cce7e89f4fc5d122f2f32566e846b3f5d6868984403ab0aee2a8b8808d0ae6bf',
                            'e3803df46fe2e75c773fb753ac815277ea9bdf6d9fcba0df316833dc855671ad',
                            '0b812f78dc872c18d916ec6b046062e9c7dfa7bd8372a133ba4343244fc86cc0',
                            'd52442f83508e6b572652942e65ca8199efeed7f0cd2e8555df75a01c21b15fa',
                            'bd9a72b7c87a1fe9bd68460883b8f1fdf2e3a4618d99dcc2d30b5954eb98e464',
                            'b207ba2040b108b8d22cb6ff5e7106a820e17bc9b104f6bf5e91b95c79aefeb8',
                            # Validated predecessor before PDF header aliasing;
                            # content/model/number/style checks remain identical.
                            '8c232f7b6275f93e127c8d5da966f9a634270b1ed9927889b2959b820cd78356',
                            # Adding a separate PDF-image pass does not invalidate
                            # already validated paragraph text or inline styles.
                            '28c24624fc3b708a49c2b69665d0a0e3fd1931b77b29744d02297f4f937de396',
                            # Saved-output verification is separate from the
                            # already validated text/style translation policy.
                            'a43b018a8f62e194c9cd5279a784e44b788b4bcb0d793648477d38faacb6efec',
                            # 2.2.2: reused text still passes current label,
                            # cross-line, number and style validation on read.
                            '40bbb9e111085fb038e7cba66d45d29ab37ea0f62aeeb1b060172163039f2692',
                            # 2.2.5 Chinese-English processing is unchanged;
                            # the new reverse direction has its own stage.
                            'e7980d7cba760b3393e13b13de28ede40dfc5df643009c791415af9b2c98a927'):
                        legacy=digest({'policy':old_policy,'input':identity})
                        if legacy==self.scope:continue
                        known={key for key,_ in rows}
                        rows.extend((key,value) for key,value in db.execute('SELECT item_key,value FROM checkpoints WHERE scope=? AND stage=?',(legacy,stage)).fetchall() if key not in known)
            for key, value in rows:
                try: self.values[key] = json.loads(value)
                except (ValueError, TypeError): pass
        except (OSError, sqlite3.Error): self.disable()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db: yield db
        finally: db.close()

    def disable(self):
        self.available = False
        self.warning = '本机断点未能写入；本次处理继续，但未保存的部分需重新处理。'
        logging.getLogger(__name__).warning('Local checkpoint storage unavailable')

    def get(self, key):
        with self.lock: return copy.deepcopy(self.values.get(digest(key)))

    def used(self):
        with self.lock: self.resumed += 1

    def put(self, key, value):
        if not self.available: return
        key, raw = digest(key), json.dumps(value, ensure_ascii=False)
        with self.lock:
            try:
                with self.connection() as db:
                    db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?,?)',
                        (self.scope, self.stage, key, raw, time.time()))
                self.values[key] = copy.deepcopy(value)
            except (OSError, sqlite3.Error): self.disable()


def open_checkpoint(stage, identity, glossary, references, client, *, reference_path=None):
    from .llm.client import LLMClient
    # Test/extension clients without a connection identity must opt in; do not
    # reuse an arbitrary provider's results under a different client.
    if not isinstance(client, LLMClient): return None
    return Checkpoint(stage, {**context_identity(glossary,references,client,reference_path), **identity})


def translation_key(segment, piece, groups):
    return [segment.locator, piece, [{'id':g['id'],'text':g['text'],'key':g.get('key')} for g in groups]]


def forget_under(folder):
    """Remove checkpoint text only when its owned shared upload folder is removed."""
    path=data_dir()/'task-checkpoints.sqlite3'
    if not path.is_file():return
    root=Path(folder).resolve();db=sqlite3.connect(path,timeout=10)
    try:
        with db:
            for scope,origin in db.execute('SELECT scope,origin FROM checkpoint_scopes').fetchall():
                owner=Path(origin)
                if owner.is_absolute() and owner.resolve().is_relative_to(root):
                    db.execute('DELETE FROM checkpoints WHERE scope=?',(scope,))
                    db.execute('DELETE FROM checkpoint_scopes WHERE scope=?',(scope,))
    finally:db.close()
