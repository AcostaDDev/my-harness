"""Synthetic supervisor process, deliberately killed by the H2.3 recovery test."""
import json
from pathlib import Path
import sys

from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter
from my_harness.adapters.engine_fake import ScriptedCommandRunner, SyntheticWorkspace
from my_harness.core.engine.serialization import restore_context
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.database import make_engine
from my_harness.storage.managed import SQLiteManagedRepository


def main():
    url, specification = sys.argv[1:]
    data = json.loads(Path(specification).read_text())
    configs = [CLIConfig(**{**value, 'executable':tuple(value['executable']),
                           'environment':tuple(tuple(pair) for pair in value['environment'])})
               for value in data['configs']]
    port = CLIProcessAdapter(configs, data['artifacts'])
    context = restore_context(data['context'])
    repository = SQLiteManagedRepository(make_engine(url))
    def factory(ctx, versions):
        return port, ScriptedCommandRunner([]), SyntheticWorkspace(context, ('app/main.txt',))
    LocalSupervisor(repository, factory, lease_seconds=.6).run_once()


if __name__ == '__main__':
    main()
