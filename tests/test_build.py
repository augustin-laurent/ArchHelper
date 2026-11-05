import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare', ROOT / 'scripts/prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class BuildTest(unittest.TestCase):
    def test_readonly_sources_and_only_writable_output_mount(self):
        config = prepare.config(Path('/tmp/a repo'))
        self.assertIn('mountPoint: /input\n    writable: false', config)
        self.assertIn('mountPoint: /output\n    writable: true', config)
        self.assertIn('vmType: qemu', config)
        self.assertIn('x86_64: host', config)
        self.assertNotIn('/dev/sd', config)
        self.assertNotIn('/dev/nvme', config)
        self.assertIn('ignore: true', config)
        self.assertNotIn('~/', config)

    def test_source_paths_cannot_escape_work(self):
        for name in ('/etc', '../work/foo', 'work/../../etc', 'dist/other'):
            with self.assertRaises(ValueError):
                prepare.source_path(ROOT, name)

    def test_download_checksum_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source, dest = tmp / 'source', tmp / 'download'
            source.write_bytes(b'checked input')
            prepare.download(source.as_uri(), dest, hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(source.read_bytes(), dest.read_bytes())
            with self.assertRaises(RuntimeError):
                prepare.download(source.as_uri(), dest, '0' * 64)
            self.assertEqual(dest.read_bytes(), b'checked input')
            self.assertFalse((tmp / 'download.part').exists())

    def test_fetch_exact_tag_and_reject_dirty_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = tmp / 'upstream'
            subprocess.run(['git', 'init', str(upstream)], check=True, stdout=subprocess.DEVNULL)
            (upstream / 'file').write_text('pinned\n')
            subprocess.run(['git', '-C', str(upstream), 'add', 'file'], check=True)
            subprocess.run(['git', '-C', str(upstream), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture'], check=True, stdout=subprocess.DEVNULL)
            commit = prepare.run('git', '-C', str(upstream), 'rev-parse', 'HEAD')
            subprocess.run(['git', '-C', str(upstream), 'tag', 'v-test'], check=True)
            source = {'path': 'work/upstream', 'url': str(upstream), 'commit': commit, 'tag': 'v-test'}
            prepare.fetch(tmp, [source])
            self.assertEqual((tmp / 'work/upstream/file').read_text(), 'pinned\n')
            (tmp / 'work/upstream/file').write_text('local changes\n')
            with self.assertRaisesRegex(RuntimeError, 'modifiée'):
                prepare.fetch(tmp, [source])

    def test_native_root_invocation_is_refused_before_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'uname').write_text('#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo x86_64 ;; esac\n')
            (tmp / 'id').write_text('#!/bin/sh\necho 0\n')
            for path in tmp.iterdir():
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(tmp) + os.pathsep + os.environ['PATH'])
            result = subprocess.run(['bash', str(ROOT / 'v8'), 'clean'], env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('sans sudo', result.stderr)



if __name__ == '__main__':
    unittest.main()
