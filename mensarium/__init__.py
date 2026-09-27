import os, sys, importlib
# Ensure the bundled src directory is on sys.path so that imports like "src.agent_core" work.
_this_dir = os.path.abspath(os.path.dirname(__file__))
src_path = os.path.join(_this_dir, "src")
if src_path not in sys.path:
    sys.path.append(src_path)

# Load the actual package from src and expose it under the "mensarium" namespace.
# This allows code that expects "mensarium.agent_core" etc. to work without moving files.
try:
    agent_core_mod = importlib.import_module('agent_core')
    sys.modules[__name__ + '.agent_core'] = agent_core_mod
    # expose subpackages similarly (profiles, contracts, core, etc.)
    for sub in ['profiles', 'contracts', 'core', 'llm_providers', 'plugins', 'policy_engine', 'shared', 'skills', 'tool_runtime', 'web', 'channels', 'cli', 'client']:
        try:
            mod = importlib.import_module(sub)
            sys.modules[__name__ + f'.{sub}'] = mod
        except Exception:
            pass
except Exception as e:
    # If loading fails, we simply continue; imports will raise later.
    pass
