"""Explicit offline fixture copied beside an installed wheel, never a provider factory."""
import json
import os
from pathlib import Path

from my_harness.adapters.engine_fake import ScriptedCommandRunner
from my_harness.adapters.git import GitWorkspace
from my_harness.core.engine.commit import GitIdentity
from my_harness.core.engine.context import Command, EnginePolicy, ProjectContext, ProjectProfile
from my_harness.core.engine.contracts import AgentResult, freeze
from my_harness.core.engine.documents import markers
from my_harness.services.managed_runtime import ManagedConfig, ManagedProject

MARKER = 'offline-installed-v2\n'
STATE_BEGIN, STATE_END = markers('state')
ROAD_BEGIN, ROAD_END = markers('roadmap')
DEC_BEGIN, DEC_END = markers('decisions')
# D088 definition drafts; AGENTS, CLAUDE, GEMINI and DDBB-DIAGRAM come from the template.
DRAFTS = {
    'README.md': '# Installed synthetic\n\nOffline wheel verification project.\n',
    'docs/SPECIFICATION.md': '# Specification\n\n## Problem\n\nRecord one synthetic outcome offline.\n',
    'docs/ARCHITECTURE.md': '# Architecture\n\n## Stack\n\nRegistered synthetic profile.\n',
    'docs/ROADMAP.md': (f'# Roadmap\n\n{ROAD_BEGIN}\n{ROAD_END}\n\n## P001 — Foundations\n\n'
                        '**Objetivo:** Deliver one synthetic outcome.\n**Criterios de salida:**\n'
                        '- The synthetic outcome is accepted.\n**Tag:** `p001`\n'),
    'docs/DECISIONS.md': (f'# Decisions\n\nSingle record.\n\n{DEC_BEGIN}\n{DEC_END}\n\n'
                          '## D001 — Use the registered profile\n\n**Estado:** aceptada\n'),
    'docs/STATE.md': (f'# State\n\n{STATE_BEGIN}\n{STATE_END}\n\n## Base acumulada\n\n'
                      'Nothing accepted yet.\n\n## Fase activa — P001 Foundations\n\nNo notes yet.\n'),
    'docs/NEXT_STEPS.md': (f'# P001 — Foundations\n\nGoal in [ROADMAP](ROADMAP.md).\n\n{STATE_BEGIN}\n{STATE_END}\n\n'
                           '## P001-T001 — Synthetic outcome\n\n**Objetivo:** Record the synthetic outcome.\n'
                           '**Rutas permitidas:** `app/**`\n**Criterios de aceptación:**\n'
                           '- The synthetic outcome is present.\n**Comandos de validación:** `test-runner check`\n'
                           '**Ejecutor:** synthetic-executor / medium — Explicit offline selection\n'),
}


class Agent:
    def __init__(self, area):
        self.area = area

    def invoke(self, context, request):
        with (self.area / 'calls.jsonl').open('a') as stream:
            stream.write(freeze({'role': request.role, 'id': request.id}) + '\n')
        if request.role == 'definition':
            payload = {'answer': 'Synthetic drafts', 'questions': [], 'pending': [],
                       'drafts': [{'path': path, 'content': content, 'reason': 'Synthetic definition'}
                                  for path, content in DRAFTS.items()]}
        elif request.role == 'executor':
            context.path('app').mkdir(exist_ok=True)
            context.path('app/outcome.txt').write_text('Synthetic outcome recorded offline.\n')
            payload = {'result': 'synthetic installed executor'}
        elif request.role == 'reviewer':
            payload = {'task_id': json.loads(request.task_json)['task_id'], 'verdict': 'ACCEPT',
                       'findings': [], 'blocking_questions': [], 'scope_grants': []}
        else:
            raise AssertionError('Unexpected role in installed offline journey')
        return AgentResult(freeze(payload), terminal_observed=True, exit_code=0)


def build():
    area = Path(os.environ['HARNESS_E2E_ROOT']).resolve(strict=True)
    if (area / 'marker').read_text() != MARKER:
        raise ValueError('Not a prepared offline fixture')
    profile = ProjectProfile('installed-synthetic', validations=(Command(('test-runner', 'check')),),
                             allowed_command_prefixes=(('test-runner',),))
    context = ProjectContext(area / 'project', profile,
        EnginePolicy(('synthetic-executor',), ('medium',), 'synthetic-planner', 'medium', 'synthetic-reviewer', 'high'),
        documents='v2', work_language='en')  # recorded once at startup, as a `local-config-6` project (D167)
    versions = {'engine': 'e2e-1', 'agent_adapter': 'synthetic-1', 'commands': 'synthetic-1',
                'evidence': 'git-1', 'provider_cli': None}
    agent = Agent(area)
    def writer(c, v):
        assert v == versions
        return GitWorkspace(GitIdentity('Offline E2E', 'e2e@example.invalid'))
    return ManagedConfig((ManagedProject('offline', context, versions, bootstrap_enabled=True),),
        ports_factory=lambda c, v: (agent, ScriptedCommandRunner(), writer(c, v)),
        commit_factory=writer, supervisor=True, poll_seconds=.02)
