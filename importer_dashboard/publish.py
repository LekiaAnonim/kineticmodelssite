"""
The history that a draft's pull request shows.

drafts.checkpoint commits a running job's identifications within a minute of each change, and the
libraries each time the importer waits for input, so one run makes many small commits ("identify
1 species", "update the RMG libraries", ...). They keep the work safe in the draft on the server.
The pull request gets the same files with fewer commits: each run of checkpoint commits becomes
one commit, and the commits people make on the web (the file editor, uploads, a new model) stay as
they are, with their own message.

The draft branch on the server is not changed. The history is made with `git commit-tree` from
the trees of the draft's own commits, so it changes exactly the same files. It takes every name
and date from those commits, so the same draft gives the same commits each time, and a push after
new checkpoints changes only the last commit.
"""
import re
from collections import namedtuple

from . import drafts

Commit = namedtuple('Commit', 'sha parents tree author_name author_email author_date '
                              'committer_name committer_email committer_date message')

# Checkpoints made before CHECKPOINT_TRAILER existed have only this body
_OLD_CHECKPOINT_BODY = re.compile(r'^(Import job \d+ on Prometheus\.|Prometheus Importer\.)$', re.M)
_JOB = re.compile(r'Import job (\d+) on Prometheus\.')
_FIELDS = ['%H', '%P', '%T', '%an', '%ae', '%ad', '%cn', '%ce', '%cd', '%B']


def is_checkpoint(commit):
    return (drafts.CHECKPOINT_TRAILER in commit.message
            or _OLD_CHECKPOINT_BODY.search(commit.message) is not None)


def _commits(draft, head):
    """The draft's commits from its base to `head`, oldest first."""
    out = drafts.git(
        ['log', '--reverse', '--date=raw', '--format=' + '%x00'.join(_FIELDS) + '%x1e',
         f'{draft.base_sha}..{head}'],
        draft.path,
    ).stdout
    commits = []
    for record in out.split('\x1e'):
        record = record.lstrip('\n')
        if not record:
            continue
        values = record.split('\x00')
        values[1] = values[1].split()
        commits.append(Commit(*values))
    return commits


def _runs(commits):
    """The commits in groups: each run of checkpoint commits together, every other commit alone."""
    runs, i = [], 0
    while i < len(commits):
        j = i + 1
        if is_checkpoint(commits[i]):
            while j < len(commits) and is_checkpoint(commits[j]):
                j += 1
        runs.append(commits[i:j])
        i = j
    return runs


def pull_request_commits(draft, head):
    """How many commits the pull request gets for the draft at `head` (without making them)."""
    commits = _commits(draft, head)
    if any(len(c.parents) != 1 for c in commits):
        return len(commits)
    return len(_runs(commits))


def _numstat(draft, old, new, relpath):
    out = drafts.git(['diff', '--numstat', old, new, '--', relpath], draft.path).stdout.split()
    if len(out) >= 2 and out[0].isdigit():
        return int(out[0]), int(out[1])
    return 0, 0


def _squash_message(draft, run):
    """One message for a run of checkpoint commits: what the run changed, the jobs, the people."""
    folder = draft.model_folder
    old, new = run[0].parents[0], run[-1].sha
    added, removed = _numstat(draft, old, new, f'{folder}/SMILES.txt')
    blocked, _ = _numstat(draft, old, new, f'{folder}/SMILES-BLOCKED.txt')
    libraries = drafts.git(['diff', '--quiet', old, new, '--',
                            *(f'{folder}/{name}' for name in drafts.LIBRARY_FOLDERS)],
                           draft.path, check=False).returncode != 0
    subject = drafts.checkpoint_subject(folder, added, removed, blocked, libraries)
    jobs = sorted({int(n) for c in run for n in _JOB.findall(c.message)})
    if len(jobs) == 1:
        body = f'Import job {jobs[0]} on Prometheus.'
    elif jobs:
        body = f'Import jobs {", ".join(map(str, jobs))} on Prometheus.'
    else:
        body = 'Prometheus Importer.'
    body += f' {len(run)} checkpoints of the draft, in one commit.'
    first = (run[0].author_name, run[0].author_email)
    others = []
    for c in run:
        person = (c.author_name, c.author_email)
        if person != first and person not in others:
            others.append(person)
    trailers = '\n'.join(f'Co-authored-by: {name} <{email}>' for name, email in others)
    return f'{subject}\n\n{body}\n' + (f'\n{trailers}\n' if trailers else '')


def _commit_tree(draft, tree, parent, message, author, committer):
    name, email, date = author
    c_name, c_email, c_date = committer
    return drafts.git(
        ['commit-tree', tree, '-p', parent],
        draft.path,
        input=message,
        env={'GIT_AUTHOR_NAME': name, 'GIT_AUTHOR_EMAIL': email, 'GIT_AUTHOR_DATE': date,
             'GIT_COMMITTER_NAME': c_name, 'GIT_COMMITTER_EMAIL': c_email,
             'GIT_COMMITTER_DATE': c_date},
    ).stdout.strip()


def squashed(draft, head):
    """
    The commit to push for the draft at `head`: its history with each run of checkpoint commits
    in one commit. `head` itself if there is nothing to squash, or if the draft has a merge.
    """
    commits = _commits(draft, head)
    if any(len(c.parents) != 1 for c in commits):
        return head
    runs = _runs(commits)
    if all(len(run) == 1 for run in runs):
        return head  # already one commit per change

    parent = draft.base_sha
    for run in runs:
        last = run[-1]
        if len(run) == 1:
            message = last.message
        else:
            message = _squash_message(draft, run)
        parent = _commit_tree(
            draft, last.tree, parent, message,
            (run[0].author_name, run[0].author_email, run[0].author_date),
            (last.committer_name, last.committer_email, last.committer_date),
        )
    return parent
