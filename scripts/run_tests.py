"""Run portable tests; archived development datasets are not a package dependency."""
import argparse
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
# These modules replay separately retained research artifacts. Keep their code
# available for maintainers, without shipping private/local observation archives.
ARCHIVE_MODULES={
    'test_action_comparison',
    'test_activity_instruction_probe',
    'test_actor_intent',
    'test_actor_intent_study',
    'test_adjustment_graph',
    'test_adjustment_references',
    'test_ami_reference_audit',
    'test_apb_reference_audit',
    'test_attempt_revision',
    'test_base_units',
    'test_behavior_moves',
    'test_condition_dispatch',
    'test_condition_grounding',
    'test_condition_observer',
    'test_content_repair_trial',
    'test_contribution_scope_graph',
    'test_contribution_scope_pairs',
    'test_decision_followthrough',
    'test_declared_work_tree',
    'test_dialogbank_reconciliation',
    'test_dialogbank_reference',
    'test_expression_challenge',
    'test_local_adjustments',
    'test_local_frames',
    'test_local_role_context',
    'test_luna_proposal_audit',
    'test_method_comparison',
    'test_native_path_selection',
    'test_native_relation_study',
    'test_outline_bindings',
    'test_outline_scope_match',
    'test_parallel_work_returns',
    'test_path_selection_audit',
    'test_plan_attempt_paths',
    'test_plan_corpus',
    'test_plan_locality',
    'test_plan_transfer_sample',
    'test_planning_structure',
    'test_planning_structure_study',
    'test_prefix_encoding_study',
    'test_process_error_pilot',
    'test_readable_context',
    'test_reasoningflow_audit',
    'test_relation_contracts',
    'test_relation_review',
    'test_request_changes',
    'test_retrieval_final_output',
    'test_retrieval_job_completion',
    'test_retrieval_partition_replay',
    'test_retry_outcomes',
    'test_revision_metrics',
    'test_rl_framework_settings',
    'test_scope_membership',
    'test_scoped_content_envelope',
    'test_scoped_content_selection',
    'test_scoped_content_trial',
    'test_scoped_reading_outcomes',
    'test_scoped_reading_trial',
    'test_scoped_selector_trial',
    'test_semantic_catalog',
    'test_semantic_map',
    'test_training_exposure',
    'test_unit_content',
    'test_work_consistency_metrics',
    'test_work_content_bindings',
    'test_work_context',
    'test_work_lineage',
    'test_work_outline',
    'test_work_purpose',
    'test_work_scope_audit',
    'test_work_scope_graph',
    'test_work_structure_metrics',
    'test_work_target_refinement_trial',

}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--with-archives',action='store_true');parser.add_argument('--javascript',action='store_true');args=parser.parse_args()
    if args.javascript:
        files=[str(p.relative_to(ROOT)) for p in sorted((ROOT/'tests').glob('*.test.cjs')) if args.with_archives or p.name!='nested_work_tree.test.cjs']
        return subprocess.call(['node','--test',*files],cwd=ROOT)
    sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]
    loader=unittest.TestLoader();suite=unittest.TestSuite()
    for path in sorted((ROOT/'tests').glob('test_*.py')):
        if not args.with_archives and path.stem in ARCHIVE_MODULES:continue
        loaded=loader.loadTestsFromName(path.stem)
        if not args.with_archives and path.stem=='test_work_retries':
            # Only the public-PDF replay depends on a retained observation archive.
            for case_class in loaded:
                suite.addTests(t for t in case_class if t._testMethodName!='test_real_pdf_step_and_cutoff_preserve_unknown_recovery')
        else:suite.addTests(loaded)
    if not args.with_archives:print(f'Portable suite: {len(ARCHIVE_MODULES)} archive-dependent modules excluded. Use --with-archives with the retained research datasets.',flush=True)
    return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
