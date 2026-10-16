"""Machine-readable CLI output must survive Windows/non-UTF-8 pipe encodings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tracker.store import Store


class CliEncodingTests(unittest.TestCase):
    def test_snapshot_and_restore_json_is_utf8_under_legacy_pipe_encodings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'workspace Ω 中文';root.mkdir()
            Store(root/'source.sqlite')
            for encoding in ['ascii','cp1252']:
                with self.subTest(encoding=encoding):
                    archive=root/(encoding+'-Ω.zip')
                    restored=root/(encoding+'-中文.sqlite')
                    env={**os.environ,'PYTHONIOENCODING':encoding}
                    for db,operation,path in [(root/'source.sqlite','snapshot',archive),(restored,'restore',archive)]:
                        proc=subprocess.run([sys.executable,'-m','rilldex','--db',str(db),
                            'workspace',operation,str(path)],env=env,capture_output=True,timeout=30)
                        self.assertEqual(proc.returncode,0,proc.stderr.decode('utf-8',errors='replace'))
                        data=json.loads(proc.stdout.decode('utf-8'))
                        if operation=='restore':self.assertIn('Ω',json.dumps(data,ensure_ascii=False))
                    self.assertTrue(restored.is_file())


if __name__=='__main__':unittest.main()
