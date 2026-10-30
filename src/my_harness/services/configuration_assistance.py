"""Explicit single-turn assistance, with a frozen active pair and its own process journal.

The only writer workspace is a new private scratch directory. Candidates are data;
neither completion nor recovery saves, activates or retries them.
"""
import copy
from dataclasses import replace
import json
import os
from uuid import uuid4

from sqlalchemy.orm import Session

from my_harness.adapters.cli_agents import CLIProcessAdapter, EFFORTS
from my_harness.adapters.cli_diagnostics import preflight_config
from my_harness.adapters.processes import identity, liveness
from my_harness.core.engine.context import IntakeContext, EnginePolicy
from my_harness.core.engine.contracts import AgentRequest, Selection, freeze
from my_harness.i18n import current as visual_language, tr
from my_harness.services.configuration import parse, secretless
from my_harness.services.configuration_setup import toml_document
from my_harness.services.local_config import _agents
from my_harness.storage import accounting
from my_harness.storage.configuration import ConfigurationConflict, seal, operation_view
from my_harness.storage.models import ConfigurationOperationRow as Operation, UsageInvocationRow as Invocation

SCHEMA = {'type': 'object', 'additionalProperties': False,
    'properties': {'text': {'type': 'string'}, 'rationale': {'type': 'string'},
                   'questions': {'type': 'array', 'items': {'type': 'string'}}},
    'required': ['text', 'rationale', 'questions']}


class AssistanceJournal:
    def __init__(self, service, operation_id, owner):
        self.service, self.operation_id, self.owner = service, operation_id, owner

    def mutate(self, transform):
        with self.service.repository.managed._write() as session:
            row = session.get(Operation, self.operation_id)
            if not row or row.status != 'INTENDED' or row.payload['owner'] != self.owner:
                raise ConfigurationConflict('configuration_assistance_ownership_lost')
            payload = copy.deepcopy(row.payload)
            transform(payload)
            row.payload, row.updated_at = payload, self.service.repository.managed._now()

    def process_intent(self, attempt_id, spec):
        def record(payload):
            if (payload.get('process') or attempt_id != payload['attempt_id']
                    or spec.get('adapter_version') != 'cli-14'):
                raise ConfigurationConflict('configuration_assistance_process_changed')
            payload['process'] = {'spec': spec, 'identity': None, 'status': 'PENDING'}
        self.mutate(record)

    def process_update(self, attempt_id, kind, value):
        def record(payload):
            process = payload.get('process')
            if not process or attempt_id != payload['attempt_id']:
                raise ConfigurationConflict('configuration_assistance_process_changed')
            if kind == 'process_spawned':
                if process['status'] != 'PENDING' or process['identity'] is not None:
                    raise ConfigurationConflict('configuration_assistance_process_changed')
                process.update(identity=value, status='RUNNING')
            elif kind == 'process_finished':
                process.update(capture=value, status='STOPPED' if value.get('group_state') == 'dead' else 'UNCERTAIN')
            # Stream bodies remain in the adapter's bounded private artifacts, not the SQLite row.
        if kind in ('process_spawned', 'process_finished'):
            self.mutate(record)

    def cancel_requested(self):
        return False


