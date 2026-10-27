"""P011-T009 (D169): vocabulary of the documents My Harness generates, in the project's work language.

Deterministic texts only (managed blocks, D088 template, archive and acceptance records): no translation of free
values, paths, markers, codes or statuses. The Spanish entries are the historical bytes: a context frozen before
D167 carries no work language and keeps generating them, so its blocks still compare byte for byte. The parsers
read both vocabularies (`planning.FIELD_NAMES`, `documents.ROADMAP_FIELDS`, D088 aliases).
"""

LANGUAGES = ('en', 'es')
HISTORICAL = 'es'


def work_language(context) -> str:
    """Work language of a frozen context; earlier contexts (no value) keep the historical Spanish documents."""
    value = getattr(context, 'work_language', None)
    if value is None:
        return HISTORICAL
    if value not in LANGUAGES:
        raise ValueError('The work language must be en or es')
    return value


def words(language: str) -> dict[str, str]:
    if language not in WORDS:
        raise ValueError('The work language must be en or es')
    return WORDS[language]


WORDS = {
    'es': {
        'truncated': ' … (recortado; texto completo en el historial de SQLite)',
        'skipped': ' · {count} omitidos',
        'commands': 'comandos {passed}/{total} OK',
        'open_questions': '**Preguntas abiertas:**',
        'none_f': '- ninguna',
        'none_m': '- ninguno',
        'no_active_phase': '**Fase activa:** ninguna (roadmap completado o sin instalar).',
        'phase_line': '**Fase:** {code} · estado {status}',
        'objective': '**Objetivo:**',
        'exit_criteria': '**Criterios de salida:**',
        'state_header': 'Estado gestionado por My Harness desde SQLite (D072). No editar dentro de este bloque.',
        'state_table': '| Tarea | Estado | Revisión | Commit | Tests |',
        'this_commit': 'este commit',
        'no_tasks': 'sin tareas',
        'executor_summaries': '**Resumen del ejecutor por tarea:**',
        'no_reasons': 'sin motivos registrados',
        'latest_check': '**Último check:**',
        'plan_header': 'Estado del plan gestionado por My Harness desde SQLite (D072). No editar dentro de este bloque.',
        'next_task': '**Siguiente tarea:** ',
        'no_next_task': 'ninguna; todas tienen commit aceptado',
        'plan_table': '| Tarea | Estado | Commit |',
        'pending': 'pendiente',
        'extra_tasks': '**Tareas añadidas fuera del plan:**',
        'roadmap_header': ('Estado de las fases gestionado por My Harness desde SQLite (D072). '
                           'No editar dentro de este bloque.'),
        'roadmap_table': '| Fase | Título | Estado | Tag |',
        'archive_column': ' Archivo |',
        'archive_link': 'archivo',
        'completed': 'completada',
        'no_phases': 'sin fases',
        'decisions_header': ('Índice generado por My Harness desde los encabezados de este archivo (D088). '
                             'No editar dentro de este bloque.'),
        'decisions_table': '| Decisión | Título | Estado |',
        'no_decisions': 'sin decisiones',
        'review_title': '# Evaluación de cierre de {code}',
        'review_note': 'Generado por My Harness desde SQLite al archivar la fase (D072). Instantánea inmutable.',
        'review_without_ready': 'La fase terminó como {status} sin un check READY que habilitara el cierre.',
        'review_latest': 'Último check registrado: {status}.',
        'review_verdict': '**Veredicto:** {status} · **HEAD evaluado:** {head} · **Vínculo READY:** {binding}',
        'review_summary': '**Resumen del revisor:** {summary}',
        'exit_criteria_heading': '## Criterios de salida',
        'criteria_table': '| Criterio | Cumplido | Evidencia |',
        'yes': 'sí',
        'no': 'no',
        'baseline_validation': '**Validación de base:** {passed}/{total} comandos con salida 0.',
        'summary_title': '# Resumen de la fase {code}',
        'summary_note': ('Generado por My Harness desde SQLite al archivar la fase (D072). Instantánea inmutable: '
                         'la autoridad operativa sigue en SQLite.'),
        'title': '**Título:** {title}',
        'final_status': '**Estado final:** {status} · **Tag:** ',
        'definition_version': ' · **Definición:** versión {number}',
        'tasks_heading': '## Tareas',
        'summary_table': '| Tarea | Estado | Revisión | Intentos por rol | Correcciones | Commit | Tests |',
        'consumption_columns': ' Tokens | Turnos |',
        'no_run': 'sin run',
        'extra_heading': '## Tareas añadidas fuera del plan',
        'extra_item': '- {task}: {status}, commit {commit}',
        'questions_heading': '## Preguntas',
        'definitions_heading': '## Definición y enmiendas',
        'definition_item': '- Versión {number} ({origin})',
        'consumption_heading': '## Consumo',
        'consumption_note': ('Tokens reportados por el proveedor o derivados del uso por mensaje, sin sumar acumulados '
                             'con incrementales; «—» es ausencia, no cero. Turnos reportados (Claude) y derivados '
                             '(elementos de Codex) por separado. Coste equivalente API reportado: no es factura ni '
                             'cuota. Excluye el chat.'),
        'consumption_table': ('| Rol | Intentos | Entrada sin caché | Caché leída | Caché escrita | Salida | Total '
                              '| Turnos | Coste equivalente API (USD) |'),
        'review_link': 'Evaluación de cierre: [REVIEW.md](REVIEW.md).',
        'attempts_coverage': ' ({covered}/{attempts} intentos)',
        'reported': 'reportados',
        'derived': 'derivados',
        'command_omitted': '# (comando omitido: contiene tres acentos graves seguidos; ver el perfil)',
        'more_commands': '# … y {count} más declarados en el perfil',
        'first_phase': 'Primera fase',
        'state_title': '# Estado',
        'next_plan_pending': '\nPendiente de planificación confirmada.\n',
        'roadmap_finished': ('# Sin fase activa\n\nEl roadmap no tiene más fases después de {code}. Añade una fase '
                             'en ROADMAP y su plan aquí mediante una edición confirmada.\n'),
        'empty_baseline': '## Base acumulada\n\nTodavía no hay trabajo aceptado.\n',
        'active_heading': '## Fase activa — {code} {title}\n\nSin notas todavía.\n',
        'no_active_heading': '## Fase activa\n\nSin fase activa: roadmap completado.\n',
        'definition_title': '# Definición del proyecto',
        'definition_note': ('Generado por My Harness desde SQLite al aceptar la definición (D072). Instantánea '
                            'inmutable: la conversación completa sigue en SQLite.'),
        'definition_conversation': '**Conversación:** `{id}` · **Título:** {title}',
        'definition_turns': '## Turnos',
        'turns_table': '| Turno | Estado | Mensaje | Respuesta | Borradores propuestos |',
        'no_turns': 'sin turnos',
        'drafts_heading': '## Borradores aplicados y ediciones',
        'draft_proposal': 'propuesta {proposal} del turno {turn}',
        'draft_edit': 'edición del usuario por API',
        'no_drafts': '- ninguno (borradores escritos solo por el usuario)',
        'last_questions': '## Preguntas del último turno',
        'deferred': 'aplazada: ',
        'blocking': 'bloqueante',
        'non_blocking': 'no bloqueante',
        'last_pending': '## Pendientes declarados en el último turno',
        'accepted_documents': '## Documentos aceptados',
        'documents_table': '| Documento | SHA-256 | Origen |',
        'origin_draft': 'borrador',
        'origin_draft_blocks': 'borrador con bloques regenerados',
        'origin_template': 'plantilla v2',
        'origin_archive': 'archivo de la definición',
        'absent': 'ausente',
        'onboarding_summary': ('# Incorporación al harness\n\nBase existente documentada; P001 ACTIVE.\n'
                               'Perfil de la composición y documentos sujetos a la confirmación de esta vista '
                               'previa.\n\n'),
        # Labels the agents read in the prompt directive and the reconciliation contract (D088 aliases).
        'baseline_label': '## Base acumulada',
        'active_label': '## Fase activa',
        'status_label': 'Estado:',
    },
    'en': {
        'truncated': ' … (truncated; full text in the SQLite history)',
        'skipped': ' · {count} skipped',
        'commands': 'commands {passed}/{total} OK',
        'open_questions': '**Open questions:**',
        'none_f': '- none',
        'none_m': '- none',
        'no_active_phase': '**Active phase:** none (roadmap completed or not installed).',
        'phase_line': '**Phase:** {code} · status {status}',
        'objective': '**Objective:**',
        'exit_criteria': '**Exit criteria:**',
        'state_header': 'State managed by My Harness from SQLite (D072). Do not edit inside this block.',
        'state_table': '| Task | Status | Review | Commit | Tests |',
        'this_commit': 'this commit',
        'no_tasks': 'no tasks',
        'executor_summaries': '**Executor summary by task:**',
        'no_reasons': 'no recorded reasons',
        'latest_check': '**Latest check:**',
        'plan_header': 'Plan status managed by My Harness from SQLite (D072). Do not edit inside this block.',
        'next_task': '**Next task:** ',
        'no_next_task': 'none; every task has an accepted commit',
        'plan_table': '| Task | Status | Commit |',
        'pending': 'pending',
        'extra_tasks': '**Tasks added outside the plan:**',
        'roadmap_header': 'Phase status managed by My Harness from SQLite (D072). Do not edit inside this block.',
        'roadmap_table': '| Phase | Title | Status | Tag |',
        'archive_column': ' Archive |',
        'archive_link': 'archive',
        'completed': 'completed',
        'no_phases': 'no phases',
        'decisions_header': ('Index generated by My Harness from the headings of this file (D088). '
                             'Do not edit inside this block.'),
        'decisions_table': '| Decision | Title | Status |',
        'no_decisions': 'no decisions',
        'review_title': '# Closure review of {code}',
        'review_note': 'Generated by My Harness from SQLite when the phase was archived (D072). Immutable snapshot.',
        'review_without_ready': 'The phase ended as {status} without a READY check enabling its closure.',
        'review_latest': 'Latest recorded check: {status}.',
        'review_verdict': '**Verdict:** {status} · **Evaluated HEAD:** {head} · **READY binding:** {binding}',
        'review_summary': '**Reviewer summary:** {summary}',
        'exit_criteria_heading': '## Exit criteria',
        'criteria_table': '| Criterion | Met | Evidence |',
        'yes': 'yes',
        'no': 'no',
        'baseline_validation': '**Baseline validation:** {passed}/{total} commands exited with 0.',
        'summary_title': '# Phase {code} summary',
        'summary_note': ('Generated by My Harness from SQLite when the phase was archived (D072). Immutable '
                         'snapshot: operational authority stays in SQLite.'),
        'title': '**Title:** {title}',
        'final_status': '**Final status:** {status} · **Tag:** ',
        'definition_version': ' · **Definition:** version {number}',
        'tasks_heading': '## Tasks',
        'summary_table': '| Task | Status | Review | Attempts by role | Corrections | Commit | Tests |',
        'consumption_columns': ' Tokens | Turns |',
        'no_run': 'no run',
        'extra_heading': '## Tasks added outside the plan',
        'extra_item': '- {task}: {status}, commit {commit}',
        'questions_heading': '## Questions',
        'definitions_heading': '## Definition and amendments',
        'definition_item': '- Version {number} ({origin})',
        'consumption_heading': '## Consumption',
        'consumption_note': ('Tokens reported by the provider or derived from per-message usage, never adding '
                             'cumulative and incremental counts; «—» means absent, not zero. Reported turns (Claude) '
                             'and derived turns (Codex items) are kept apart. Reported API-equivalent cost: neither an '
                             'invoice nor a quota. Chat is excluded.'),
        'consumption_table': ('| Role | Attempts | Uncached input | Cache read | Cache write | Output | Total '
                              '| Turns | API-equivalent cost (USD) |'),
        'review_link': 'Closure review: [REVIEW.md](REVIEW.md).',
        'attempts_coverage': ' ({covered}/{attempts} attempts)',
        'reported': 'reported',
        'derived': 'derived',
        'command_omitted': '# (command omitted: it contains three consecutive backticks; see the profile)',
        'more_commands': '# … and {count} more declared in the profile',
        'first_phase': 'First phase',
        'state_title': '# State',
        'next_plan_pending': '\nPending a confirmed plan.\n',
        'roadmap_finished': ('# No active phase\n\nThe roadmap has no phase after {code}. Add a phase to ROADMAP and '
                             'its plan here through a confirmed edit.\n'),
        'empty_baseline': '## Accumulated baseline\n\nNo accepted work yet.\n',
        'active_heading': '## Active phase — {code} {title}\n\nNo notes yet.\n',
        'no_active_heading': '## Active phase\n\nNo active phase: roadmap completed.\n',
        'definition_title': '# Project definition',
        'definition_note': ('Generated by My Harness from SQLite when the definition was accepted (D072). '
                            'Immutable snapshot: the whole conversation stays in SQLite.'),
        'definition_conversation': '**Conversation:** `{id}` · **Title:** {title}',
        'definition_turns': '## Turns',
        'turns_table': '| Turn | Status | Message | Answer | Proposed drafts |',
        'no_turns': 'no turns',
        'drafts_heading': '## Applied drafts and edits',
        'draft_proposal': 'proposal {proposal} of turn {turn}',
        'draft_edit': 'user edit through the API',
        'no_drafts': '- none (drafts written only by the user)',
        'last_questions': '## Questions of the last turn',
        'deferred': 'deferred: ',
        'blocking': 'blocking',
        'non_blocking': 'non-blocking',
        'last_pending': '## Pending items declared in the last turn',
        'accepted_documents': '## Accepted documents',
        'documents_table': '| Document | SHA-256 | Origin |',
        'origin_draft': 'draft',
        'origin_draft_blocks': 'draft with regenerated blocks',
        'origin_template': 'v2 template',
        'origin_archive': 'definition archive',
        'absent': 'absent',
        'onboarding_summary': ('# Harness onboarding\n\nExisting baseline documented; P001 ACTIVE.\n'
                               'Composition profile and documents subject to the confirmation of this preview.\n\n'),
        'baseline_label': '## Accumulated baseline',
        'active_label': '## Active phase',
        'status_label': 'Status:',
    },
}

