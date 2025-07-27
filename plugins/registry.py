from plugins.constant import ConstantPlugin
from plugins.adder import AdderPlugin
from plugins.signal_logger import SignalLoggerPlugin
from plugins.eeg_reader_plugin import EEGReaderPlugin
from plugins.eeg_visualizer_plugin import EEGVisualizerPlugin
from plugins.eeg_filter_plugin import EEGFilterPlugin

PLUGIN_REGISTRY = [
    ConstantPlugin,
    AdderPlugin,
    SignalLoggerPlugin,
    EEGReaderPlugin,
    EEGFilterPlugin,
    EEGVisualizerPlugin
]
