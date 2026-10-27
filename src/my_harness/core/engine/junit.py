"""Bounded JUnit: observed bytes, never acceptance authority or active XML."""

import base64
from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
import stat
from xml.etree.ElementTree import Element, TreeBuilder
from xml.parsers import expat

from my_harness.core.engine.context import JUnitDeclaration, ProjectContext, relative_path

MAX_BYTES = 2 * 1024 * 1024
MAX_CASES = 2000
MAX_ELEMENTS = 30000
MAX_DEPTH = 64


@dataclass(frozen=True)
class TestCase:
    id: str  # Stable fingerprint of the observed identity + ordinal among duplicates.
    reported_id: str | None
    name: str | None
    classname: str | None
    suite: tuple[str | None, ...]
    result: str
    duration_seconds: float | None
    message: str | None
    error_type: str | None
    error: str | None


@dataclass(frozen=True)
class JUnitReport:
    path: str
    coverage: str
    status: str
    diagnostics: tuple[str, ...] = ()
    sha256: str | None = None
    size_bytes: int | None = None
    original_base64: str | None = None
    freshness: str = 'unknown'
    cases: tuple[TestCase, ...] = ()


@dataclass(frozen=True)
class ReportObservation:
    data: bytes | None
    signature: tuple | None
    status: str
    diagnostic: str | None = None


