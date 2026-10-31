from career_agent.config import load_settings
from career_agent.runtime import create_agent_runtime


_runtime = None


def graph(config: object | None = None):
    global _runtime

    if _runtime is None:
        _runtime = create_agent_runtime(load_settings())

    return _runtime[1]