STATUS_LABELS = {
    'es': {None: 'pendiente', 'ACTIVE': 'activa', 'CLOSED': 'cerrada', 'ABANDONED': 'abandonada',
           'CHECKING': 'en check', 'CLOSING': 'cerrándose', 'READY_TO_CLOSE': 'lista para cerrar',
           'NEEDS_RECONCILIATION': 'requiere reconciliación', 'BLOCKED': 'bloqueada'},
    'en': {None: 'pending', 'ACTIVE': 'active', 'CLOSED': 'closed', 'ABANDONED': 'abandoned',
           'CHECKING': 'checking', 'CLOSING': 'closing', 'READY_TO_CLOSE': 'ready to close',
           'NEEDS_RECONCILIATION': 'needs reconciliation', 'BLOCKED': 'blocked'},
}

# D088 template (`documents.skeleton`). Placeholders are layout paths, the escaped title and the managed markers.
AGENTS = {
    'es': {
        'title': '# {name} — instrucciones para agentes',
        'intro': 'Fuente canónica para agentes; `{claude}` y `{gemini}` la importan. Para personas, `{readme}`.',
        'discovery': '## Discovery al empezar una sesión',
        'steps': ('1. `{state}`: base acumulada y fase activa.',
                  '2. `{next_steps}`: tareas de la fase activa y siguiente tarea.',
                  '3. `{roadmap}`: sección de la fase activa.',
                  '4. `{specification}` y `{architecture}`: solo las secciones que afecten a la tarea.',
                  '5. `{decisions}`: las decisiones que cite la tarea; el índice, para buscar precedentes.',
                  '6. `{ddbb_diagram}` y `{flows_dir}/` si la tarea toca datos o flujos.',
                  '7. `{archive_dir}/` solo cuando un documento lo cite.'),
        'rules': '## Reglas inquebrantables',
        'rule_lines': ('- No inventar fuera de la especificación ni de lo decidido. Ante una incongruencia entre '
                       'documentos, o entre documentos y código, preguntar antes de decidir.',
                       '- Paridad: un cambio de modelos de datos actualiza `{ddbb_diagram}`; un cambio de flujo, '
                       '`{flows_dir}/`, en la misma tarea.',
                       '- STATE, NEXT_STEPS, ROADMAP, DECISIONS y `{archive_dir}/` los mantiene My Harness: una '
                       'tarea normal no los edita.',
                       '- Las decisiones nuevas se proponen en la salida de la tarea; no se escriben en DECISIONS.',
                       '- Artefactos de trabajo de la fase en curso en `{phase_dir}/`.',
                       '- Ningún secreto, credencial ni dato privado en el repositorio.'),
        'commands': '## Comandos',
        'no_commands': 'Sin comandos declarados por el perfil del proyecto.',
        'preparation': 'Preparación',
        'validation': 'Validación (tests, lint y tipos)',
        'wrapper': '# {provider}\n\n@{agents}\n\nNotas para {provider}: ninguna todavía. Las instrucciones comunes '
                   'viven en `{agents}`.\n',
    },
    'en': {
        'title': '# {name} — agent instructions',
        'intro': 'Canonical source for agents; `{claude}` and `{gemini}` import it. For people, `{readme}`.',
        'discovery': '## Discovery at the start of a session',
        'steps': ('1. `{state}`: accumulated baseline and active phase.',
                  '2. `{next_steps}`: tasks of the active phase and the next task.',
                  '3. `{roadmap}`: section of the active phase.',
                  '4. `{specification}` and `{architecture}`: only the sections that affect the task.',
                  '5. `{decisions}`: the decisions the task cites; the index, to look for precedents.',
                  '6. `{ddbb_diagram}` and `{flows_dir}/` when the task touches data or flows.',
                  '7. `{archive_dir}/` only when a document cites it.'),
        'rules': '## Unbreakable rules',
        'rule_lines': ('- Do not invent beyond the specification or what was decided. On an inconsistency between '
                       'documents, or between documents and code, ask before deciding.',
                       '- Parity: a data model change updates `{ddbb_diagram}`; a flow change, `{flows_dir}/`, in '
                       'the same task.',
                       '- STATE, NEXT_STEPS, ROADMAP, DECISIONS and `{archive_dir}/` are maintained by My Harness: '
                       'a normal task does not edit them.',
                       '- New decisions are proposed in the task output; they are not written to DECISIONS.',
                       '- Work artifacts of the current phase go in `{phase_dir}/`.',
                       '- No secrets, credentials or private data in the repository.'),
        'commands': '## Commands',
        'no_commands': 'No commands declared by the project profile.',
        'preparation': 'Preparation',
        'validation': 'Validation (tests, lint and types)',
        'wrapper': '# {provider}\n\n@{agents}\n\nNotes for {provider}: none yet. The common instructions live in '
                   '`{agents}`.\n',
    },
}