def observe_report(context: ProjectContext, path: str) -> ReportObservation:
    """Walks descriptors without following links or opening special files.

    Never deletes an earlier report. O_NONBLOCK avoids blocking on a FIFO.
    Rejects hard links: does not attribute files shared outside the checkout.
    """
    descriptors = []
    try:
        parts = relative_path(path).parts
        if not parts or '.git' in parts:
            raise ValueError('Report path must be a checkout file outside .git')
        directory = os.open(context.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(directory)
        for part in parts[:-1]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            descriptors.append(directory)
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError('Report must be a regular, unshared file without links')
        if before.st_size > MAX_BYTES:
            return ReportObservation(None, None, 'limit', f'Report exceeds {MAX_BYTES} bytes; not retained')
        with os.fdopen(os.dup(descriptor), 'rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        after = os.fstat(descriptor)
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        # Also verifies that the name was not replaced during the read.
        named = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        if signature(before) != signature(after) or signature(after) != signature(named) or len(data) != after.st_size:
            return ReportObservation(None, None, 'unreadable', 'Report changed during capture; bytes not attributed')
        if len(data) > MAX_BYTES:
            return ReportObservation(None, None, 'limit', f'Report exceeds {MAX_BYTES} bytes; not retained')
        digest = hashlib.sha256(data).hexdigest()
        return ReportObservation(data, (*signature(after), digest), 'observed')
    except FileNotFoundError:
        return ReportObservation(None, None, 'missing', 'Declared report is absent')
    except (OSError, ValueError) as exc:
        return ReportObservation(None, None, 'unreadable', f'Cannot safely read declared report: {exc}')
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def parse_junit(data: bytes, declaration: JUnitDeclaration) -> JUnitReport:
    report = JUnitReport(declaration.path, declaration.coverage, 'invalid')
    if len(data) > MAX_BYTES:
        return replace(report, status='limit', diagnostics=(f'Report exceeds {MAX_BYTES} bytes; not retained',))
    report = replace(report, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
                     original_base64=base64.b64encode(data).decode('ascii'))
    builder = TreeBuilder()
    stack: list[Element] = []
    completed: list[tuple[Element, tuple[str | None, ...]]] = []
    suites: list[Element] = []
    diagnostics = []
    elements = 0
    root = None

    def reject(*args):
        raise ValueError('DTD, entity declarations and external entities are forbidden')

    def start(tag, attributes):
        nonlocal elements, root
        elements += 1
        if elements > MAX_ELEMENTS or len(stack) >= MAX_DEPTH:
            raise ValueError('XML element/depth limit exceeded')
        if root is None and tag not in ('testsuite', 'testsuites'):
            raise ValueError('Expected testsuite or testsuites root')
        if tag == 'testcase' and (not stack or stack[-1].tag not in ('testsuite', 'testsuites')):
            raise ValueError('Testcase must be a direct child of a suite container')
        if tag in ('testsuite', 'testsuites') and stack and stack[-1].tag not in ('testsuite', 'testsuites'):
            raise ValueError('Invalid suite hierarchy')
        node = builder.start(tag, attributes)
        root = root if root is not None else node
        stack.append(node)

    def end(tag):
        node = builder.end(tag)
        if tag == 'testcase':
            if len(completed) >= MAX_CASES:
                raise ValueError('XML testcase limit exceeded')
            completed.append((node, tuple(s.get('name') for s in stack[:-1] if s.tag == 'testsuite')))
        if tag in ('testsuite', 'testsuites'):
            suites.append(node)
        stack.pop()

    parser = expat.ParserCreate()
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = reject
    parser.EntityDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        diagnostics.append(f'XML incomplete or malformed: {exc}')
    except (ValueError, LookupError) as exc:
        # Unsafe/incompatible structure: keeps the original, attributes no cases.
        return replace(report, diagnostics=(str(exc),))

    cases = []
    identities: dict[str, int] = {}

    def duration(value):
        if value is None:
            return None
        try:
            number = float(value)
            if not math.isfinite(number) or number < 0:
                raise ValueError
            return number
        except ValueError:
            diagnostics.append(f'Invalid observed duration: {value!r}')
            return None

    for node, suite in completed:
        markers = [child for child in node if child.tag in ('failure', 'error', 'skipped')]
        identity = json.dumps([suite, node.get('classname'), node.get('name'), node.get('id')], ensure_ascii=False)
        ordinal = identities.get(identity, 0)
        identities[identity] = ordinal + 1
        identifier = hashlib.sha256(f'{identity}:{ordinal}'.encode()).hexdigest()
        result = {'failure': 'failed', 'error': 'error', 'skipped': 'skipped'}.get(markers[0].tag) if len(markers) == 1 else 'passed'
        if not node.get('name') or len(markers) > 1 or any(child.tag not in
                ('failure', 'error', 'skipped', 'system-out', 'system-err', 'properties') for child in node):
            result = 'unknown'
            diagnostics.append('Case has absent identity, contradictory or unsupported result markers')
        if node.get('status') not in (None, 'run', 'passed', 'success') and not markers:
            result = 'unknown'
            diagnostics.append('Case reports absent or unsupported execution status')
        marker = markers[0] if len(markers) == 1 else None
        cases.append(TestCase(identifier, node.get('id'), node.get('name'), node.get('classname'), suite,
                              result, duration(node.get('time')), marker.get('message') if marker is not None else None,
                              marker.get('type') if marker is not None else None,
                              ''.join(marker.itertext()) if marker is not None else None))

    for suite in suites:
        descendants = list(suite.iter('testcase'))
        for field, marker in (('tests', None), ('failures', 'failure'), ('errors', 'error'), ('skipped', 'skipped')):
            value = suite.get(field)
            if value is None:
                continue
            observed = len(descendants) if marker is None else sum(any(c.tag == marker for c in node) for node in descendants)
            if not value.isascii() or not value.isdecimal() or (value.lstrip('0') or '0') != str(observed):
                diagnostics.append(f'Declared {field}={value!r} differs from observed cases in suite {suite.get("name")!r}')
    if not cases:
        diagnostics.append('No completed testcases observed; no test success inferred')
    # Avoids amplifying responses with thousands of identical diagnostics.
    diagnostics = tuple(dict.fromkeys(diagnostics))[:100]
    status = 'partial' if diagnostics and cases else 'invalid' if diagnostics and root is None else 'partial' if diagnostics else 'complete'
    return replace(report, status=status, diagnostics=diagnostics, cases=tuple(cases))


def capture_junit(context, declaration, before: ReportObservation) -> JUnitReport:
    after = observe_report(context, declaration.path)
    if after.data is None:
        return JUnitReport(declaration.path, declaration.coverage, after.status, (after.diagnostic,))
    report = parse_junit(after.data, declaration)
    if before.signature == after.signature:
        return replace(report, status='stale', freshness='unchanged',
                       diagnostics=report.diagnostics + ('Report unchanged during command; current execution is unproven',))
    if before.status not in ('observed', 'missing'):
        return replace(report, freshness='unknown', diagnostics=report.diagnostics +
                       ('Pre-command capture unavailable; freshness is unknown',))
    return replace(report, freshness='changed' if before.signature else 'created')
