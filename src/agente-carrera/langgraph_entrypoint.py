import sys
from pathlib import Path

MODULE_DIRECTORY = str(Path(__file__).resolve().parent)
if MODULE_DIRECTORY not in sys.path:
    sys.path.insert(0, MODULE_DIRECTORY)

from config import load_settings
from runtime import create_agent_runtime


_runtime = None


def graph(config: object | None = None):
    global _runtime

    if _runtime is None:
        _runtime = create_agent_runtime(load_settings())

    return _runtime[1]