class ConfigurationAssistance:
    def __init__(self, runtime):
        self.runtime = runtime

    @property
    def repository(self):
        if self.runtime.setup is None or self.runtime.setup.legacy:
            raise ConfigurationConflict('configuration_import_required')
        return self.runtime.setup.repository

    def source(self, scope):
        self.repository._writable()
        self.runtime.setup.require_ready()
        state = self.repository.read(scope)
        if state['status'] != 'READY' or not state['active']:
            raise ConfigurationConflict('active_configuration_required')
        text = self.repository.document(scope, state['active']['revision'])
        return state, parse(text, scope)

    def adapter(self, data):
        agents, _ = _agents(data['agents'], automatic=True,
                            allow_judge=data['format'] in ('local-config-11', 'project-config-3'))
        resolved = {}
        for role, config in agents.items():
            from my_harness.adapters.cli_diagnostics import discover
            config = discover(config)
            report = preflight_config(config, access='write' if role == 'executor' else 'read')
            if not report['available']:
                raise ConfigurationConflict('configuration_assistance_clients_unavailable')
            resolved[role] = replace(config, cli_version=report['observed_version'])
        return CLIProcessAdapter(resolved, self.runtime.setup.state_dir / 'configuration-assistance' / 'artifacts')

    def preview(self, scope, body):
        state, active = self.source(scope)
        if (state['version'] != body['expected_version'] or state['active']['sha256'] != body['active_sha256']
                or state['actual_sha256'] != body['base_sha256']):
            raise ConfigurationConflict('stale_configuration_preview')
        candidate = body['candidate']
        if (candidate.get('text') is None) == (candidate.get('form') is None):
            raise ValueError('candidate')
        text = candidate['text'] if candidate.get('text') is not None else toml_document(candidate['form'])
        parse(text, scope, validated=False)
        role = body['role']
        agents = self.adapter(active)
        try:
            versions = agents.frozen_versions()
        finally:
            agents.close()
        selection = body.get('selection')
        if role == 'reviewer':
            selection = {k: active['agents']['reviewer'][k] for k in ('model', 'effort')}
        elif (not selection or not selection.get('model', '').strip()
                or selection.get('effort') not in EFFORTS[active['agents']['executor']['provider']]):
            raise ValueError('selection')
        if role == 'executor' and scope != 'global':
            from my_harness.core.engine.contracts import executor_selection
            executor_selection(self.runtime.project(scope[8:]).context, {**selection, 'reason': body['message']})
        context = []
        if scope != 'global':
            from my_harness.storage.chat import read_documents
            project = self.runtime.project(scope[8:])
            from my_harness.core.engine.documents import layout
            target = layout(project.context)
            allowed = {target.agents, target.specification, target.architecture, target.decisions}
            if set(body['documents']) - allowed:
                raise ValueError('documents')
            context = read_documents(project.context, body['documents'])
        elif body['documents']:
            raise ValueError('documents')
        value = {'contract': 'configuration-assistance-1', 'scope': scope, 'source': state['active'],
            'version': state['version'], 'working_sha256': state['actual_sha256'], 'role': role,
            'selection': selection, 'versions': versions, 'text': text, 'message': body['message'],
            'documents': context, 'active_agents_sha256': seal(active['agents']),
            'write_scope': 'private_scratch' if role == 'executor' else 'read_only',
            'network_commands': [], 'configuration_write': False,
            'work_language': (self.runtime.project(scope[8:]).context.work_language if scope != 'global'
                              else visual_language())}
        return {**value, 'sha256': seal(value)}

    def confirm(self, scope, body, *, preview_sha256, key):
        self.repository._writable()
        request = {'kind': 'ASSIST', 'scope': scope, 'body': body, 'preview_sha256': preview_sha256}
        with Session(self.runtime.engine) as session:
            replay = self.repository._replay(session, key, request)
            if replay:
                return replay
        preview = self.preview(scope, body)
        if preview['sha256'] != preview_sha256:
            raise ConfigurationConflict('stale_configuration_assistance')
        _, data = self.source(scope)
        adapter = self.adapter(data)
        owner, attempt_id = identity(), str(uuid4())
        with self.repository.managed._write() as session:
            replay = self.repository._replay(session, key, request)
            if replay:
                adapter.close()
                return replay
            self.repository._clear(session)
            # CAS and global readiness use the same serialized write connection as activation/admission.
            self.runtime.setup.require_ready(session)
            state = self.repository._state(session, self.repository._files(session), scope)
            if (state['version'] != preview['version'] or state['active'] != preview['source']
                    or state['actual_sha256'] != preview['working_sha256']
                    or adapter.frozen_versions() != preview['versions']):
                adapter.close()
                raise ConfigurationConflict('stale_configuration_assistance')
            row = self.repository._operation(session, key, request,
                {'preview': preview, 'owner': owner, 'attempt_id': attempt_id, 'owner_closed': False},
                kind='ASSIST', status='INTENDED')
            operation_id = row.id
            accounting.intend_assistance(session, row, preview, attempt_id, self.repository.managed._now())
        workspace = self.runtime.setup.state_dir / 'configuration-assistance' / 'work' / operation_id
        result, failure_type = None, None
        try:
            from my_harness.storage.configuration_files import ConfigurationFiles
            private = self.runtime.setup.state_dir / 'configuration-assistance'
            if private.parent.resolve() != private.parent:
                raise ValueError(tr('configuration.private'))
            private.mkdir(mode=0o700, exist_ok=True)
            files = ConfigurationFiles(private)
            with files.folder(('work',), create=True) as fd:
                os.mkdir(operation_id, 0o700, dir_fd=fd)
                os.fsync(fd)
            with files.folder(('artifacts',), create=True):
                pass
            if body['role'] == 'executor':
                from my_harness.adapters.git import Git
                global_state = self.repository.read('global')
                global_data = parse(self.repository.document('global', global_state['active']['revision']), 'global')
                Git(workspace, executable=global_data['git']['executable']).run('init')
            policy = EnginePolicy(('unused',), ('low',), 'unused', 'low', 'unused', 'low')
            context = IntakeContext(workspace, policy, work_language=preview['work_language'])
            schema = SCHEMA if body['role'] == 'reviewer' else {
                'type': 'object', 'properties': {'result': {'type': 'string'}}, 'required': ['result'], 'additionalProperties': False}
            snapshot = {'output_schema': schema, 'schema_sha256': seal(schema), 'configuration_assistance': True}
            payload = {'candidate': preview['text'], 'documents': preview['documents'], 'request': body['message']}
            prompt = ('Work only from the supplied data. Do not read other directories or execute commands, '
                'installers, Git or network. Never edit configuration or user settings. '
                'The active client pair is frozen; proposed clients cannot run in this turn. '
                + ('Return complete candidate TOML, rationale and questions. Do not claim checks were run. '
                   if body['role'] == 'reviewer' else
                   'Inspect the candidate; any scratch files must stay in this private workspace. Return observations only. ')
                + ('Respond in ' + (preview['work_language'] or 'English') + '.\n') + freeze(payload))
            journal = AssistanceJournal(self, operation_id, owner)
            journal.mutate(lambda p: p.update(prompt=prompt, snapshot=snapshot, workspace=str(workspace)))
            adapter.bind_preparation(journal, preview['versions'])
            answer = adapter.invoke(context, AgentRequest(attempt_id,
                'configuration' if body['role'] == 'reviewer' else 'executor',
                Selection(**preview['selection'], reason=body['message']), prompt, None, freeze({'root': str(workspace)}),
                prompt_snapshot_json=freeze(snapshot)))
            if answer.error or not answer.terminal_observed or answer.exit_code != 0 or not answer.payload_json:
                raise ValueError('answer')
            result = json.loads(answer.payload_json)
            secretless(result)
            if len(freeze(result).encode()) > 100000:
                raise ValueError('answer')
            if body['role'] == 'reviewer':
                if (set(result) != {'text', 'rationale', 'questions'} or not isinstance(result['rationale'], str)
                        or not result['rationale'].strip() or not isinstance(result['questions'], list)
                        or any(not isinstance(q, str) for q in result['questions'])):
                    raise ValueError('answer')
                parse(result['text'], scope, validated=False)
            elif (not isinstance(result, dict) or 'result' not in result
                    or set(result) - {'result', 'decision_proposals'}
                    or result.get('decision_proposals', []) != [] or not isinstance(result['result'], str)):
                raise ValueError('answer')
            current = self.repository.read(scope)
            if (current['active'] != preview['source'] or current['actual_sha256'] != preview['working_sha256']
                    or current['status'] != 'READY'):
                raise ConfigurationConflict('configuration_assistance_source_changed')
        except Exception as error:
            failure_type = type(error).__name__
            result = {'diagnostic': 'configuration_assistance_failed'}
        finally:
            adapter.close()
            with self.repository.managed._write() as session:
                row = session.get(Operation, operation_id)
                payload = copy.deepcopy(row.payload)
                process = payload.get('process')
                uncertain = bool(process and (process['status'] != 'STOPPED' or
                    process.get('identity') and liveness(process['identity'], group=True) != 'dead'))
                payload['owner_closed'] = True
                row.payload = payload
                row.status = 'RECOVERY_REQUIRED' if uncertain else 'APPLIED'
                accounting.settle_process(session, 'configuration_assistance', operation_id, process,
                                          outcome=row.status, now=self.repository.managed._now())
                row.result = {'proposal': result, 'preview': preview, 'authority_changed': False,
                              **({'failure_type': failure_type} if failure_type else {})}
                row.updated_at = self.repository.managed._now()
        return self.repository.operation(operation_id)

    def recover(self, operation_id, *, writers_stopped):
        self.repository._writable()
        if writers_stopped is not True:
            raise ConfigurationConflict('configuration_writers_not_confirmed_stopped')
        with self.repository.managed._write() as session:
            row = session.get(Operation, operation_id)
            if not row or row.kind != 'ASSIST':
                raise ConfigurationConflict('configuration_not_recoverable')
            if row.status == 'APPLIED':
                return operation_view(row)
            payload, process = row.payload, row.payload.get('process')
            if (not payload.get('owner_closed') and liveness(payload['owner']) != 'dead'
                    or process and process.get('identity') and liveness(process['identity'], group=True) != 'dead'):
                raise ConfigurationConflict('configuration_assistance_writer_alive')
            row.status = 'APPLIED'
            from my_harness.storage.permissions import actor
            row.payload = {**row.payload, 'recovery': {'writers_stopped': True, 'actor': actor(),
                                                     'at': self.repository.managed._now()}}
            row.result = {**(row.result or {}), 'authority_changed': False, 'recovered_without_retry': True}
            invocation = session.get(Invocation, accounting.key('configuration_assistance', row.id))
            if invocation is not None and invocation.launch == 'pending':
                # Recovery classifies the recorded evidence only; it never launches or retries inference.
                accounting.settle_process(session, 'configuration_assistance', row.id, process,
                                          outcome='APPLIED', now=self.repository.managed._now())
            row.updated_at = self.repository.managed._now()
            return operation_view(row)
