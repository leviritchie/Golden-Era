import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import batch_operator as op


class BatchOperatorTests(unittest.TestCase):
    def test_sparse_resource_budget_forbids_nested_workers_and_loops(self):
        budget = op.validate_resource_budget(None, 1)
        self.assertFalse(budget["allowNestedDelegation"])
        self.assertEqual(budget["maxIndependentReviews"], 1)
        with self.assertRaisesRegex(ValueError, "Nested delegation"):
            op.validate_resource_budget({"allowNestedDelegation": True}, 1)
        with self.assertRaisesRegex(ValueError, "at most two"):
            op.validate_resource_budget({"maxRepairAttemptsPerUnit": 3}, 1)

    def review(self):
        panel = (op.ROOT / 'artifacts/test-panel.png').as_posix()
        return dict(candidateFingerprint='fit', artifacts={'mesh': 'hash'}, decision='pass',
                    gates={g: {'pass': True, 'evidence': 'Inspected retained evidence'} for g in op.GATES},
                    inspectedPanels=[{'path': panel, 'sha256': 'panel'}], reviewedFrames=[0],
                    fullReelReviewed=True, reviewer='independent-agent', repairWorker='worker')

    def validate(self, review):
        panels = {(op.ROOT / 'artifacts/test-panel.png').as_posix(): 'panel'}
        return op.validate_review(review, 'fit', {'mesh': 'hash'}, panels, [0])

    def test_complete_review_structure(self):
        self.assertEqual(self.validate(self.review()), [])

    def test_candidate_or_image_change_rejected(self):
        for field, value in [('candidateFingerprint', 'stale'), ('artifacts', {'mesh': 'other'}),
                             ('inspectedPanels', [{'path': 'other.png', 'sha256': 'panel'}])]:
            with self.subTest(field=field):
                review = self.review()
                review[field] = value
                with self.assertRaises(ValueError):
                    self.validate(review)

    def test_passing_requires_reel_all_frames_and_all_gates(self):
        mutations = [dict(fullReelReviewed=False), dict(reviewedFrames=[])]
        for changes in mutations:
            with self.assertRaises(ValueError):
                self.validate({**self.review(), **changes})
        review = self.review()
        review['gates']['surface']['pass'] = False
        with self.assertRaises(ValueError):
            self.validate(review)

    def test_independent_final_review_required(self):
        review = self.review()
        review['reviewer'] = review['repairWorker']
        with self.assertRaises(ValueError):
            self.validate(review)
        review = self.review()
        del review['repairWorker']
        with self.assertRaises(ValueError):
            self.validate(review)

    def test_negative_can_avoid_expensive_full_reel(self):
        review = self.review()
        review.update(decision='reject', fullReelReviewed=False, reviewedFrames=[],
                      nextAction='Separate fused grip from hand')
        review['gates']['ownership']['pass'] = False
        self.assertEqual(self.validate(review), ['ownership'])

    def test_output_cannot_escape_workspace(self):
        workspace = op.ROOT / 'artifacts/test-workspace'
        with self.assertRaises(ValueError):
            op.owned_path(workspace / '../outside', workspace)

    def test_context_unknown_duplicate_excluded(self):
        for units in (['unknown'], ['h3_grand_elf'] * 2, ['h3_archer']):
            with self.assertRaises(ValueError):
                op.context(units, ledger={'rows': []})

    def test_packet_must_pin_selected_candidate(self):
        candidate = op.ROOT / 'artifacts/test-candidate'
        job = {'unit': 'u', 'out': str(candidate)}
        report = dict(unit='u', status='experimental_candidate', inputs=job, frames=1,
                      preview=False, previewScale=3, fingerprint='fit')
        packet = dict(unit='u', fitFingerprint='fit', frameCount=1, inputs=[], panels=[])
        attempt = dict(candidate=candidate, packetDir=candidate / 'review', job=job)
        with patch.object(op, 'verify_fit'), patch.object(op, 'read', side_effect=[report, packet]):
            with self.assertRaisesRegex(ValueError, 'does not pin'):
                op.verify_packet(attempt, 'u')

    def test_full_qa_cannot_use_probe_report(self):
        candidate = op.ROOT / 'artifacts/test-candidate'
        job = {'unit': 'u', 'out': str(candidate)}
        report = dict(unit='u', status='experimental_candidate', inputs=job,
                      preview=False, previewScale=3)
        with patch.object(op, 'verify_fit'), patch.object(op, 'read', return_value=report):
            with self.assertRaisesRegex(ValueError, 'full saved-motion'):
                op.verify_packet(dict(candidate=candidate, job=job), 'u', require_full=True)

    def test_duplicate_candidate_output_refused(self):
        workspace = op.ROOT / 'artifacts/test-workspace'
        job = {'unit': 'u', 'out': str(workspace / 'candidate')}
        attempt = dict(fitManifest='fixture.json', packetDir=str(workspace / 'packet'),
                       review=str(workspace / 'review.json'), hypothesis='rigid prop')
        manifest = dict(workspace=str(workspace), units=[dict(unit='u', maxAttempts=2,
                        attempts=[attempt, copy.deepcopy(attempt)])])
        with patch.object(op, 'read', side_effect=[manifest, {'jobs': [job]}, {'jobs': [job]}]):
            with self.assertRaisesRegex(ValueError, 'disjoint'):
                op.load_batch(Path('fixture.json'))

    def test_reuse_candidate_cannot_overlap_logs(self):
        workspace = op.ROOT / 'artifacts/test-workspace'
        job = {'unit': 'u', 'out': str(workspace / 'logs')}
        attempt = dict(fitManifest='fixture.json', packetDir=str(workspace / 'packet'),
                       review=str(workspace / 'review.json'), hypothesis='rigid prop', reuseExisting=True)
        manifest = dict(workspace=str(workspace), units=[dict(unit='u', maxAttempts=1, attempts=[attempt])])
        with patch.object(op, 'read', side_effect=[manifest, {'jobs': [job]}]):
            with self.assertRaisesRegex(ValueError, 'driver-owned'):
                op.load_batch(Path('fixture.json'))

    def test_existing_unowned_candidate_cannot_be_refitted(self):
        candidate = op.ROOT / 'artifacts/test-candidate'
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'iterdir', return_value=iter([candidate / 'fitted_bind.glb'])), \
             patch.object(Path, 'is_file', return_value=False):
            with self.assertRaisesRegex(ValueError, 'not this resumable attempt'):
                op.claim_candidate(dict(candidate=candidate, job={'unit': 'u', 'out': str(candidate)}))

    def test_stage_failure_can_be_unfinished_exception_without_fake_qa(self):
        workspace = op.ROOT / 'artifacts/test-workspace'
        job = {'unit': 'u', 'out': str(workspace / 'candidate')}
        attempt = dict(candidate=workspace / 'candidate', review=workspace / 'qa.json', job=job,
                       packetDir=workspace / 'packet')
        closure = {stage: dict(state='not_indicated', reason='Recorded route decision',
                               evidence=[dict(path='evidence.json', sha256='h')]) for stage in op.SEQUENCE}
        closure['registration']['state'] = 'blocked'
        manifest = dict(units=[dict(unit='u', attempts=[attempt], sequenceClosure=closure,
                                   exceptionNextAction='Provide the missing capture reference')])
        state = [dict(unit='u', attempt=0, state='stage_exception', job=op.normalized_job(job),
                      attemptIdentity=op.attempt_identity(attempt),
                      reason='Missing capture')]
        with patch.object(Path, 'is_file', return_value=False), patch.object(op, 'read', return_value=state), \
             patch.object(op, 'identity', return_value=dict(path='evidence.json', sha256='h')), \
             patch.object(Path, 'write_text') as write:
            result = op.finalize(manifest, workspace)
        self.assertTrue(result['workRemaining'])
        self.assertEqual(result['exceptions'], 1)
        self.assertIn('stageFailure', write.call_args.args[0])

    def test_changed_attempt_cannot_inherit_stage_failure(self):
        workspace = op.ROOT / 'artifacts/test-workspace'
        attempt = dict(job={}, packetDir=workspace / 'packet', review=workspace / 'qa.json')
        original = op.attempt_identity(attempt)
        for mutation in ({'renderMode': 'full'}, {'reuseExisting': True},
                         {'packetDir': workspace / 'other'}):
            changed = {**attempt, **mutation}
            state = [dict(unit='u', attempt=0, state='stage_exception', attemptIdentity=original)]
            with patch.object(Path, 'is_file', return_value=False), \
                 patch.object(op, 'read', return_value=state):
                with self.assertRaisesRegex(ValueError, 'needs visual QA'):
                    op.finalize(dict(units=[dict(unit='u', attempts=[changed])]), workspace)

    def test_pending_qa_is_not_a_stage_failure(self):
        workspace = op.ROOT / 'artifacts/test-workspace'
        attempt = dict(candidate=workspace / 'candidate', review=workspace / 'qa.json', job={})
        with patch.object(Path, 'is_file', return_value=False), patch.object(op, 'read', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'needs visual QA'):
                op.finalize(dict(units=[dict(unit='u', attempts=[attempt])]), workspace)


if __name__ == '__main__':
    unittest.main()
