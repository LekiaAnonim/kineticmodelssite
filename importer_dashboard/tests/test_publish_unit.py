"""
A draft's pull request gets its checkpoint commits squashed: each run of the Importer's
checkpoints becomes one commit, and the commits people make on the web keep their message.
PCI2019/657-Zhang (Nov 2026) had a dozen "identify 1 species" / "update the RMG libraries"
commits around one edit, "Corrected SMILES of HCOH from [C-]=[OH+] to [CH-]=[OH+]".
"""
import os

from django.contrib.auth.models import User

from importer_dashboard import drafts, editor, publish
from importer_dashboard.tests.test_drafts_unit import DraftTestCase, out, run


class SquashTests(DraftTestCase):
    def confirm(self, draft, line, user=None, library=None):
        with open(self.worktree_file(draft, 'SMILES.txt'), 'a') as f:
            f.write(line + '\n')
        if library:
            os.makedirs(self.worktree_file(draft, 'RMG-Py-thermo-library'), exist_ok=True)
            with open(self.worktree_file(draft, 'RMG-Py-thermo-library/ThermoLibrary.py'), 'w') as f:
                f.write(library)
        return drafts.checkpoint(draft, include_libraries=bool(library), user=user or self.user, job=self.job)

    def history(self, draft, sha):
        return out('log', '--reverse', '--format=%s%x09%an', f'{draft.base_sha}..{sha}', cwd=draft.path).splitlines()

    def edit(self, draft, text, message):
        return editor.save(draft, {'SMILES.txt': text.encode()}, message, self.user)

    def test_checkpoints_in_a_row_become_one_commit_and_edits_keep_their_message(self):
        draft, _ = self.open()
        self.confirm(draft, 'CH4\tC\t! Confirmed by lekia')
        self.confirm(draft, 'H2O\tO\t! Confirmed by lekia', library='entry(label="H2O")\n')
        smiles = open(self.worktree_file(draft, 'SMILES.txt')).read()
        self.edit(draft, smiles.replace('[Ar]', '[Ar] ! checked'), 'Corrected the comment of AR')
        self.confirm(draft, 'CO\t[C-]#[O+]\t! Confirmed by lekia')
        self.confirm(draft, 'CO2\tO=C=O\t! Confirmed by lekia', library='entry(label="CO2")\n')
        head = out('rev-parse', 'HEAD', cwd=draft.path)

        squashed = publish.squashed(draft, head)
        self.assertEqual(self.history(draft, squashed), [
            f'{self.model}: identify 2 species, update the RMG libraries\tLekia Prosper',
            f'{self.model}: Corrected the comment of AR\tLekia Prosper',
            f'{self.model}: identify 2 species, update the RMG libraries\tLekia Prosper',
        ])
        self.assertEqual(len(self.history(draft, head)), 5)  # the draft keeps its checkpoints
        # Same files, and the same commits every time
        self.assertEqual(out('rev-parse', f'{squashed}^{{tree}}', cwd=draft.path),
                         out('rev-parse', f'{head}^{{tree}}', cwd=draft.path))
        self.assertEqual(publish.squashed(draft, head), squashed)
        body = out('log', '-1', '--format=%b', f'{squashed}~2', cwd=draft.path)
        self.assertIn(f'Import job {self.job.pk} on Prometheus. 2 checkpoints of the draft, in one commit.', body)
        self.assertEqual(publish.pull_request_commits(draft, head), 3)
        self.assertEqual(drafts.changes(draft)['pull_request_commits'], 3)

        # A new checkpoint changes only the last commit
        self.confirm(draft, 'H2\t[H][H]\t! Confirmed by lekia')
        again = publish.squashed(draft, out('rev-parse', 'HEAD', cwd=draft.path))
        self.assertEqual(out('rev-parse', f'{again}~1', cwd=draft.path), out('rev-parse', f'{squashed}~1', cwd=draft.path))
        self.assertEqual(self.history(draft, again)[-1],
                         f'{self.model}: identify 3 species, update the RMG libraries\tLekia Prosper')

    def test_everyone_who_confirmed_in_a_run_is_credited(self):
        draft, _ = self.open()
        other = User.objects.create_user('richard', email='r.west@example.org', first_name='Richard', last_name='West')
        self.confirm(draft, 'CH4\tC\t! Confirmed by lekia')
        self.confirm(draft, 'H2O\tO\t! Confirmed by richard', user=other)
        squashed = publish.squashed(draft, out('rev-parse', 'HEAD', cwd=draft.path))
        message = out('log', '-1', '--format=%an%n%B', squashed, cwd=draft.path)
        self.assertTrue(message.startswith('Lekia Prosper\n'))
        self.assertIn('Co-authored-by: Richard West <r.west@example.org>', message)

    def test_a_draft_with_nothing_to_squash_is_pushed_as_it_is(self):
        draft, _ = self.open()
        self.confirm(draft, 'CH4\tC\t! Confirmed by lekia')
        head = out('rev-parse', 'HEAD', cwd=draft.path)
        self.assertEqual(publish.squashed(draft, head), head)

    def test_checkpoints_from_before_the_trailer_are_squashed_too(self):
        draft, _ = self.open()
        for label, smiles in (('CH4', 'C'), ('H2O', 'O')):
            with open(self.worktree_file(draft, 'SMILES.txt'), 'a') as f:
                f.write(f'{label}\t{smiles}\n')
            run('commit', '-qam', f'{self.model}: identify 1 species', '-m', f'Import job {self.job.pk} on Prometheus.',
                cwd=draft.path)
        squashed = publish.squashed(draft, out('rev-parse', 'HEAD', cwd=draft.path))
        self.assertEqual([line.split('\t')[0] for line in self.history(draft, squashed)],
                         [f'{self.model}: identify 2 species'])
