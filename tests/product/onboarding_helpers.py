"""Shared synthetic planning world; no provider or retired import implementation."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from my_harness.adapters.git import GitWorkspace
from my_harness.storage.managed import SQLiteManagedRepository
from my_harness.storage.planning import PlanningRepository
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.onboarding_commit import OnboardingRepository
from test_managed_api import VERSIONS, IDENTITY, Ports, make_context

def answer(drafts=None, questions=(), pending=(), text='Fusiones y adelgazamiento propuestos'):
    return {'answer': text, 'questions': list(questions), 'pending': list(pending),
            'drafts': [{'path': path, 'content': content, 'reason': f'Propuesta para {path}'}
                       for path, content in (drafts or {}).items()]}


class World:
    def __init__(self, root, engine):
        self.context = replace(make_context(root), documents='v2')
        self.repo = SQLiteManagedRepository(engine)
        self.writer = GitWorkspace(IDENTITY)
        self.ports = Ports()
        self.worker = LocalSupervisor(self.repo, self.ports, commit_factory=lambda c, v: self.writer)
        self.planning = PlanningRepository(self.repo)
        self.engine, self.keys = engine, 0

    def key(self):
        self.keys += 1
        return f'import-{self.keys}'

    def create(self, **kwargs):
        return self.planning.create(self.context, kind='onboarding', title='Synthetic project', writer=self.writer,
                                    **kwargs)

    def view(self, cid):
        return self.planning.get(cid)

    def message(self, cid, text='Propón las fusiones'):
        return self.planning.submit_message(self.context, cid, self.view(cid)['version'], key=self.key(),
                                            versions=VERSIONS, text=text, writer=self.writer)

    def turn(self, cid, response, text='Propón las fusiones'):
        job = self.message(cid, text)
        self.ports.agents.responses.append(response)
        assert self.worker.run_once().status == 'DONE'
        return job, self.view(cid)['turns'][-1]

    def apply_all(self, cid):
        for proposal in self.view(cid)['proposals']:
            if proposal['status'] == 'PROPOSED':
                self.planning.apply(self.context, cid, proposal['id'], self.view(cid)['version'],
                                    proposal_sha256=proposal['proposal_sha256'], confirmed=True, writer=None)

def tree_state(root: Path) -> dict:
    """Bytes of the checkout and of `.git` (excluding nothing): no T011 operation changes them."""
    return {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file()}


def checkout_state(root):
    # Previews may materialize unreachable Git blobs/trees, as existing document previews do.
    return {path: value for path, value in tree_state(root).items() if not path.startswith('.git/objects/')}


def operation(world):
    return OnboardingRepository(world.repo).get(world.context.root)
