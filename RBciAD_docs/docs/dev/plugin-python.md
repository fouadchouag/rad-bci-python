Writing a Python Plugin

from core.node_base import BasePlugin
from rx.subject import BehaviorSubject


class MyNode(BasePlugin):
category = "Processing"
display_name = "MyNode"


def setup(self):
self.inputs = {"x": BehaviorSubject(None)}
self.outputs = {"y": BehaviorSubject(None)}


def execute(self, in_data: dict, **kwargs):
x = in_data.get("x")
if x is None:
return None