"""Real local checkpoint bytes plus declared cloud-object metadata for browser QA."""
import json
import sys
from pathlib import Path
from rilldex import Run

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True);db=root/'workspace.sqlite'
if db.exists():raise RuntimeError('Choose a fresh fixture directory')
checkpoint=root/'step-80';checkpoint.mkdir()
(checkpoint/'config.json').write_text('{"architecture":"control"}')
for index in range(2):
    with (checkpoint/f'model-{index+1:05d}-of-00002.safetensors').open('wb') as stream:
        for _ in range(4):stream.write(bytes([index+1])*1024*1024)
with Run('artifact-study',project='product',workspace=db,producer='learner-0',hardware=False,capture_console=False) as run:
    session=run.session
    snapshot=root/'notes.txt';snapshot.write_text('Embedded snapshot remains available.');run.add_file(snapshot);snapshot.unlink()
    run.add_reference(checkpoint,role='checkpoint',step=80)
    run.add_reference('s3://training-artifacts/policy/checkpoint-80.safetensors',name='cloud-policy.safetensors',role='model',version='v80',size=40*1024**3)
    run.log({'loss':.3},step=80)
(root/'fixture.json').write_text(json.dumps({'experiment':run.experiment,'session':session}),encoding='utf-8')
