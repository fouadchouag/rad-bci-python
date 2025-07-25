from plugins.constant import ConstantPlugin
from plugins.adder import AdderPlugin
from plugins.eeg_reader import EEGReaderPlugin
from plugins.signal_logger import SignalLoggerPlugin

PLUGIN_REGISTRY = {
    "Constant": ConstantPlugin,
    "Adder": AdderPlugin,
    "EEG Reader": EEGReaderPlugin,
    "Signal Logger": SignalLoggerPlugin,
}
