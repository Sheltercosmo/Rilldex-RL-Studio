"""Condition retention and provenance invariants, not semantic reference labels."""
from copy import deepcopy
import unittest
from tracker.schema import InputError
from tracker.requested_work import apply_edits,CLAUSE_VERSION,VERSION
from tests.test_requested_work import fixture,edit


def clause(unit,cid,kind,text):
    return {'id':cid,'kind':kind,'text':text,'evidence':[unit['source']]}


class ConditionClauseTests(unittest.TestCase):
    def test_unchanged_restriction_retains_its_original_identity_and_source(self):
        run,x=fixture();a,b,c=x['units']
        intro=edit(a,'introduce','payment','Payment terms.');intro['kind']='condition'
        intro['clauses']=[clause(a,'method','requirement','Use card A.'),clause(a,'guard','requirement','Do not charge until an ID is supplied.')]
        first,_=apply_edits(run,a,[],[intro],CLAUSE_VERSION)
        revise=edit(b,'revise','payment','Updated payment terms.')
        revise['clauses']=[clause(b,'method','requirement','Use card B.'),deepcopy(first[0]['clauses'][1])]
        second,_=apply_edits(run,b,first,[revise],CLAUSE_VERSION)
        self.assertEqual(first[0]['clauses'][1],second[0]['clauses'][1])
        self.assertNotEqual(first[0]['clauses'][0]['version_id'],second[0]['clauses'][0]['version_id'])
        self.assertEqual(second[0]['clauses'][1]['source_unit_id'],a['id'])
        bad=deepcopy(revise);bad['clauses']=bad['clauses'][:1]
        with self.assertRaisesRegex(InputError,'silently dropped'):apply_edits(run,b,first,[bad],CLAUSE_VERSION)
        bad['retired_clauses']=[{'id':'guard','reason':'Current source withdraws this restriction.','evidence':[b['source']]}]
        after,changes=apply_edits(run,b,first,[bad],CLAUSE_VERSION)
        self.assertEqual(len(after[0]['clauses']),1)
        self.assertEqual(changes[0]['retired_clauses'][0]['previous'],first[0]['clauses'][1])

    def test_checks_claims_and_terms_keep_distinct_content_roles(self):
        run,x=fixture();a,b,c=x['units']
        value=edit(a,'introduce','payment','Payment condition.');value['kind']='condition'
        value['clauses']=[clause(a,'claimed_balance','attributed_claim','The user says the balance is $15.'),
                          clause(a,'balance_check','requested_check','Verify the card balance.')]
        state,_=apply_edits(run,a,[],[value],CLAUSE_VERSION)
        revised=edit(b,'revise','payment','Different terms.');revised['clauses']=deepcopy(state[0]['clauses'])
        revised['clauses'][0]['kind']='requirement'
        with self.assertRaisesRegex(InputError,'content role'):apply_edits(run,b,state,[revised],CLAUSE_VERSION)
        revised['clauses'][0]['kind']='attributed_claim';revised['clauses'][0]['text']='A new claim.'
        with self.assertRaisesRegex(InputError,'current contribution'):apply_edits(run,b,state,[revised],CLAUSE_VERSION)
        revised['clauses'][0]['evidence']=[c['source']]
        with self.assertRaisesRegex(InputError,'Future evidence'):apply_edits(run,b,state,[revised],CLAUSE_VERSION)
        with self.assertRaisesRegex(InputError,'version 2'):apply_edits(run,a,[],[value],VERSION)

    def test_record_enrichment_can_add_a_clause_without_rewording_the_summary(self):
        run,x=fixture();a,b,c=x['units']
        value=edit(a,'introduce','payment','Payment terms.');value['kind']='condition'
        value['clauses']=[clause(a,'method','requirement','Use the supplied card.')]
        state,_=apply_edits(run,a,[],[value],CLAUSE_VERSION)
        revised=edit(b,'revise','payment','Payment terms.');revised['clauses']=deepcopy(state[0]['clauses'])
        revised['clauses'].append(clause(b,'guard','requirement','Do not charge before the card ID is supplied.'))
        after,_=apply_edits(run,b,state,[revised],CLAUSE_VERSION)
        self.assertEqual(len(after[0]['clauses']),2)
        revised['evidence']=[c['source']]
        with self.assertRaisesRegex(InputError,'Identical terms'):apply_edits(run,c,after,[revised],CLAUSE_VERSION)


if __name__=='__main__':unittest.main()
