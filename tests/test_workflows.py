"""Exercise shared build, bundle-validation, and artifact-download contracts offline."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


def step(workflow, name):
    data = yaml.safe_load((ROOT / '.github/workflows' / workflow).read_text())
    return next(s for job in data['jobs'].values() for s in job['steps'] if s.get('name') == name)['run']


class WorkflowTests(unittest.TestCase):
    def run_step(self, script, folder, **env):
        return subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=folder,
                              env={**os.environ, **env}, text=True, capture_output=True)

    def test_bundle_validation(self):
        script = step('tauri-package.yml', 'Verify requested bundle outputs')
        for target in ('', 'x86_64-unknown-linux-gnu', 'aarch64-apple-darwin'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'src-tauri/target' / target / 'release/bundle'
                for directory, filename in [('deb', 'app.deb'), ('appimage', 'app.AppImage'),
                                            ('nsis', 'app.exe'), ('dmg', 'app.dmg'), ('macos', 'app.app')]:
                    (root / directory).mkdir(parents=True)
                    (root / directory / filename).touch()
                env = dict(BUILD_TARGET=target, BUILD_BUNDLES='deb,appimage,nsis,app,dmg')
                result = self.run_step(script, tmp, **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                (root / 'deb/app.deb').unlink()
                self.assertNotEqual(self.run_step(script, tmp, **env).returncode, 0)
                env['BUILD_BUNDLES'] = 'unknown'
                self.assertNotEqual(self.run_step(script, tmp, **env).returncode, 0)

    def test_build_credentials_are_scoped_and_json_safe(self):
        script = step('tauri-package.yml', 'Build installers')
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'probe.mjs').write_text('''import fs from 'node:fs';
fs.writeFileSync('result.json', JSON.stringify({secret: process.env.TEST_CREDENTIAL,
  leaked: 'BUILD_ENVIRONMENT' in process.env}));
''')
            secret = 'quotes " and newline\nwith $shell `syntax`'
            result = self.run_step(script, tmp, BUILD_COMMAND='node probe.mjs',
                                   BUILD_ENVIRONMENT=json.dumps({'TEST_CREDENTIAL': secret}))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(Path(tmp, 'result.json').read_text()),
                             {'secret': secret, 'leaked': False})
            self.assertNotIn(secret, result.stdout + result.stderr)
            for invalid in ('[]', 'null', '{"KEY": 42}'):
                result = self.run_step(script, tmp, BUILD_COMMAND='touch should-not-exist', BUILD_ENVIRONMENT=invalid)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(Path(tmp, 'should-not-exist').exists())
            result = self.run_step(script, tmp, BUILD_COMMAND='exit 7', BUILD_ENVIRONMENT='{}')
            self.assertEqual(result.returncode, 7)

    def test_nonsecret_environment_rejects_line_injection(self):
        script = step('tauri-package.yml', 'Configure app build environment')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp, 'github-env')
            result = self.run_step(script, tmp, GITHUB_ENV=str(output),
                                   APP_ENVIRONMENT='{"APP_CHANNEL":"preview"}')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), 'APP_CHANNEL=preview\n')
            for values in ({'APP_CHANNEL': 'preview\nINJECTED=value'}, {'INVALID=KEY': 'value'}, []):
                output.unlink(missing_ok=True)
                result = self.run_step(script, tmp, GITHUB_ENV=str(output), APP_ENVIRONMENT=json.dumps(values))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())

    def test_artifact_download_contract_and_failures(self):
        script = step('apt-publish.yml', 'Download tested packages')
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp, 'gh')
            fake.write_text('''#!/usr/bin/env python3
import json, os, sys
with open('calls.jsonl', 'a') as output: output.write(json.dumps(sys.argv[1:]) + '\\n')
sys.exit(int(os.environ.get('FAKE_FAILURE', '0')))
''')
            fake.chmod(0o755)
            env = dict(PATH=f'{tmp}:{os.environ["PATH"]}', SOURCE_RUN_ID='123',
                       GITHUB_REPOSITORY='1100soft/example',
                       ARTIFACT_INPUTS=json.dumps({'standard': 'apt-input/standard', 'lean': 'apt-input/lean'}))
            result = self.run_step(script, tmp, **env)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in Path(tmp, 'calls.jsonl').read_text().splitlines()]
            self.assertEqual(calls, [['run', 'download', '123', '--repo', '1100soft/example', '--name', name,
                                     '--dir', f'apt-input/{name}'] for name in ('standard', 'lean')])
            self.assertNotEqual(self.run_step(script, tmp, **env, FAKE_FAILURE='1').returncode, 0)
            env['ARTIFACT_INPUTS'] = '{}'
            self.assertNotEqual(self.run_step(script, tmp, **env).returncode, 0)


if __name__ == '__main__':
    unittest.main()
