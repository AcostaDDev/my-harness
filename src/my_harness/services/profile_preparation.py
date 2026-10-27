"""Confirmed generic preparation (D218), separate from immutable packaged recipes.

The native UID boundary remains cooperative. Exact commands, a closed environment,
process gates and before/after content guards do not constitute an OS sandbox.
"""
from dataclasses import asdict
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.preparation import PreparationCommandRunner, file_hash, verify_files, verify_tools
from my_harness.core.engine.context import relative_path
from my_harness.core.engine.contracts import (AgentRequest, context_snapshot, executor_selection, freeze)
from my_harness.core.engine.documents import layout
from my_harness.core.engine.evidence import matches
from my_harness.core.engine.junit import capture_junit, observe_report
from my_harness.i18n import tr
from my_harness.services import local_config
from my_harness.services.configuration import parse, secretless
from my_harness.services.project_creation import directory, identity
from my_harness.services.project_preparation import ProjectPreparation, snapshot
from my_harness.services.project_registry import RegistryError, digest
from my_harness.storage.models import (
    RegisteredProjectRow as Project,
    PlanningProposalRow as Proposal, PlanningConversationRow as Conversation,
    ProjectBootstrapRow as Bootstrap, ProjectImportRow as Import, PhaseRow as Phase,
    ProjectPreparationStepRow as Step, ProjectPreparationOperationRow as Operation,
)
from my_harness.storage.preparation import PreparationJournal, PreparationAgentJournal

CONTRACT = 'project-profile-preparation-1'
TOOL_LINK_POLICY = 'external-directories-1'


def git_controls(root):
    """Freeze Git settings/hooks/HEAD; object writes and the service's own index/ref CAS are separate."""
    result = {}
    with directory(root / '.git'):
        for folder, dirs, files in os.walk(root / '.git', followlinks=False):
            if Path(folder) == root / '.git':
                dirs[:] = [name for name in dirs if name not in ('objects', 'logs', 'refs')]
            for name in dirs + files:
                path = Path(folder) / name
                key = str(path.relative_to(root / '.git'))
                if key in ('index', 'packed-refs'):
                    continue
                info = path.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    result[key] = {'sha256': file_hash(path), 'mode': stat.S_IMODE(info.st_mode)}
                elif not stat.S_ISDIR(info.st_mode):
                    raise refuse('scope')
    return result


def refs(git):
    return dict(line.split(' ', 1) for line in git.text('for-each-ref', '--format=%(refname) %(objectname)').splitlines())


def environment_entries(workspace, patterns):
    roots = {p.removesuffix('/**') for p in patterns}
    return {p: v for p, v in workspace.items() if p in roots or matches(p, patterns)}


def tool_link(path, tools):
    """D247: bounded file-link resolution, never traversing a directory symlink."""
    chain = []
    for _ in range(41):
        with directory(path.parent) as fd:
            info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            # Normalize '..' only after proving every parent is a real directory.
            path = Path(os.path.normpath(path))
            if stat.S_ISLNK(info.st_mode):
                if len(chain) == 40:
                    raise refuse('scope')
                link = os.readlink(path.name, dir_fd=fd)
                chain.append({'path': str(path), 'link': link, 'mode': stat.S_IMODE(info.st_mode)})
                path = path.parent / link
            else:
                if (not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111
                        or not any(str(path) == tool['resolved'] for tool in tools.values())):
                    raise refuse('scope')
                return {'chain': chain, 'resolved': str(path), 'mode': stat.S_IMODE(info.st_mode)}