SKELETON = {
    'es': {
        'readme': ('# {name}\n\nQué es, para quién y qué problema resuelve.\n\n## Estado\n\n'
                   'Fases y progreso en [ROADMAP]({roadmap}) y [STATE]({state}).\n\n'
                   '## Requisitos\n\n## Instalación\n\n## Uso\n\n## Tests\n\n## Documentación\n\n'
                   '- [Especificación]({specification})\n- [Arquitectura]({architecture})\n'
                   '- [Diagrama de datos]({ddbb_diagram})\n- [Decisiones]({decisions})\n'
                   '- Instrucciones para agentes: [AGENTS]({agents})\n'),
        'specification': ('# Especificación — {name}\n\n## Problema\n\n## Usuarios\n\n## Alcance\n\n'
                          '## Requisitos\n\n## Reglas de negocio\n\n## Fuera de alcance\n'),
        'architecture': ('# Arquitectura — {name}\n\n## Stack\n\n## Componentes\n\n## Flujos\n\n'
                         'Diagramas por módulo o funcionalidad en `flows/`.\n\n## Persistencia\n\n'
                         'Esquema en [DDBB-DIAGRAM](DDBB-DIAGRAM.md).\n\n## Límites\n'),
        'roadmap': ('# Roadmap — {name}\n\n{road_begin}\n{road_end}\n\n## P001 — {first}\n\n'
                    '**Objetivo:** Definir el objetivo verificable de la fase.\n**Criterios de salida:**\n'
                    '- Criterio observable de salida.\n'),
        'decisions': ('# Decisiones — {name}\n\nRegistro único: una sección por decisión con el encabezado '
                      '`DNNN — título` de nivel 2 y una primera línea `Estado:` (propuesta, aceptada, '
                      'sustituida por DMMM o rechazada). Las decisiones no se borran: se sustituyen. El índice '
                      'lo genera My Harness.\n\n{dec_begin}\n{dec_end}\n'),
        'ddbb_diagram': ('# Diagrama de datos — {name}\n\nSin persistencia.\n\nCuando el proyecto tenga '
                         'modelos de datos, este documento recoge su esquema en Mermaid `erDiagram`.\n'),
        'state': ('# Estado — {name}\n\n{state_begin}\n{state_end}\n\n## Base acumulada\n\n'
                  'Todavía no hay trabajo aceptado.\n\n'
                  '## Fase activa — P001 {first}\n\nSin notas todavía.\n'),
        'next_steps': ('# P001 — {first}\n\nObjetivo y criterios de salida en [ROADMAP](ROADMAP.md).\n\n'
                       '{state_begin}\n{state_end}\n\n## Restricciones compartidas\n\n'
                       '## P001-T001 — Primera tarea\n\n**Objetivo:** Describir el cambio acotado.\n'
                       '**Rutas permitidas:** `src/**`\n**Criterios de aceptación:**\n- Criterio verificable.\n'),
    },
    'en': {
        'readme': ('# {name}\n\nWhat it is, who it is for and which problem it solves.\n\n## Status\n\n'
                   'Phases and progress in [ROADMAP]({roadmap}) and [STATE]({state}).\n\n'
                   '## Requirements\n\n## Installation\n\n## Usage\n\n## Tests\n\n## Documentation\n\n'
                   '- [Specification]({specification})\n- [Architecture]({architecture})\n'
                   '- [Data diagram]({ddbb_diagram})\n- [Decisions]({decisions})\n'
                   '- Agent instructions: [AGENTS]({agents})\n'),
        'specification': ('# Specification — {name}\n\n## Problem\n\n## Users\n\n## Scope\n\n'
                          '## Requirements\n\n## Business rules\n\n## Out of scope\n'),
        'architecture': ('# Architecture — {name}\n\n## Stack\n\n## Components\n\n## Flows\n\n'
                         'Diagrams per module or feature in `flows/`.\n\n## Persistence\n\n'
                         'Schema in [DDBB-DIAGRAM](DDBB-DIAGRAM.md).\n\n## Limits\n'),
        'roadmap': ('# Roadmap — {name}\n\n{road_begin}\n{road_end}\n\n## P001 — {first}\n\n'
                    '**Objective:** Define the verifiable objective of the phase.\n**Exit criteria:**\n'
                    '- Observable exit criterion.\n'),
        'decisions': ('# Decisions — {name}\n\nSingle record: one section per decision with a level-two heading '
                      '`DNNN — title` and a first `Status:` line (proposed, accepted, superseded by DMMM or '
                      'rejected). Decisions are never deleted: they are superseded. My Harness generates the '
                      'index.\n\n{dec_begin}\n{dec_end}\n'),
        'ddbb_diagram': ('# Data diagram — {name}\n\nNo persistence.\n\nWhen the project has data models, this '
                         'document holds their schema as a Mermaid `erDiagram`.\n'),
        'state': ('# State — {name}\n\n{state_begin}\n{state_end}\n\n## Accumulated baseline\n\n'
                  'No accepted work yet.\n\n'
                  '## Active phase — P001 {first}\n\nNo notes yet.\n'),
        'next_steps': ('# P001 — {first}\n\nObjective and exit criteria in [ROADMAP](ROADMAP.md).\n\n'
                       '{state_begin}\n{state_end}\n\n## Shared constraints\n\n'
                       '## P001-T001 — First task\n\n**Objective:** Describe the bounded change.\n'
                       '**Allowed paths:** `src/**`\n**Acceptance criteria:**\n- Verifiable criterion.\n'),
    },
}

# Plan section of a task confirmed from chat (`chat.task_text`). Its historical bytes are English.
CHAT_TASK = {
    'en': {'objective': '**Objective:**', 'scope': '**Scope:**', 'acceptance': '**Acceptance criteria:**',
           'validation': '**Validation:**', 'context': '**Business context:**',
           'references': ('**References:** chat conversation {conversation}, turn {turn}, proposal {proposal} '
                          '(sha256 {sha256})')},
    'es': {'objective': '**Objetivo:**', 'scope': '**Alcance:**', 'acceptance': '**Criterios de aceptación:**',
           'validation': '**Validación:**', 'context': '**Contexto de negocio:**',
           'references': ('**Referencias:** conversación de chat {conversation}, turno {turn}, propuesta '
                          '{proposal} (sha256 {sha256})')},
}
