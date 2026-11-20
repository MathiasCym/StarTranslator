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

# Read from the verified original 2.4.1 payload, not inferred from display tags.
# Import only exact task/session scopes; callers revalidate cached content.
SHIPPED_241={
    'translation':'e95240e9ceb3c072913ade55a2f7f19e8daba649296e18738a75b6c225cb058a',
    'translation-zh':'9d7cf2e1050fa2b8d45a852868424ab4d601ce1333d3c76091e9611f2cd7bc37',
    'translation-multi':'44c6417fb5318db51929cec1b6b5f9454768d1e4f12aba6e4ee134ef2559e0cc',
    'review':'65feb1e2211971c9332165ddda4a68c80b0f6f34c6cc08f2ab645cbfcdf3d498',
    'review-zh':'9d7cf2e1050fa2b8d45a852868424ab4d601ce1333d3c76091e9611f2cd7bc37',
    'review-multi':'44c6417fb5318db51929cec1b6b5f9454768d1e4f12aba6e4ee134ef2559e0cc',
    'terminology-review':'5bb35abbb65b25e9d458ba224e55da3a2aaeb44bfcf7d9be8405292ed0cd9b4a'}

# The shipped 2.4.4 multilingual checkpoints use the same source and model
# identity. Their translations and review findings still pass current checks.
SHIPPED_244={
    'translation-multi':'7650501b3f8117e26e58755a5b79bb44c00611adb6c53b95d3e7ea0b7ea02414',
    'review-multi':'95f61e367809b4f4bbc60992410b4056cd003c14170511f091cfaa88e7e522cc',
}

# Parallel scheduling and current validation change the policy hash. An
# explicit resume can still reuse matching, revalidated 2.4.5 entries.
SHIPPED_245={
    'translation':'c736560032582e4432c87971700b45299c0effcabf4cfdd45e747ebbb5e313c0',
    'translation-multi':'59e0fdaeb28146db4985395d9c40861da4333c08d4b9f2c3dfb4443019e050f3',
    'review-multi':'fe8a22b04b85dfb8246f46031e61a2968d06760b44a0654e8d07bd48d9829a82',
    'terminology-review':'df9360afa630b4d984f50bd2ae66cf06590e197f0ccfaf9dd6906ffc12767eb6',
    'translation-zh':'eae62802e551cfea10a5d125a8473e4c464ed60a2c97e505d129f592ab6fead1',
    'review-zh':'8b79396343535f800788d74e568554df217173c6c274336d4ca4df21515a0c30',
    'review':'b4ad2cf34299d1ac0c74417861316f9f4761294f1e399d0a214cae849dbc1fc2',
    'pdf-image':'6217c80281e8a2793800857f077dbfde5dd024f19db87467ab21515a7e49366e',
    'pdf-output':'a408f9261b803493f3aa413067da50228917770736e9d6059453b6a143b58898',
}

SHIPPED_246={
    'translation':'bda630ca7fbac8c756d1b286993ba3740202981d91422e284c3fcd7f35de449a',
    'translation-multi':'89c2dea1faf192572b2bbb9671562d7a6fcfde07af698924306d2e5ab68318c6',
    'review-multi':'cd1b89b27cd7f31d182658ca852f55b909fb2217f03067fd0fb58d89f04e4278',
    'terminology-review':'d9373e71645c802a2fa0f30785015ac06835f209dcabcd54468dcc7c736fe516',
    'translation-zh':'2a937bf9b819b02f2baf21babfc8a29c6cba783a7aa272c3a28b422a0ef1a720',
    'review-zh':'6a5cc2da3d659e2a304f526682b48e6bf3f905e0f0c8c29ff01b38c802751a24',
    'review':'ed09f9c09f428e8fd1054c8529a08fb2b4cc9b94b5a121dff94222410fd125cf',
    'pdf-image':'84bf568d3667e9675241bd013de9b25b09b2fa4053a21bf244fc079629311f2e',
    'pdf-output':'bcf1d14db65a8b243639a294eb842a92cfb9aae8c38dc1ec2abccd8aa9fc76ae',
}

# Revalidate compatible checkpoints only when the user explicitly resumes.
SHIPPED_247={
    'translation':'051ea49e3dee7f7c68029d21c597c10d81479126f345a2cacf06d96d11875e4e',
    'translation-multi':'db38e6582872283b10eeeeebb7d00849885376260d1af4da8f84a96156392279',
    'review-multi':'5edbd8eb1edd6182254072ea72c7b91800298076cd638cc45076a4ba04d29d79',
    'terminology-review':'f464f2c221748263b62e1a7c4c3c2f6d7d30cd7da013086da4d465c5a56c61a5',
    'translation-zh':'2d5726a13309348fd42457b1c5f835341d70bec8abf9445ea547b1e3be1e40ad',
    'review-zh':'34c6fbe4385eba022f5faa5acaec25b4cddc74480fe7c053fcb0cc03090406d2',
    'review':'ce84f8dfa4c417b624ece9e6c14cb5286ce41f227d64d65ef5a09565ecb27245',
    'pdf-image':'73275dac6b3cf776d1913865e2894a8fe7b196828343be56157b774fc84887e0',
    'pdf-output':'c46f32050e28d714fd810054f0759971c1faaeff913efd3f3c35ba33c4dcab33',
}

