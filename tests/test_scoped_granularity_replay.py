"""Retained model outputs: these checks replay development evidence, not new accuracy tests."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker import work_content_stages as stages, work_content_bindings as scopes
from tracker.schema import InputError


def required_matches(contents, required):
    """Maximum one-to-one anchor matching; a merged content cannot satisfy two items."""
    owners = {}
    def assign(index, seen):
        anchor, mode = required[index]
        for cid, content in enumerate(contents):
            if cid in seen or content['mode'] != mode or anchor not in content['expression']['text']:
                continue
            seen.add(cid)
            if cid not in owners or assign(owners[cid], seen):
                owners[cid] = index
                return True
        return False
    return sum(assign(i,set()) for i in range(len(required)))


class ScopedGranularityReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((Path(__file__).parent/'fixtures/scoped_content_granularity.json').read_text(encoding='utf-8'))

    def bind_contents(self, row, arm):
        packet=row['packet'];record=row['arms'][arm]
        options=dict(content_policy=stages.SEPARATE_WORK if arm=='granularity' else 'legacy',
                     syntax=row['syntax'] if arm=='syntax' else None)
        self.assertEqual(record['request'],stages.scoped_content_request(packet,packet['units'][0]['unit_id'],**options))
        return stages.bind_scoped_contents(packet,record['request'],record['response'],
            'luna-subagent/separate-work/1' if arm=='granularity' else 'luna-subagent/'+arm,**options)

    def test_required_contents_preserve_failed_baseline_and_non_splitting_controls(self):
        counts={arm:dict(cases=0,bound=0,matched=0,required=0) for arm in ['plain','syntax','granularity']}
        for row in self.data['cases']:
            for arm in row['arms']:
                with self.subTest(case=row['case'],arm=arm):
                    total=counts[arm];total['cases']+=1;total['required']+=len(row['reference']['required'])
                    if arm=='plain' and row['case']=='asserted-state-new-fix':
                        with self.assertRaises(InputError):self.bind_contents(row,arm)
                        continue
                    bound=self.bind_contents(row,arm);total['bound']+=1
                    total['matched']+=required_matches(bound['contents'],row['reference']['required'])
                    if 'expected_count' in row['reference']:
                        self.assertEqual(len(bound['contents']),row['reference']['expected_count'])
        self.assertEqual(counts,dict(
            plain=dict(cases=16,bound=15,matched=27,required=39),
            syntax=dict(cases=6,bound=6,matched=11,required=16),
            granularity=dict(cases=16,bound=16,matched=39,required=39)))
        merged=[dict(mode='proposed',expression=dict(text='open and inspect'))]
        self.assertEqual(required_matches(merged,[('open','proposed'),('inspect','proposed')]),1)

    def test_feature_only_contract_removes_duplicated_scope_generation(self):
        feature_count=0
        for row in self.data['cases']:
            if 'features' not in row:continue
            with self.subTest(case=row['case']):
                contents=self.bind_contents(row,'granularity');packet=row['packet']
                old=row['features']['features'];new=row['features']['unscoped-features']
                self.assertEqual(old['request'],stages.scoped_feature_request(packet,contents))
                with self.assertRaises(InputError):
                    stages.bind_scoped_features(packet,contents,old['request'],old['response'],contents['producer'])
                self.assertEqual(new['request'],stages.scoped_feature_request(packet,contents,scope_proposals=False))
                bound=stages.bind_scoped_features(packet,contents,new['request'],new['response'],contents['producer'],scope_proposals=False)
                self.assertEqual(bound['contents'],contents['contents'])
                feature_count+=len(bound['features'])
                for feature in bound['features']:
                    self.assertEqual(feature['scopes'],[[c['id']] for c in contents['contents']])
                    req=scopes.membership_scope_request(packet,bound,feature['id'])
                    self.assertEqual(len(req['questions']),len(contents['contents']))
                if row['case'] in {'fresh-1','fresh-2'}:
                    self.assertFalse(any(f['type']=='question' for f in bound['features']))
                modified=deepcopy(new['response']);modified['features'][0]['scopes']=[['c1']]
                with self.assertRaises(InputError):
                    stages.bind_scoped_features(packet,contents,new['request'],modified,contents['producer'],scope_proposals=False)
        self.assertEqual(feature_count,29)

    def test_scope_probe_improvement_and_invalid_feature_failures_remain_visible(self):
        cases={row['case']:row for row in self.data['cases']};matches={'plain':0,'syntax':0}
        for probe in self.data['scope_probes']:
            row=cases[probe['case']];packet=row['packet'];bound=probe['bound']
            options=dict(argument_rule='direct_owner',syntax=row['syntax'] if probe['arm']=='syntax' else None)
            self.assertEqual(probe['request'],scopes.membership_scope_request(packet,bound,'probe',**options))
            result=scopes.membership_scope_result(packet,bound,'probe',probe['response'],**options)
            matches[probe['arm']]+=result['content_ids']==probe['expected']
            view=scopes.project_membership_scope(packet,bound,result,syntax=options['syntax'])
            self.assertEqual(view['unit']['source'],packet['units'][0]['source'])
        self.assertEqual(matches,dict(plain=3,syntax=4))
        self.assertEqual(self.data['jev_usage'],dict(input_tokens=35590,output_tokens=1476))
        self.assertIsNone(self.data['candidate_token_usage'])


if __name__=='__main__':unittest.main()
