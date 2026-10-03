"""Build the actual Android plugin and final release as one ordered operation.

Required: Java 17, JSON_JAR (or java/json.jar), D8_JAR, project Python.
No npm publish or GitHub mutation is performed by this command.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_plugin import verify_plugin


def run(command, cwd=ROOT):
    subprocess.run([str(x) for x in command], cwd=cwd, check=True,
                   env={**os.environ, 'PYTHON': sys.executable})


def main():
    json_jar = Path(os.environ.get('JSON_JAR', ROOT / 'java/json.jar')).resolve()
    d8_jar = Path(os.environ.get('D8_JAR', '')).resolve()
    if not json_jar.is_file() or not d8_jar.is_file():
        raise SystemExit('JSON_JAR and D8_JAR must point to existing, trusted build dependencies')
    java_home = os.environ.get('JAVA_HOME')
    def tool(name):
        return str(Path(java_home) / 'bin' / name) if java_home else name
    java = ROOT / 'java'
    classes, dex = java / 'classes', java / 'dex'
    for p in (classes, dex):
        if p.exists(): shutil.rmtree(p)
        p.mkdir()
    # Compile THIS catalogue/version before D8, then regenerate the final hashes.
    run([sys.executable, ROOT / 'scripts/assemble.py'])
    sources = sorted((java / 'src').rglob('*.java'))
    sources += sorted((java / 'stubs').rglob('*.java'))
    sources += sorted((java / 'test').glob('*.java'))
    run([tool('javac'), '-encoding', 'UTF-8', '-source', '8', '-target', '8',
         '-cp', json_jar, '-d', classes, *sources])
    classpath = str(classes) + os.pathsep + str(json_jar)
    run([tool('java'), '-cp', classpath, 'HomeTest'], cwd=java)
    # Host stubs and tests are only compiler inputs; never include them in DEX.
    run([tool('jar'), 'cf', java / 'home-classes.jar', '-C', classes,
         'com/github/catvod/spider'])
    run([tool('java'), '-cp', d8_jar, 'com.android.tools.r8.D8', '--min-api', '24',
         '--no-desugaring', '--output', dex, java / 'home-classes.jar'])
    with ZipFile(ROOT / 'home.jpg', 'w', compression=ZIP_DEFLATED) as archive:
        entry = ZipInfo('classes.dex', date_time=(1980, 1, 1, 0, 0, 0))
        entry.compress_type = ZIP_DEFLATED
        entry.external_attr = 0o100644 << 16
        archive.writestr(entry, (dex / 'classes.dex').read_bytes())
    run([sys.executable, ROOT / 'scripts/assemble.py'])
    binary = verify_plugin(ROOT)
    run(['node', ROOT / 'scripts/validate.cjs'])
    run([sys.executable, ROOT / 'scripts/test_layout.py'])
    run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'])
    run([tool('java'), '-cp', classpath, 'HomeIntegration'])
    report = {'version': json.loads((ROOT / 'package.json').read_text())['version'],
              'plugin': binary, 'java_tests': 'passed', 'android_device_test': False,
              'mainland_network_test': False,
              'dependencies_sha256': {str(p.name): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in (json_jar, d8_jar)}}
    (ROOT / 'build-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print('ANDROID_PLUGIN_AND_RELEASE_BUILD_PASSED')


if __name__ == '__main__':
    main()