SHIPPED_248={
    'translation':'0abd73b4a3bd00f9e72286e0fac0bbf3cedda26163e7fc5b376fbcaa75cbb686',
    'translation-multi':'275176170c4da98a38de02147e973cf8b388275d7ad795ef9b658fa3e27f29d4',
    'review-multi':'750ff78b1aa66bbd78bc881d75d8cdbbc7510147bc6ad3fa45ee095d8852568b',
    'terminology-review':'ff018a48d0da1b1fd2d39523abd9b2dfc118cd3ddd99f256415c292e88bc6c4f',
    'translation-zh':'fe1db9643ee3c6a34ee3623ca57e9f6adb1afeca13a42fddae0189ee30598d19',
    'review-zh':'6fa6260e2a0bc042edc71fefd755d7a6ab456c7ea41737716c0c1671b5e8b0ce',
    'review':'f96c6026d9fe288e1a887e10e51d6d6d4bf41eb0c38cfc969b596264f5154311',
    'pdf-image':'e303f237de20bc8de396fdcee4e449c370fb276a7baa38699f644142813d5d93',
    'pdf-output':'a3ff06d9033c358800e7552f2847c38789de8459f83535217a7b3e227677b36c',
}

SHIPPED_249={
    'translation':'21a4e881765916947f07bb85382faedebf51aed914b2b6e538e83f507b92c3bc',
    'translation-multi':'efcc10f80024767ca0275547710ba9c3a50025367f01420de997fafde169ef2d',
    'review-multi':'8ae27a1646957ce1215649762de0970c8fc506a8e38141f5e56f2126240b8714',
    'terminology-review':'2a1eb37ad5af5419bf1ef142ecadef33b9a07e3bd20a036f5b9529476f8ab0b4',
    'translation-zh':'dd85de35202be5e88f461773c8c640ad4c91bca7633039532f64acca6042c0de',
    'review-zh':'ef7b0f94ab9c9b532c3a3aa15e426f08129398cc2efbea530c6f5d988f16c0bf',
    'review':'3c9e60ea9a25bd2e7a9f84d81cf72a8b5ee8601066dfcc2f8a1c5939006726a0',
    'pdf-image':'9daf6313517e5001efb04d8ceb7a1325b5294cf3e9bd9ab91091b98c6de9c99f',
    'pdf-output':'d32550ae9fa3ac21d74284a9ebd2463be6e0d87d16542a846adf8d7acb9a9faa',
}

