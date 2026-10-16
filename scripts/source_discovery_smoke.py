"""Installed-package onboarding check; authored source data, no models/server."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import tracker
from tracker.portable import generation_document
from tracker.store import Store


def main():
    print('Package:',tracker.__file__)
    with tempfile.TemporaryDirectory(prefix='jev-discovery-') as tmp:
        base=Path(tmp);root=base/'outputs';root.mkdir();db=base/'workspace.sqlite'
        def cli(*args):
            r=subprocess.run([sys.executable,'-m','rilldex','--db',str(db),*map(str,args)],cwd=base,capture_output=True,text=True)
            assert r.returncode==0,(r.stdout,r.stderr)
            return json.loads(r.stdout)
        def write(i):
            (root/f'rollout-{i}.json').write_text(json.dumps(generation_document('Authored question',f'Answer {i}')),encoding='utf-8')
        (root/'config.json').write_text('{"learning_rate":0.01}')
        write(1);write(2)
        r=cli('discover',root);assert not db.exists()
        route=r['routes'][0];assert route['pattern']=='rollout-*.json'
        setup=cli('setup','--root',root,'--mode',route['mode'],'--pattern',route['pattern'])
        assert setup['connection']['pattern']==route['pattern']
        args=('watch',root,'--producer','authored/outputs','--experiment','authored','--mode',route['mode'],'--pattern',route['pattern'],'--once')
        assert cli(*args)['ingested']==2
        write(3);assert cli(*args)['ingested']==1
        assert cli(*args)['ingested']==0
        assert len(Store(db).list())==3
        print('PASS: discover without database; filtered replay; new filename; restart; no duplicate receipts')
        print('PASS: detected filename rule survives generated setup and actual CLI collection')


if __name__=='__main__':main()
