#!/usr/bin/env python3
"""Wrapper to run generate_node_catalog.py with fully dynamic mocked deps."""
import sys, types, importlib.util

class MockModule(types.ModuleType):
    """Module that returns a mock for any attribute access/import."""
    def __getattr__(self, name):
        # Return a new mock sub-module or a dummy class
        if name.startswith('_'):
            raise AttributeError(name)
        mock = MockModule(f"{self.__name__}.{name}")
        setattr(self, name, mock)
        sys.modules[f"{self.__name__}.{name}"] = mock
        return mock
    def __call__(self, *args, **kwargs):
        return self
    def __iter__(self):
        return iter([])

# Mock all external deps
_MOCK_MODULES = [
    'rx', 'rx.subject', 'rx.scheduler', 'rx.core', 'rx.core.observable',
    'PyQt5', 'PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtSvg',
    'sip',
    'core', 'core.node_base', 'core.plugin_registry', 'core.ui_kit', 'core.collapsible',
    'lsl', 'mne', 'numpy', 'scipy', 'sklearn', 'pyriemann', 'pyriemann.utils',
    'pyriemann.utils.distance', 'pyriemann.utils.mean',
    'requests', 'websockets', 'asyncio', 'aiohttp',
    'pylsl', 'serial',
    'matplotlib', 'matplotlib.pyplot', 'matplotlib.figure', 'matplotlib.backends',
    'matplotlib.backends.backend_qt5agg', 'matplotlib.figure',
    'pyqtgraph', 'pyqtgraph as pg',
    'pandas',
]

for mod_name in _MOCK_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MockModule(mod_name)

# Also install a catch-all for any PyQt5.Qt* or core.* sub-imports
_orig_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

def _patched_import(name, *args, **kwargs):
    if name.startswith(('PyQt5', 'rx', 'core.', 'lsl', 'pylsl')):
        if name not in sys.modules:
            sys.modules[name] = MockModule(name)
        return sys.modules[name]
    return _orig_import(name, *args, **kwargs)

__builtins__.__import__ = _patched_import

# Now run the catalog generator
import os
os.environ["DOCS_BUILD"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.generate_node_catalog import main
main()
