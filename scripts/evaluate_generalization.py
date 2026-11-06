"""Repeat live reading checks with one process-local credential."""
import argparse
import getpass
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_environment_reading import evaluate as definitions
from scripts.evaluate_reading_context import evaluate as context
from scripts.evaluate_harness_generalization import evaluate as formats
from scripts.evaluate_purpose_boundary import evaluate as purpose
from tracker.schema import dumps

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--prompt-key',action='store_true');p.add_argument('--output',default='outputs');a=p.parse_args()
    root=Path(a.output)
    if a.live and a.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(formats(root/'harness-generalization-final',a.live)),flush=True)
    print(dumps(definitions(root/'environment-reading-generalized',live=a.live)),flush=True)
    print(dumps(context(root/'reading-context-generalized',live=a.live,arms=('current',))),flush=True)
    if a.live:purpose(root/'purpose-boundary')
