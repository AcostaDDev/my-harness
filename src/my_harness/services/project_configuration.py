"""P013-T009: documentary handoff, private project editor and verified activation."""
import copy
import difflib
import json
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine.context import IntakeContext
from my_harness.i18n import tr
from my_harness.core.engine.journal import JournalError
from my_harness.services.configuration import parse
from my_harness.services.configuration_setup import toml_document
from my_harness.services.project_registry import digest
from my_harness.storage.configuration import ConfigurationConflict
from my_harness.storage.models import (PlanningConversationRow as Conversation, PlanningProposalRow as Proposal,
    ProjectBootstrapRow as Bootstrap, ProjectImportRow as Import, ProjectPreparationOperationRow as Preparation)


class ProjectConfiguration:
    def __init__(self, runtime):
        self.runtime = runtime

    @property
    def repository(self):
        setup = self.runtime.setup
        if setup is None:
            raise ConfigurationConflict('project_configuration_unavailable')
        if setup.legacy:
            from my_harness.services.configuration_import import imported
            with Session(self.runtime.engine) as session:
                if not imported(session):
                    raise ConfigurationConflict('project_configuration_unavailable')
        return setup.repository

    def proposal(self, session, project_id):
        project = self.runtime.project(project_id)
        proposal = session.scalar(select(Proposal).join(Conversation, Conversation.id == Proposal.conversation_id)
            .where(Conversation.root == str(project.context.root), Proposal.kind == 'profile', Proposal.status == 'ACCEPTED'))
        if not proposal:
            raise ConfigurationConflict('accepted_profile_required')
        return proposal

    def check_candidate(self, project_id, data):
        project = self.runtime.project(project_id)
        state = self.repository.read('project:' + project_id)
        if state['active']:
            from my_harness.services.configuration_editing import documentary
            from my_harness.services.profile_preparation import validate_plan
            from my_harness.services.local_config import _profile
            before = parse(self.repository.document(state['scope'], state['active']['revision']), state['scope'])
            if data['project'] != before['project'] or data.get('provenance') != before.get('provenance'):
                raise ConfigurationConflict('project_identity_changed')
            # A later technical edit is bound to the current committed documentary context. Agent-only
            # edits retain the original receipt; the admitted pair still performs any new preparation.
            if data.get('edit'):
                _, git = self.runtime.preparation.writer(project)
                binding = documentary(project.context, git)
                if {k: data['edit'][k] for k in ('head', 'documents')} != binding:
                    raise ConfigurationConflict('documentary_profile_changed')
                validate_plan(data['edit']['preparation_plan'],
                    _profile(data['profile_name'], data['profile'], allow_formatter=True), project.context)
            if data['profile'] != before['profile'] or data['profile_name'] != before['profile_name']:
                from my_harness.services.configuration_editing import prepared
                with Session(self.runtime.engine) as session:
                    prior = prepared(session, state['scope'], before, reference=state['active'], verify=False)
                    baseline = before.get('edit', {}).get('documents', prior.plan['base_files'])
                if (not data.get('edit') or all(baseline.get(p) == h for p, h in data['edit']['documents'].items())):
                    raise ConfigurationConflict('profile_documentary_update_required')
            return data
        if state['saved']:
            saved = parse(self.repository.document(state['scope'], state['saved']['revision']), state['scope'], validated=False)
            if saved.get('provenance', {}).get('source') == 'legacy-configuration':
                if data['project'] != saved['project'] or data.get('provenance') != saved.get('provenance'):
                    raise ConfigurationConflict('project_identity_changed')
                if not data.get('edit'):
                    raise ConfigurationConflict('profile_documentary_update_required')
                from my_harness.services.configuration_editing import documentary
                _, git = self.runtime.preparation.writer(project)
                binding = documentary(project.context, git)
                if {k: data['edit'][k] for k in ('head', 'documents')} != binding:
                    raise ConfigurationConflict('documentary_profile_changed')
                return data
        with Session(self.runtime.engine) as session:
            proposal = self.proposal(session, project_id)
            candidate = json.loads(proposal.content)['candidate']
        if (data['project'] != {'id': project_id, 'root': str(project.context.root)}
                or data['profile_name'] != candidate['name'] or data['profile'] != candidate['profile']
                or data.get('provenance') != {'source': 'profile-proposal', 'sha256': proposal.proposal_sha256}):
            raise ConfigurationConflict('documentary_profile_changed')
        # T009 changes tool paths/command limits, never the admitted agent pair or policy.
        original = self.initial(project_id)
        if data['policy'] != original['policy'] or data['agents'] != original['agents']:
            raise ConfigurationConflict('intake_agent_policy_changed')
        if set(data['commands']['executables']) != {tool['name'] for tool in candidate['tools']}:
            raise ConfigurationConflict('profile_tools_changed')
        return data

    def initial(self, project_id):
        project = self.runtime.project(project_id)
        registrar = self.runtime.registry.registrar
        with Session(self.runtime.engine) as session:
            proposal = self.proposal(session, project_id)
            candidate = json.loads(proposal.content)['candidate']
        state = self.repository.read('global')
        if state['status'] != 'READY' or not state['active']:
            raise ConfigurationConflict('active_global_configuration_required')
        row = self.runtime.registry.repository.get(project_id)['row']
        declarations = ({role: registrar.presets[choice['preset_id']][1]
                         for role, choice in row['agent_selection'].items()} if row.get('agent_selection') else registrar.agents)
        from my_harness.services.local_config import CLI_KEYS, TOOL_KEYS
        agents = {role: {key: value for key, value in asdict(declaration).items()
                        if key in (*CLI_KEYS, *TOOL_KEYS, 'provider') and value is not None
                        and not (key == 'executable' and not value)} for role, declaration in declarations.items()}
        # CLI declarations use tuple pairs, while the editor accepts JSON/TOML tables and arrays.
        for role in agents:
            agents[role]['environment'] = dict(declarations[role].environment)
            if 'executable' in agents[role]:
                agents[role]['executable'] = list(agents[role]['executable'])
            for key in ('tools', 'allowed_tools', 'grantable_tools'):
                if key in agents[role]:
                    if role in ('reviewer', 'judge') or declarations[role].provider != 'claude':
                        agents[role].pop(key)
                    else:
                        agents[role][key] = list(agents[role][key])
        agents['reviewer'].update(model=project.context.policy.reviewer_model, effort=project.context.policy.reviewer_effort)
        if 'judge' in agents:
            agents['judge'].update(model=project.versions['judge_model'], effort=project.versions['judge_effort'])
        local = candidate.get('preparation_plan', {}).get('local_paths', [])
        base = local[0].removesuffix('/**') if local else '.harness-preparation'
        return {'format': 'project-config-3' if 'judge' in agents else 'project-config-1', 'project': {'id': project_id, 'root': str(project.context.root)},
                'global': {key: state['active'][key] for key in ('revision', 'sha256')},
                'profile_name': candidate['name'], 'profile': copy.deepcopy(candidate['profile']),
                'commands': {'executables': {tool['name']: '' for tool in candidate['tools']},
                    'environment': {'HOME': str(project.context.root / base / 'home'),
                                    'TMPDIR': str(project.context.root / base / 'tmp')},
                    'authorize_profile_commands': True, 'max_timeout_seconds': 1800, 'max_output_bytes': 1048576},
                'policy': row['policy'], 'agents': agents,
                'provenance': {'source': 'profile-proposal', 'sha256': proposal.proposal_sha256}}

    def candidate(self, project_id, *, text=None, form=None, validated=True):
        if (text is None) == (form is None):
            raise ValueError(tr('setup.invalid'))
        text = toml_document(form) if form is not None else text
        data = parse(text, 'project:' + project_id, validated=validated)
        if validated:
            self.check_candidate(project_id, data)
        else:
            commands = data.get('commands', {})
            if (not isinstance(data.get('profile_name'), str)
                    or not isinstance(data.get('profile'), dict)
                    or not isinstance(data['profile'].get('executor_instructions'), str)
                    or not isinstance(commands.get('executables'), dict)
                    or not isinstance(commands.get('environment'), dict)
                    or any(not isinstance(value, str) for value in (
                        *commands['executables'].values(), *commands['environment'].values()))):
                raise ValueError(tr('setup.invalid'))
        return text

    def read(self, project_id):
        project = self.runtime.project(project_id)
        scope = 'project:' + project_id
        state = self.repository.read(scope)
        text = self.repository.document(scope, state['saved']['revision']) if state['saved'] else None
        if text and parse(text, scope, validated=False).get('provenance', {}).get('source') == 'legacy-configuration':
            from my_harness.storage.models import ConfigurationRevisionRow as Revision
            with Session(self.runtime.engine) as session:
                revision = session.get(Revision, (scope, state['saved']['revision']))
                registry = self.runtime.registry.repository.get(project_id)
            prepared = self.runtime.preparation.read(project_id)
            form = parse(text, scope, validated=False)
            from my_harness.services.configuration_editing import prepared as selected_preparation
            try:
                with Session(self.runtime.engine) as session:
                    selected_preparation(session, scope, form, reference=state['saved'])
            except (ValueError, OSError, JournalError):
                prepared = {**prepared, 'prepared': False}
            stage = 'READY_TO_ACTIVATE' if prepared['prepared'] else 'PREPARATION_REQUIRED'
            if state['active']:
                try:
                    receipt = self.active_receipt(project_id, state['active'])
                    if state['status'] != 'READY':
                        raise ConfigurationConflict('project_configuration_changed')
                    self.runtime.preparation.generic().verify_configuration(project, receipt, active=True)
                    stage = 'ACTIVE'
                except (ValueError, OSError, JournalError):
                    stage = 'PREPARATION_REQUIRED'
            return {**state, 'configuration_state': stage, 'candidate_state': ('READY_TO_ACTIVATE' if prepared['prepared'] else 'PREPARATION_REQUIRED') if state['saved'] != state['active'] else stage, 'text': text, 'form': form,
                'proposal_id': revision.operation_id, 'proposal_sha256': state['saved']['sha256'],
                'profile': {'candidate': {'name': form['profile_name'], 'profile': form['profile']}},
                'preparation': {**prepared, 'available': True, 'project_version': registry['version']},
                'assistance_documents': self.assistance_documents(project)}
        with Session(self.runtime.engine) as session:
            proposal = self.proposal(session, project_id)
            payload = json.loads(proposal.content)
            documentary = session.scalar(select(Bootstrap).where(Bootstrap.root == str(project.context.root)))
            if documentary is None:
                documentary = session.scalar(select(Import).where(Import.root == str(project.context.root)))
        from my_harness.storage.knowledge_exchange import completed_at_root
        with Session(self.runtime.engine) as session:
            structured_delivery = completed_at_root(session, str(project.context.root))
        stage = ('PREPARATION_REQUIRED' if state['saved'] else 'DOCUMENTS_COMMITTED') if structured_delivery else 'PROFILE_PROPOSED'
        if documentary:
            stage = ('PREPARATION_REQUIRED' if state['saved'] else 'DOCUMENTS_COMMITTED') if documentary.status == 'COMPLETED' else 'PROFILE_PROPOSED'
        prepared = self.runtime.preparation.read(project_id)
        if prepared['prepared']:
            stage = 'READY_TO_ACTIVATE'
        candidate_stage = stage
        if state['active'] and not isinstance(project.context, IntakeContext):
            try:
                receipt = self.active_receipt(project_id, state['active'])
                if state['status'] != 'READY' or not receipt:
                    raise ConfigurationConflict('project_preparation_changed')
                self.runtime.preparation.generic().verify_configuration(project, receipt, active=True)
                stage = 'ACTIVE'
            except (ValueError, OSError, JournalError):
                stage = 'PREPARATION_REQUIRED'
            if state['saved'] == state['active']:
                candidate_stage = stage
        proposal_id, proposal_sha256 = proposal.id, proposal.proposal_sha256
        if state['active'] and state['saved'] and parse(text, scope, validated=False).get('edit'):
            from my_harness.storage.models import ConfigurationRevisionRow as Revision
            with Session(self.runtime.engine) as session:
                proposal_id = session.get(Revision, (scope, state['saved']['revision'])).operation_id
            proposal_sha256 = state['saved']['sha256']
        return {**state, 'configuration_state': stage, 'candidate_state': candidate_stage, 'text': text,
                'form': parse(text, scope, validated=False) if text else self.initial(project_id),
                'proposal_id': proposal_id, 'proposal_sha256': proposal_sha256,
                'profile': payload, 'preparation': prepared,
                'assistance_documents': self.assistance_documents(project)}

    @staticmethod
    def assistance_documents(project):
        from my_harness.core.engine.documents import layout
        target = layout(project.context)
        return [target.agents, target.specification, target.architecture, target.decisions]

    def edit_base(self, project_id):
        from my_harness.services.configuration_editing import documentary, prepared
        project = self.runtime.project(project_id)
        state = self.repository.read('project:' + project_id)
        if not state['active'] and state['saved']:
            data = parse(self.repository.document(state['scope'], state['saved']['revision']), state['scope'], validated=False)
            if data.get('provenance', {}).get('source') == 'legacy-configuration':
                _, git = self.runtime.preparation.writer(project)
                if git.run('status', '--porcelain=v1', '--untracked-files=all').strip():
                    raise ConfigurationConflict('prepared_head_changed')
                data['edit'] = {**documentary(project.context, git), 'preparation_plan': {
                    'write_paths': [], 'local_paths': [], 'environment_paths': [], 'dependencies': [],
                    'network': [], 'scripts': False, 'executor_selection': {
                        'model': project.context.policy.executor_models[0], 'effort': project.context.policy.executor_efforts[0],
                        'reason': 'Explicit imported profile preparation'}, 'instructions': ''}}
                return {'text': toml_document(data), 'form': data}
        if not state['active'] or state['status'] != 'READY':
            raise ConfigurationConflict('active_project_configuration_required')
        data = parse(self.repository.document(state['scope'], state['saved']['revision']), state['scope'])
        active = parse(self.repository.document(state['scope'], state['active']['revision']), state['scope'])
        with Session(self.runtime.engine) as session:
            row = prepared(session, state['scope'], active, reference=state['active'], verify=False)
            plan = data.get('edit', {}).get('preparation_plan', row.plan['technical'])
        _, git = self.runtime.preparation.writer(project)
        if git.run('status', '--porcelain=v1', '--untracked-files=all').strip():
            raise ConfigurationConflict('prepared_head_changed')
        data['edit'] = {**documentary(project.context, git), 'preparation_plan': plan}
        return {'text': toml_document(data), 'form': data}

    def verify(self, session, scope, data):
        from my_harness.storage.models import ConfigurationScopeRow as Scope
        head = session.get(Scope, scope)
        if (not head or not head.active_revision) and data.get('provenance', {}).get('source') != 'legacy-configuration':
            return self._verify_initial(session, scope, data)
        from my_harness.services.configuration_editing import verify_revision
        evidence = verify_revision(session, scope, data, self.repository)
        row = session.get(Preparation, evidence['operation_id'])
        reference = self.repository._ref(session, scope, head.saved_revision)
        self.runtime.config.registrar.compose_profile(self.runtime.project(scope[8:]), data, row.receipt, reference)
        return evidence

    def _verify_initial(self, session, scope, data):
        project = self.runtime.project(scope[8:])
        row = session.scalar(select(Preparation).where(Preparation.project_id == project.id,
            Preparation.status == 'COMPLETED').order_by(Preparation.created_at.desc(), Preparation.id.desc()).limit(1))
        if not row or not row.receipt or row.plan.get('configuration_data') != data:
            raise ConfigurationConflict('project_preparation_required')
        try:
            self.runtime.preparation.generic().verify_configuration(project, row.receipt)
        except (ValueError, OSError, JournalError):
            raise ConfigurationConflict('project_preparation_changed') from None
        # Activation requires the exact prepared HEAD and a clean index/worktree. Later tasks may evolve ordinary code.
        _, git = self.runtime.preparation.writer(project)
        if (git.text('rev-parse', 'HEAD') != row.receipt['commit']
                or git.run('status', '--porcelain=v1', '--untracked-files=all').strip()):
            raise ConfigurationConflict('prepared_head_changed')
        self.check_candidate(project.id, data)
        # Compose before the transaction can publish authority, without installing or running clients.
        self.runtime.registry.registrar.compose_profile(project, data, row.receipt, row.receipt['configuration'])
        return {'operation_id': row.id, 'receipt_sha256': digest(row.receipt), 'commit': row.receipt['commit']}

    def activation_preview(self, references, *, reason):
        preview = self.repository.activation_preview(references, reason=reason)
        changes = []
        for reference in preview['references']:
            scope = reference['scope']
            text = self.repository.document(scope, reference['revision'])
            previous = reference['previous']
            before = self.repository.document(scope, previous['revision']) if previous else ''
            changes.append({'scope': scope, 'sha256': reference['sha256'], 'text': text,
                'diff': ''.join(difflib.unified_diff(before.splitlines(True), text.splitlines(True),
                    fromfile='active', tofile='candidate'))})
        # Diffs are a derived view of the immutable before/after hashes already sealed in the preview.
        return {**preview, 'changes': changes}

    def active_receipt(self, project_id, reference):
        from my_harness.services.configuration_editing import prepared
        with Session(self.runtime.engine) as session:
            data = parse(self.repository.document('project:' + project_id, reference['revision']), 'project:' + project_id)
            return prepared(session, 'project:' + project_id, data, reference=reference).receipt

    def install_active(self, project, *, reference=None, global_reference=None):
        """Install the active revision, or stage an explicit candidate reference of a live set (D238)."""
        state = self.repository.read('project:' + project.id)
        reference = reference or state['active']
        if not reference:
            return project
        # While a live set is pending, the active revision remains the authority; a staged first
        # activation has no active revision yet.
        allowed = ('READY', 'APPLY_PENDING', *(('UNCONFIGURED',) if reference is not state['active'] else ()))
        if state['status'] not in allowed:
            raise ConfigurationConflict('project_configuration_changed')
        data = parse(self.repository.document(state['scope'], reference['revision']), state['scope'])
        receipt = self.active_receipt(project.id, reference)
        if not receipt:
            raise ConfigurationConflict('project_preparation_required')
        try:
            self.runtime.preparation.generic().verify_configuration(project, receipt, active=True,
                reference=reference, global_reference=global_reference)
        except (ValueError, OSError, JournalError):
            raise ConfigurationConflict('project_preparation_changed') from None
        composed = self.runtime.registry.registrar.compose_profile(project, data, receipt, reference)
        self.runtime.registry.registrar._receipts[project.context.root] = receipt
        return self.runtime.registry.registrar.install(composed)
