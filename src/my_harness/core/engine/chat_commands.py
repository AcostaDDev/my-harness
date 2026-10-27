"""Closed syntax: a leading slash is never implicitly sent to a model.

Command names are Spanish protocol tokens (P011-T010/T021): they are never translated.
"""
from my_harness.i18n import message, tr

COMMANDS = ('estado', 'tests', 'siguiente', 'lote', 'check', 'cerrar', 'exportar', 'abrir-fase', 'tarea')


def parse(text):
    text = text.strip()
    if not text.startswith('/'):
        return None
    parts = text.split(maxsplit=1)
    name = parts[0][1:]
    argument = parts[1].strip() if len(parts) == 2 else ''
    if name not in COMMANDS or (name == 'tarea') != bool(argument):
        raise ValueError(tr('chat.command_invalid', commands=', '.join('/' + name for name in COMMANDS[:-1])))
    if len(argument) > 4000:
        raise ValueError(tr('chat.command_length'))
    return {'name': name, 'argument': argument}


def proposal(argument, work_language=None):
    """The answer follows the visual language; the proposed task's own text, the work language (D169)."""
    return {'answer': tr('chat.proposal_answer'),
            'references': [], 'proposals': [{'title': argument[:200], 'objective': argument, 'scope': '',
                'acceptance_criteria': [argument], 'validation': [],
                'rationale': message('chat.proposal_rationale', work_language)}]}
