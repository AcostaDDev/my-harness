"""H4.2: execution of the confirmed bootstrap; no providers, web, SQLite or stack in the core.

D088: the v1 template (`project-foundation`) is retired; the preview comes from the v2 definition."""
from dataclasses import replace


def execute(context, history, saved, git, journal):
    journal.checkpoint(history, 'bootstrap')
    result = git.execute_bootstrap(context, saved['preview'], saved['intent'])
    return replace(history, status='completed', stop=None), result
