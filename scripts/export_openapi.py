"""Export contracts without starting the service, connecting to SQLite or running simulations."""
import json
from pathlib import Path

from my_harness.api.app import create_app


if __name__ == "__main__":
    target = Path("frontend/openapi.json")
    target.write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n")
    print(target)
