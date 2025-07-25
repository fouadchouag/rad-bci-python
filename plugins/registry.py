from plugins.constant import ConstantPlugin
from plugins.adder import AdderPlugin
from plugins.signal_logger import SignalLoggerPlugin
from plugins.eeg_reader import EEGReaderPlugin

PLUGIN_REGISTRY = [
    ConstantPlugin,
    AdderPlugin,
    SignalLoggerPlugin,
    EEGReaderPlugin,
]
