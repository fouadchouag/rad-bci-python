# tests/conftest.py — Mock heavy deps so tests can run without PyQt5/rx
import sys, types


class MockModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        mock = MockModule(f"{self.__name__}.{name}")
        setattr(self, name, mock)
        sys.modules[f"{self.__name__}.{name}"] = mock
        return mock
    def __call__(self, *a, **kw):
        return self
    def __bool__(self):
        return True
    def __iter__(self):
        return iter([])
    def __add__(self, other):
        return 0
    def __radd__(self, other):
        return 0


_MOCK = [
    'PyQt5', 'PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui',
    'sip',
    'rx', 'rx.subject', 'rx.scheduler',
    'core', 'core.node_base', 'core.plugin_registry', 'core.ui_kit', 'core.collapsible',
    'lsl', 'pylsl',
]

for mod_name in _MOCK:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MockModule(mod_name)

# Set up core.node_base.BasePlugin properly so subclasses work
_bp = types.ModuleType('core.node_base')
class BasePlugin:
    def __init__(self):
        self.inputs = {}
        self.outputs = {}
    def setup(self):
        pass
_bp.BasePlugin = BasePlugin
sys.modules['core.node_base'] = _bp
sys.modules['core'].__dict__['node_base'] = _bp

# Make BehaviorSubject store values
class BehaviorSubject:
    def __init__(self, initial=None):
        self._value = initial
    def on_next(self, val):
        self._value = val
    def on_completed(self):
        pass
    def on_error(self, e):
        pass
    @property
    def value(self):
        return self._value
sys.modules['rx.subject'].BehaviorSubject = BehaviorSubject
sys.modules['rx'].subject = sys.modules['rx.subject']