def external_tool_link(path, tools, root):
    """D248: resolve exact tool components, explicitly binding external directory aliases."""
    pending, current, chain = list(path.parts[1:]), Path('/'), []
    while pending:
        part, *pending = pending
        if part in ('', '.'):
            continue
        if part == '..':
            current = current.parent
            continue
        candidate = current / part
        with directory(current) as fd:
            info = os.stat(part, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                if len(chain) == 40 or pending and candidate.is_relative_to(root):
                    raise refuse('scope')
                link = os.readlink(part, dir_fd=fd)
                evidence = {'path': str(candidate), 'link': link, 'mode': stat.S_IMODE(info.st_mode)}
                if pending:
                    evidence['directory'] = True
                chain.append(evidence)
                # Keep trailing slash/dot components: a regular file cannot serve as a directory.
                parts = link.split('/')
                if link.startswith('/'):
                    current = Path('/')
                    pending = parts[1:] + pending
                else:
                    pending = parts + pending
            elif pending:
                if not stat.S_ISDIR(info.st_mode):
                    raise refuse('scope')
                current = candidate
            else:
                if (not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111
                        or not any(str(candidate) == tool['resolved'] for tool in tools.values())):
                    raise refuse('scope')
                return {'chain': chain, 'resolved': str(candidate), 'mode': stat.S_IMODE(info.st_mode)}
    raise refuse('scope')


def refuse(key='invalid'):
    return RegistryError(409, 'profile_preparation_' + key, tr('profile_preparation.' + key))


def paths(values, *, empty=True):
    if not isinstance(values, list) or len(values) > 64 or (not empty and not values):
        raise refuse()
    for value in values:
        if not isinstance(value, str):
            raise refuse()
        base = value[:-3] if value.endswith('/**') else value
        if (str(relative_path(base)) != base or base == '.' or any(c in base for c in '*?[')
                or '.git' in Path(base).parts):
            raise refuse()
    if len(set(values)) != len(values):
        raise refuse()
    return values


def validate_plan(value, profile, context):
    """Reviewer data, not permission. Confirmation later binds installed tools/configuration."""
    keys = {'write_paths', 'local_paths', 'environment_paths', 'dependencies', 'network', 'scripts',
            'executor_selection', 'instructions'}
    if not isinstance(value, dict) or set(value) != keys:
        raise refuse()
    secretless(value)
    paths(value['write_paths'])
    paths(value['local_paths'])
    paths(value['environment_paths'])
    if any(not p.endswith('/**') or p not in value['write_paths'] for p in value['local_paths']):
        raise refuse()
    if any(p not in value['local_paths'] for p in value['environment_paths']):
        raise refuse()
    target = layout(context)
    for pattern in value['write_paths']:
        base = pattern.removesuffix('/**')
        # Technical authority may include profile manifests, never documentary/Git authority.
        if (base in (*target.instructions, target.readme) or base == target.docs
                or base.startswith(target.docs + '/')
                or matches(base, profile.sensitive_paths) and not matches(base, profile.sensitive_allowlist)):
            raise refuse('scope')
    if type(value['scripts']) is not bool or not isinstance(value['network'], list) or len(value['network']) > 16:
        raise refuse()
    for url in value['network']:
        parsed = urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise refuse()
    dependencies = value['dependencies']
    if not isinstance(dependencies, list) or len(dependencies) > 64:
        raise refuse()
    for item in dependencies:
        if not isinstance(item, dict) or set(item) != {'name', 'version', 'lock_path', 'sha256'}:
            raise refuse()
        paths([item['lock_path']])
        if any(not isinstance(item[k], str) or not item[k].strip() for k in ('name', 'version')):
            raise refuse()
        if not isinstance(item['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', item['sha256']):
            raise refuse()
    executor_selection(context, value['executor_selection'])
    if not isinstance(value['instructions'], str) or not value['instructions'].strip() or len(value['instructions']) > 8000:
        raise refuse()
    return value


class ProfilePreparation(ProjectPreparation):
    def __init__(self, parent):
        self.runtime, self.managed = parent.runtime, parent.managed
        self.repository, self.lock = parent.repository, parent.lock
        self.runner_factory = parent.runner_factory

    def configuration(self):
        setup = self.runtime.setup
        if setup is None:
            raise refuse('configuration')
        if setup.legacy:
            from my_harness.services.configuration_import import imported
            with Session(self.runtime.engine) as session:
                if not imported(session):
                    raise refuse('configuration')
        return setup.repository

    def _source(self, session, project, body):
        current = session.get(Project, project.id)
        if not current or current.status != 'ACTIVE' or current.version != body['expected_version']:
            raise refuse('stale')
        config = self.configuration()
        scope = 'project:' + project.id
        state = config.read(scope)
        ref = state['saved']
        if (state['status'] not in ('UNCONFIGURED', 'READY') or not ref
                or ref['status'] != 'VALIDATED'
                or ref['revision'] != body['configuration_revision'] or ref['sha256'] != body['configuration_sha256']):
            raise refuse('configuration')
        data = parse(config.document(scope, ref['revision']), scope)
        if data['project'] != {'id': project.id, 'root': str(project.context.root)}:
            raise refuse('stale')
        global_state = config.read('global')
        global_ref = global_state['saved'] if self.runtime.setup.legacy else global_state['active']
        if (global_state['status'] not in ('READY', 'UNCONFIGURED') or not global_ref
                or data['global'] != {k: global_ref[k] for k in ('revision', 'sha256')}):
            raise refuse('configuration')
        if data.get('edit') and (state['active'] or data.get('provenance', {}).get('source') == 'legacy-configuration'):
            from my_harness.storage.models import ConfigurationRevisionRow as Revision
            revision = session.get(Revision, (scope, ref['revision']))
            if body['proposal_id'] != revision.operation_id or body['proposal_sha256'] != ref['sha256']:
                raise refuse('stale')
            profile = local_config._profile(data['profile_name'], data['profile'], allow_formatter=True)
            technical = validate_plan(data['edit']['preparation_plan'], profile, project.context)
            documents = data['edit']['documents']
            verify_files(project.context.root, documents)
            payload = {'candidate': {'name': data['profile_name'], 'profile': data['profile'],
                'tools': [{'name': name, 'requirement': 'Confirmed project tool'}
                          for name in data['commands']['executables']]}}
            return data, profile, technical, {'scope': scope, **ref}, data['edit']['head'], documents, payload
        proposal = session.get(Proposal, body['proposal_id'])
        conversation = session.get(Conversation, proposal.conversation_id) if proposal else None
        from my_harness.core.engine.definition import text_hash
        if (not proposal or not conversation or conversation.root != current.root or proposal.kind != 'profile'
                or proposal.status != 'ACCEPTED' or proposal.proposal_sha256 != body['proposal_sha256']
                or text_hash(proposal.content) != proposal.content_sha256):
            raise refuse('stale')
        payload = json.loads(proposal.content)
        candidate = payload['candidate']
        if candidate['name'] != data['profile_name'] or candidate['profile'] != data['profile']:
            raise refuse('stale')
        profile = local_config._profile(data['profile_name'], data['profile'], allow_formatter=True)
        if not profile.validations:
            raise refuse()
        technical = validate_plan(candidate.get('preparation_plan'), profile, project.context)
        # A completed documentary operation, P001 and the accepted profile must agree before any preparation.
        documentary = session.scalar(select(Bootstrap).where(Bootstrap.root == current.root, Bootstrap.status == 'COMPLETED'))
        if documentary is None:
            documentary = session.scalar(select(Import).where(Import.root == current.root, Import.status == 'COMPLETED'))
        if (documentary is None or not documentary.result or not documentary.phase_id
                or not session.get(Phase, documentary.phase_id)
                or documentary.preview.get('profile_proposal_sha256') != proposal.proposal_sha256):
            raise refuse('documents')
        # Document hashes may include managed blocks added by the documentary commit; the accepted operation
        # owns these final bytes. No draft or caller-provided boolean can stand in for that commit.
        documents = documentary.result.get('documents')
        if documents is None and isinstance(documentary, Import):
            documents = {entry['path']: entry['sha256'] for entry in documentary.preview['result_tree']}
        if not documents:
            raise refuse('documents')
        verify_files(project.context.root, documents)
        return data, profile, technical, {'scope': scope, **ref}, documentary.result['commit'], documents, payload

    @staticmethod
    def _links(plan, *, discover=None):
        # Absence retains the historical policy; recovery must not opt old plans in.
        frozen = plan.get('read_only_tool_links')
        if frozen is not None:
            verify_tools(plan['tool_files'])
        def permitted(root, key, path):
            if frozen is not None and not matches(key, plan['technical']['local_paths']):
                if plan.get('tool_link_policy') == TOOL_LINK_POLICY:
                    try:
                        evidence = external_tool_link(path, plan['tool_files'], root)
                    except OSError as error:
                        raise ValueError(tr('preparation.unexpected_symlink', key=key)) from error
                else:
                    evidence = tool_link(path, plan['tool_files'])
                if discover is not None:
                    discover[key] = evidence
                    return True
                return frozen.get(key) == evidence
            resolved = path.resolve(strict=True)
            if (matches(key, plan['technical']['local_paths'])
                    and any(str(resolved) == tool['resolved'] for tool in plan['tool_files'].values())):
                return True  # Explicit, byte-bound tool aliases (for example a venv's interpreter).
            patterns = (plan['technical']['environment_paths']
                        if matches(key, plan['technical']['environment_paths']) else plan['technical']['local_paths'])
            return (matches(key, plan['technical']['local_paths']) and resolved.is_relative_to(root)
                    and matches(str(resolved.relative_to(root)), patterns))
        return permitted

    def _agent(self, project):
        return self.runtime.config.ports_factory(project.context, project.versions)[0]

    def preview(self, project_id, body, *, session=None):
        if session is None:
            with Session(self.runtime.engine) as read:
                return self.preview(project_id, body, session=read)
        project = self.runtime.project(project_id)
        data, profile, technical, ref, documentary_commit, documents, proposal = self._source(session, project, body)
        previous_id = body.get('previous_id')
        self._idle(session, str(project.context.root), previous=previous_id)
        if body['mode'] == 'offline' and technical['network']:
            raise refuse('network')
        if body['mode'] == 'network' and not technical['network']:
            raise refuse('network')
        root = project.context.root
        writer, git = self.writer(project)
        commands = local_config._commands(data['commands'], 'commands', root, profile, strict=True)
        environment = dict(commands.environment)
        # Home/temp/cache writes must stay in the confirmed private checkout area.
        for name in ('HOME', 'TMPDIR'):
            value = environment.get(name)
            if not value or not Path(value).is_absolute() or not Path(value).is_relative_to(root):
                raise refuse('scope')
            relative = str(Path(value).relative_to(root))
            if not matches(relative + '/placeholder', technical['local_paths']):
                raise refuse('scope')
        def confined_environment(values):
            for name, value in values.items():
                if name in ('HOME', 'TMPDIR') or 'CACHE' in name.upper():
                    path = Path(value)
                    if (not path.is_absolute() or path.resolve() != path or not path.is_relative_to(root)
                            or not matches(str(path.relative_to(root)) + '/placeholder', technical['local_paths'])):
                        raise refuse('scope')
        confined_environment(environment)
        for command in profile.preparation + profile.validations:
            confined_environment(dict(command.environment))
        for path in technical['local_paths']:
            base = path.removesuffix('/**')
            if (git.run('ls-files', '--', base).strip()
                    or git.code('check-ignore', '--no-index', '--', base + '/placeholder') != 0
                    and '.gitignore' not in technical['write_paths']):
                raise refuse('scope')
        tools = {name: {'path': path, 'resolved': str(Path(path).resolve(strict=True)),
                        'sha256': file_hash(Path(path).resolve(strict=True))} for name, path in commands.executables}
        agent = self._agent(project)
        agent_versions = agent.frozen_versions()
        steps = [{'kind': 'directories', 'paths': [str(Path(environment[k]).relative_to(root)) for k in ('HOME', 'TMPDIR')]}]
        steps.append({'kind': 'executor', 'selection': technical['executor_selection'],
                      'instructions': technical['instructions'], 'write_paths': technical['write_paths']})
        for kind, declarations in (('preparation', profile.preparation), ('validation', profile.validations)):
            for index, command in enumerate(declarations):
                # Command environment is merged explicitly by the native runner; it cannot escape the confirmed home/temp.
                effective = {**environment, **dict(command.environment)}
                if any(effective.get(k) != environment[k] for k in ('HOME', 'TMPDIR')):
                    raise refuse('scope')
                steps.append({'kind': 'command', 'stage': kind, 'index': index, 'command': asdict(command),
                    'executables': dict(commands.executables), 'environment': environment,
                    'max_timeout_seconds': commands.max_timeout_seconds, 'max_output_bytes': commands.max_output_bytes,
                    'binding': PreparationCommandRunner(commands).frozen_versions(),
                    'network': technical['network'], 'scripts': technical['scripts']})
        steps.append({'kind': 'commit'})
        dependency_inputs = []
        for dep in technical['dependencies']:
            path = project.context.path(dep['lock_path'])
            current_hash = file_hash(path) if path.exists() else None
            if current_hash != dep['sha256'] and dep['lock_path'] not in technical['write_paths']:
                raise refuse('scope')
            dependency_inputs.append({**dep, 'base_sha256': current_hash})
        with directory(root) as fd:
            info = identity(os.fstat(fd))
        plan = {'contract': CONTRACT, 'recipe': None, 'project_id': project.id, 'root': str(root),
                'identity': info, 'versions': dict(project.versions), 'expected_version': body['expected_version'],
                'configuration': ref, 'configuration_data': data, 'technical': technical,
                'proposal_id': body['proposal_id'], 'proposal_sha256': body['proposal_sha256'],
                'profile_proposal': proposal,
                'agent_versions': agent_versions, 'tool_files': tools, 'steps': steps, 'mode': body['mode'],
                'dependency_inputs': dependency_inputs,
                'documentary_commit': documentary_commit, 'base_files': documents,
                'work_language': project.context.work_language,
                'commit': {'message': 'harness: prepare project profile', 'author_name': writer.identity.name,
                           'author_email': writer.identity.email},
                'files': [{'path': path, 'effect': 'may create or modify'} for path in technical['write_paths']]}
        # A linked recovery keeps the original policy/evidence, including old plans.
        if previous_id:
            previous = self.repository.require(session, previous_id)
            if 'read_only_tool_links' in previous.plan:
                plan['read_only_tool_links'] = previous.plan['read_only_tool_links']
            if 'tool_link_policy' in previous.plan:
                plan['tool_link_policy'] = previous.plan['tool_link_policy']
            workspace = snapshot(root, self._links(plan))
        else:
            plan['tool_link_policy'] = TOOL_LINK_POLICY
            plan['read_only_tool_links'] = {}
            workspace = snapshot(root, self._links(plan, discover=plan['read_only_tool_links']))
            if any(matches(p, profile.protected_paths) for p in plan['read_only_tool_links']):
                raise refuse('scope')
        captured = writer.capture(project.context)
        trees = json.loads(captured.provenance_json)
        if previous_id:
            previous = self.repository.require(session, previous_id)
            if (previous.project_id != project_id or previous.plan['contract'] != CONTRACT
                    or previous.status not in ('FAILED', 'CANCELLED', 'RECOVERY_REQUIRED')):
                raise refuse('recovery')
            self.repository.stopped(session, previous)
            old = previous.plan
            if any(plan[k] != old[k] for k in ('configuration', 'technical', 'versions', 'agent_versions', 'tool_files', 'identity')):
                raise refuse('stale')
            steps_done = list(session.scalars(select(Step).where(Step.operation_id == previous_id).order_by(Step.number)))
            first = next((s.number for s in steps_done if s.status != 'DONE'), len(steps_done) - 1)
            if body.get('retry_step') != first:
                raise refuse('recovery')
            # An uncertain step cannot authorize its own partial effects. Only the exact completed prefix is reusable.
            expected = steps_done[first - 1].evidence['workspace'] if first else old['initial_workspace']
            if workspace != expected:
                raise refuse('recovery')
            pending = previous.commit_intent
            if captured.base_revision not in {old['base_head'], pending['expected_commit'] if pending else old['base_head']}:
                raise refuse('stale')
            self._git_guard(root, git, old, pending)
            plan = {**old, 'recovery': {'previous_id': previous_id, 'previous_version': previous.version,
                                      'retry_step': first, 'workspace': workspace}, 'inherited_commit': pending}
            plan.pop('preview_sha256', None)
        else:
            latest = self.latest(project_id, session)
            if (latest and (latest.status != 'COMPLETED' or latest.plan.get('configuration') == ref)
                    or body.get('retry_step') is not None):
                raise refuse('recovery')
            if captured.changed_paths or trees['base_tree'] != trees['index_tree'] or captured.base_revision != documentary_commit:
                raise refuse('documents')
            plan.update(base_head=captured.base_revision, base_tree=trees['base_tree'], initial_workspace=workspace,
                        git_controls=git_controls(root), refs=refs(git), head_ref=trees['head_ref'])
        return {**plan, 'preview_sha256': digest(plan)}

    def _check(self, row, project, expected_workspace):
        plan, root = row['plan'], project.context.root
        if digest(plan) != row['plan_sha256'] or plan['contract'] != CONTRACT:
            raise refuse('stale')
        if len(row['steps']) != len(plan['steps']) or any(s['spec'] != plan['steps'][n] or s['number'] != n
                                                       for n, s in enumerate(row['steps'])):
            raise refuse('stale')
        with Session(self.runtime.engine) as session:
            self._source(session, project, {**plan, 'configuration_revision': plan['configuration']['revision'],
                                          'configuration_sha256': plan['configuration']['sha256']})
        if dict(project.versions) != plan['versions'] or self._agent(project).frozen_versions() != plan['agent_versions']:
            raise refuse('stale')
        with directory(root) as fd:
            if identity(os.fstat(fd)) != plan['identity']:
                raise refuse('stale')
        verify_tools(plan['tool_files'])
        _, git = self.writer(project)
        pending = plan.get('inherited_commit')
        if git.text('rev-parse', 'HEAD') not in {plan['base_head'], pending['expected_commit'] if pending else plan['base_head']}:
            raise refuse('stale')
        index = self.writer(project)[0]._index_tree(git)
        if index not in {plan['base_tree'], pending['tree'] if pending else plan['base_tree']}:
            raise refuse('stale')
        self._git_guard(root, git, plan, pending)
        if snapshot(root, self._links(plan)) != expected_workspace:
            raise refuse('scope')

    def _scope(self, root, plan, before):
        after = snapshot(root, self._links(plan))
        for path in before.keys() | after.keys():
            if before.get(path) == after.get(path):
                continue
            if path in plan.get('read_only_tool_links', {}):
                raise refuse('scope')
            # New parent directories are harmless only if they lead to an explicitly granted file/prefix.
            if after.get(path, {}).get('directory') and any(p.startswith(path + '/') for p in plan['technical']['write_paths']):
                continue
            if not matches(path, plan['technical']['write_paths']):
                raise refuse('scope')
        verify_files(root, plan['base_files'])
        writer, git = self.writer(self.runtime.project(plan['project_id']))
        if git.text('rev-parse', 'HEAD') != plan['base_head'] or writer._index_tree(git) != plan['base_tree']:
            raise refuse('scope')
        self._git_guard(root, git, plan)
        return after

    @staticmethod
    def _git_guard(root, git, plan, pending=None):
        current = refs(git)
        expected = dict(plan['refs'])
        allowed = [expected]
        if pending:
            allowed.append({**expected, plan['head_ref']: pending['expected_commit']})
        if git_controls(root) != plan['git_controls'] or current not in allowed:
            raise refuse('scope')

    def _execute_step(self, operation_id, token, project, plan, step):
        root, spec = project.context.root, step['spec']
        before = snapshot(root, self._links(plan))
        journal = PreparationJournal(self.repository, operation_id, token)
        kind = spec['kind']
        evidence = {}
        if kind == 'directories':
            for path in spec['paths']:
                project.context.path(path).mkdir(parents=True, mode=0o700, exist_ok=True)
        elif kind == 'executor':
            adapter = self._agent(project)
            bound = PreparationAgentJournal(self.repository, operation_id, token)
            adapter.bind_preparation(bound, plan['agent_versions'])
            # The executor needs technical inputs, not the private editor document/agent environments or
            # a potentially huge workspace hash inventory. Those remain in the service's confirmed journal.
            inputs = {'contract': CONTRACT, 'base_head': plan['base_head'], 'technical': plan['technical'],
                      'profile': plan['configuration_data']['profile'], 'dependencies': plan['dependency_inputs'],
                      'tools': plan['profile_proposal']['candidate']['tools'],
                      'private_directories': plan['steps'][0]['paths'],
                      'commands': [s['command'] for s in plan['steps'] if s['kind'] == 'command']}
            request = AgentRequest(step['id'], 'executor', executor_selection(project.context, spec['selection']),
                'Prepare only the confirmed technical scope. Do not run commands, installers, Git or network; '
                'the harness runs the exact commands afterward. Never edit documentation or user configuration.\n'
                + freeze(inputs),
                freeze({'allowed_paths': spec['write_paths'], 'forbidden_paths': ['.git/**'],
                        'executor_prompt': spec['instructions']}), context_snapshot(project.context))
            try:
                result = adapter.invoke(project.context, request)
            finally:
                adapter.close()
            if (result.error or not result.terminal_observed or result.exit_code != 0
                    or result.status not in (None, 'complete') or not result.payload_json):
                raise refuse('executor')
            payload = json.loads(result.payload_json)
            if not isinstance(payload, dict) or not isinstance(payload.get('result'), str):
                raise refuse('executor')
            evidence = {'request': asdict(request), 'result': asdict(result)}
        elif kind == 'command':
            for dependency in plan['technical']['dependencies']:
                verify_files(root, {dependency['lock_path']: dependency['sha256']})
            profile = local_config._profile(plan['configuration_data']['profile_name'],
                                            plan['configuration_data']['profile'], allow_formatter=True)
            config = local_config._commands(plan['configuration_data']['commands'], 'commands', root, profile, strict=True)
            command = (profile.preparation if spec['stage'] == 'preparation' else profile.validations)[spec['index']]
            declaration = next((d for d in profile.junit_reports if d.command == command), None)
            previous_report = observe_report(project.context, declaration.path) if declaration else None
            runner = self.runner_factory(config)
            runner.bind_preparation(journal, spec['binding'])
            result = runner.run_managed(project.context, command, step['id'])
            if result.error or result.timed_out or result.exit_code != 0:
                raise refuse('command')
            evidence = {'result': asdict(result)}
            if declaration:
                report = capture_junit(project.context, declaration, previous_report)
                if (report.status != 'complete' or not any(c.result == 'passed' for c in report.cases)
                        or report.freshness not in ('changed', 'created')
                        or any(c.result not in ('passed', 'skipped') for c in report.cases)):
                    raise refuse('command')
                evidence['junit'] = asdict(report)
        elif kind == 'commit':
            return {}, self._commit(operation_id, token, project, plan)
        else:
            raise refuse()
        self._scope(root, plan, before)
        return evidence, None

    def _commit(self, operation_id, token, project, plan):
        root = project.context.root
        for dependency in plan['technical']['dependencies']:
            verify_files(root, {dependency['lock_path']: dependency['sha256']})
        writer, git = self.writer(project)
        with Session(self.runtime.engine) as session:
            pending = self.repository.require(session, operation_id).commit_intent
        if pending is None:
            self._scope(root, plan, plan['initial_workspace'])
            workspace = snapshot(root, self._links(plan))
            for path in plan['technical']['local_paths']:
                base = path.removesuffix('/**')
                if git.code('check-ignore', '--no-index', '--', base + '/placeholder') != 0:
                    raise refuse('scope')
            for path, value in workspace.items():
                if ('sha256' in value and value != plan['initial_workspace'].get(path)
                        and not matches(path, plan['technical']['local_paths'])
                        and git.code('check-ignore', '--no-index', '--', path) == 0):
                    raise refuse('scope')
            captured = writer.capture(project.context)
            trees = json.loads(captured.provenance_json)
            if any(not matches(p, plan['technical']['write_paths']) for p in captured.changed_paths):
                raise refuse('scope')
            if matches_any_model(captured.changed_paths, plan):
                raise refuse('scope')
            tree = trees['worktree_tree']
            timestamp = int(self.managed.clock().timestamp())
            message = plan['commit']['message'] + '\n\nHarness-Preparation: ' + operation_id + '\n'
            raw = writer._commit_text(tree, plan['base_head'], message, plan['commit']['author_name'],
                                     plan['commit']['author_email'], timestamp)
            pending = {'base_head': plan['base_head'], 'base_tree': plan['base_tree'], 'tree': tree,
                       'expected_commit': (git.text('hash-object', '-t', 'commit', '--stdin', input=raw)
                                           if tree != plan['base_tree'] else plan['base_head']),
                       'message': message, 'timestamp': timestamp, 'changed': tree != plan['base_tree']}
            with self.managed._write() as session:
                row = self.repository.owned(session, operation_id, token)
                row.commit_intent = pending
                self.repository.event(session, row, 'commit_intended', pending)
        raw = writer._commit_text(pending['tree'], pending['base_head'], pending['message'],
                                 plan['commit']['author_name'], plan['commit']['author_email'], pending['timestamp'])
        head, index = git.text('rev-parse', 'HEAD'), writer._index_tree(git)
        self._git_guard(root, git, plan, pending)
        captured = writer.capture(project.context)
        if json.loads(captured.provenance_json)['worktree_tree'] != pending['tree']:
            raise refuse('stale')
        if pending['changed'] and git.text('hash-object', '-t', 'commit', '--stdin', input=raw) != pending['expected_commit']:
            raise refuse('stale')
        if head == pending['base_head'] and pending['changed']:
            if index != pending['base_tree']:
                raise refuse('stale')
            git.run('hash-object', '-t', 'commit', '-w', '--stdin', input=raw)
            git.run('update-ref', '-m', 'harness: prepare project profile', 'HEAD', pending['expected_commit'], head)
        elif head != pending['expected_commit']:
            raise refuse('stale')
        if index == pending['base_tree']:
            git.run('read-tree', '--reset', pending['tree'])
        elif index != pending['tree']:
            raise refuse('stale')
        if writer.capture(project.context).changed_paths:
            raise refuse('stale')
        workspace = snapshot(root, self._links(plan))
        profile = local_config._profile(plan['configuration_data']['profile_name'], plan['configuration_data']['profile'],
                                       allow_formatter=True)
        if any('link' in v and matches(p, profile.protected_paths) for p, v in workspace.items()):
            raise refuse('scope')
        protected = {p: v['sha256'] for p, v in workspace.items() if 'sha256' in v and matches(p, profile.protected_paths)}
        with Session(self.runtime.engine) as session:
            results = [{'number': s.number, 'spec': s.spec, 'evidence': s.evidence}
                       for s in session.scalars(select(Step).where(Step.operation_id == operation_id,
                                                                 Step.number < len(plan['steps']) - 1).order_by(Step.number))]
            if any(r['evidence'] is None for r in results):
                raise refuse('recovery')
        receipt = {'contract': CONTRACT, 'recipe': None, 'operation_id': operation_id,
                   'plan_sha256': digest(plan), 'configuration': plan['configuration'],
                   'technical_sha256': digest({'profile': plan['configuration_data']['profile'],
                                              'commands': plan['configuration_data']['commands']}),
                   'proposal_sha256': plan['proposal_sha256'], 'versions': plan['versions'],
                   'identity': plan['identity'], 'prepared_head': plan['base_head'], 'commit': pending['expected_commit'],
                   'protected_files': protected, 'protected_paths': list(profile.protected_paths),
                   'tools': plan['tool_files'], 'local_paths': plan['technical']['local_paths'],
                   'environment_paths': plan['technical']['environment_paths'],
                   'environment': environment_entries(workspace, plan['technical']['environment_paths']),
                   'work_language': plan['work_language'], 'results': results}
        if 'read_only_tool_links' in plan:
            receipt['read_only_tool_links'] = plan['read_only_tool_links']
        if 'tool_link_policy' in plan:
            receipt['tool_link_policy'] = plan['tool_link_policy']
        return receipt

    def bind(self, project):
        # T009 owns activation and executable runtime composition. A receipt alone grants neither.
        return project

    def verify_configuration(self, project, receipt, *, active=False, reference=None, global_reference=None):
        """Service-side activation/admission building block; never trusts a caller's ready flag.

        Explicit references verify a staged live set (D238) against its own candidate revisions."""
        if receipt.get('contract') != CONTRACT:
            raise refuse('configuration')
        config = self.configuration()
        state = config.read('project:' + project.id)
        ref = reference or (state['active'] if active else state['saved'])
        if state['status'] not in ('READY', 'UNCONFIGURED', 'APPLY_PENDING') or not ref:
            raise refuse('configuration')
        data = parse(config.document(state['scope'], ref['revision']), state['scope'])
        from my_harness.services.configuration_editing import prepared
        from my_harness.storage.configuration import ConfigurationConflict
        try:
            with Session(self.runtime.engine) as session:
                if prepared(session, state['scope'], data, reference=ref).receipt != receipt:
                    raise refuse('configuration')
        except ConfigurationConflict:
            raise refuse('configuration') from None
        global_state = config.read('global')
        global_ref = global_reference or (global_state['saved'] if self.runtime.setup.legacy else global_state['active'])
        if (global_state['status'] not in ('READY', 'UNCONFIGURED', 'APPLY_PENDING') or not global_ref
                or data['global'] != {k: global_ref[k] for k in ('revision', 'sha256')}):
            raise refuse('configuration')
        verify_profile_receipt(project.context.root, receipt)


def matches_any_model(paths, plan):
    return any(matches(p, plan['configuration_data']['profile']['data_model_paths']) for p in paths)


def verify_profile_receipt(root, receipt):
    from my_harness.adapters.preparation import same_directory
    with directory(root) as fd:
        if not same_directory(identity(os.fstat(fd)), receipt['identity']):
            raise refuse('stale')
    verify_tools(receipt['tools'])
    verify_files(root, receipt['protected_files'])
    # Complete path-set verification catches newly added protected files as well as changed/deleted ones.
    plan = {'technical': {'local_paths': receipt['local_paths'], 'environment_paths': receipt['environment_paths']},
            'tool_files': receipt['tools']}
    if 'read_only_tool_links' in receipt:
        plan['read_only_tool_links'] = receipt['read_only_tool_links']
    if 'tool_link_policy' in receipt:
        plan['tool_link_policy'] = receipt['tool_link_policy']
    workspace = snapshot(root, ProfilePreparation._links(plan))
    if any(p not in workspace or 'link' not in workspace[p] for p in receipt.get('read_only_tool_links', {})):
        raise refuse('stale')
    if any('link' in v and matches(p, receipt['protected_paths']) for p, v in workspace.items()):
        raise refuse('stale')
    protected = {p: v['sha256'] for p, v in workspace.items() if 'sha256' in v and matches(p, receipt['protected_paths'])}
    local = environment_entries(workspace, receipt['environment_paths'])
    def normalized(entries):
        return {p: ({'directory': {'inode': v['directory']['inode']}} if 'directory' in v else v)
                for p, v in entries.items()}
    if protected != receipt['protected_files'] or normalized(local) != normalized(receipt['environment']):
        raise refuse('stale')