# Verified local preview before quantity review changed. Exact-session resume
# still requires the current language and style checks for each cached entry.
PREVIEW_BEFORE_QUANTITY_REVIEW={
    'translation':'5d905a9a3c261bcedb8925463ec153ec355ee42807803d75389d4c926131ea26',
    'translation-multi':'39686e6860225e7dfe76f1b384d1bdc0c2ccc58ce2d911cfe1fe4e520fb866b1',
    'review-multi':'7199211cbdbd444fe60e4c2ff6f471820f0d4d2074bf54f43a5469a9262c6663',
    'translation-zh':'a17cd642e130b13e43fefd2f7369872562ce642b302524fc8e5bd97d06e79449',
    'review-zh':'f07d2ade2fb0ffd634363db3f2e9c8063683b6050e00b12088b7c0542457effc',
    'terminology-review':'11e4559c934c8bcbcb2fcc78a76df8a3e9642f8d8faaeda1e86c668e70ddcb49',
    'review':'7a03854c16e719cc9a5adb41e8ce23330aca8f77fb1e255c2f07ec7b029e7093',
    'pdf-image':'5a71ad9b4fc731824d2c68561efe552c25b992bac228b340b2bc4b2512ee1759',
    'pdf-output':'d1849260f9f4786579ee8b0d79361ee9a7cfece8e476e2ef0f548ca237e0902e',
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


@lru_cache(maxsize=2)
def policy(stage):
    names = ['writing_policy.py', 'document_context.py', 'pptx_content.py', 'llm/client.py', 'text_integrity.py',
             'document_translation_core.py','document_parallel.py','llm/transport_recovery.py','review_format.py']
    if stage.startswith('review') or stage=='terminology-review':names+=['glossary/language_pairs.py','glossary/catalog.py']
    if stage in ('translation-multi','review-multi'):
        names+=['multilingual_documents.py','multilingual_quality.py','text_languages.py','formats.py','replacer/styled_text.py','extract/office.py','replacer/pptx_package.py','document_translation_policy.py']
    elif stage=='terminology-review':names+=['terminology_review.py','text_languages.py']
    elif stage in ('translation-zh', 'review-zh'):names+=['reverse_translation.py','reverse_entities.py','reverse_validation.py','text_translation.py','formats.py','pdf_reflow.py','pdf_links.py','replacer/styled_text.py','extract/office.py','replacer/pptx_package.py']
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
    def __init__(self, stage, identity, *, read_only=False):
        from .task_resume import checkpoint_identity
        identity,self.observer=checkpoint_identity(identity)
        self.read_only=read_only
        self.stage, self.scope = stage, digest({'policy': policy(stage), 'input': identity})
        self.path = data_dir()/'task-checkpoints.sqlite3'
        self.lock, self.values, self.resumed = threading.Lock(), {}, 0
        self.available, self.warning = True, ''
        if read_only and not self.path.is_file():return
        try:
            if not read_only:self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connection() as db:
                if not read_only:
                    db.execute('PRAGMA journal_mode=WAL')
                    db.execute('CREATE TABLE IF NOT EXISTS checkpoints (scope TEXT NOT NULL, stage TEXT NOT NULL, item_key TEXT NOT NULL, value TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(scope,stage,item_key))')
                    db.execute('CREATE TABLE IF NOT EXISTS checkpoint_scopes (scope TEXT PRIMARY KEY, origin TEXT NOT NULL)')
                    db.execute('INSERT OR REPLACE INTO checkpoint_scopes VALUES (?,?)',(self.scope,str(identity.get('source',''))))
                rows = db.execute('SELECT item_key,value FROM checkpoints WHERE scope=? AND stage=?', (self.scope,stage)).fetchall()
                if identity.get('task_session') is not None:
                    for shipped in (PREVIEW_BEFORE_QUANTITY_REVIEW, SHIPPED_249, SHIPPED_248, SHIPPED_247, SHIPPED_246, SHIPPED_245, SHIPPED_244, SHIPPED_241):
                        if stage not in shipped:
                            continue
                        legacy=digest({'policy':shipped[stage],'input':identity})
                        known={key for key,_ in rows}
                        rows.extend((key,value) for key,value in db.execute(
                            'SELECT item_key,value FROM checkpoints WHERE scope=? AND stage=?',
                            (legacy,stage)).fetchall() if key not in known)
                # Explicit compatibility with the shipped 2.0.11–2.0.14 translators.
                # Source/model/glossary/references/styles remain in the identity;
                # every resumed paragraph still passes today's content checks.
                if stage=='translation':
                    for old_policy in ('697989bcd6621c21d2512fde97c2aa4d63f81808dd31d97f136ade66a48032e6',
                            # 2.4.0: ignoring spelling-only metadata changes no
                            # text/style semantics; reused runs are revalidated.
                            'aa3f0817166b782f33c3272bf8635f25a8de69652c9fdb057e4845aab3d02856',
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
                if stage in ('translation-zh','review-zh'):
                    # Shipped reverse results still require current
                    # content/style validation at each use. Keep their exact
                    # source/model/glossary identity, never import blindly.
                    for old_policy in (
                            'f7c57c1a8461abcd28faaa7d1910a7e5435fc46e1640dfeacac8b0cc9e3be13a',
                            '3e8008c39f1869cd051787ea1b42679b6987d9fd1d5bbcbc9c93de70a4865fa6',
                            # 2.3.6/2.3.7: resume bookkeeping changes do not
                            # invalidate content. Reads still run validation;
                            # legacy reviews require the entire original scope.
                            'f55c372c1060a27d2271890788534e12f99480c914897f8fdfdeeb4cf3881326'):
                        legacy=digest({'policy':old_policy,'input':identity})
                        known={key for key,_ in rows}
                        rows.extend((key,value) for key,value in db.execute(
                            'SELECT item_key,value FROM checkpoints WHERE scope=? AND stage=?',
                            (legacy,stage)).fetchall() if key not in known)
                if stage in ('translation-multi','review-multi'):
                    # The shipped2.4.0 policy accidentally hashed matcher
                    # sources. Import only its exact scope, then require today's
                    # facts/styles and source/target-bound language evidence.
                    legacy=digest({'policy':'e42eaf9212dcb7d92d3f6e219e4db5798da2517565462cd9daadaf33e46590f9','input':identity})
                    known={key for key,_ in rows}
                    rows.extend((key,value) for key,value in db.execute(
                        'SELECT item_key,value FROM checkpoints WHERE scope=? AND stage=?',
                        (legacy,stage)).fetchall() if key not in known)
                if stage=='review':
                    legacy=digest({'policy':'e42eaf9212dcb7d92d3f6e219e4db5798da2517565462cd9daadaf33e46590f9','input':identity})
                    known={key for key,_ in rows}
                    rows.extend((key,value) for key,value in db.execute(
                        'SELECT item_key,value FROM checkpoints WHERE scope=? AND stage=?',
                        (legacy,stage)).fetchall() if key not in known)
            for key, value in rows:
                try: self.values[key] = json.loads(value)
                except (ValueError, TypeError): pass
        except (OSError, sqlite3.Error): self.disable()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10) if self.read_only else sqlite3.connect(self.path, timeout=10)
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
        if self.observer:self.observer(self.stage)

    def put(self, key, value):
        if not self.available or self.read_only: return
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
