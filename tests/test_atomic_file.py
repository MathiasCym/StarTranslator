import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.atomic_file import replace_checked

def locked():
    error=PermissionError('locked');error.winerror=32;return error

class AtomicFileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.target=self.root/'source.docx';self.new=self.root/'temporary.docx';self.target.write_bytes(b'original');self.new.write_bytes(b'new')
    def tearDown(self):self.temp.cleanup()
    def guard(self):
        if self.target.read_bytes()!=b'original':raise ValueError('Original changed')
    def test_transient_lock_retries_without_backups_or_partial_document(self):
        real=os.replace;calls=[]
        def attempt(a,b):
            calls.append(1)
            if len(calls)<3:raise locked()
            real(a,b)
        with patch('backend.atomic_file.os.replace',side_effect=attempt),patch('backend.atomic_file.time.sleep'):
            replace_checked(self.new,self.target,self.guard)
        self.assertEqual(self.target.read_bytes(),b'new');self.assertEqual(list(self.root.iterdir()),[self.target])
    def test_original_edited_during_wait_is_preserved(self):
        with patch('backend.atomic_file.os.replace',side_effect=locked()),patch('backend.atomic_file.time.sleep',side_effect=lambda _:self.target.write_bytes(b'edited externally')):
            with self.assertRaises(ValueError):replace_checked(self.new,self.target,self.guard)
        self.assertEqual(self.target.read_bytes(),b'edited externally')
    def test_persistent_lock_has_clear_error_and_keeps_original(self):
        with patch('backend.atomic_file.os.replace',side_effect=locked()),patch('backend.atomic_file.time.sleep'):
            with self.assertRaisesRegex(PermissionError,'尚未覆盖'):replace_checked(self.new,self.target,self.guard)
        self.assertEqual(self.target.read_bytes(),b'original')
