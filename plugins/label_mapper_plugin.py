from core.node_base import BasePlugin
from rx.subject import BehaviorSubject

class LabelMapperPlugin(BasePlugin):
    name = "LabelMapper"
    category = "Custom"

    def setup(self):
        # value: n'importe quel type (int/bool/str)
        self.inputs = {
            "value": BehaviorSubject(None),
            "left_value": BehaviorSubject(0),   # adapte selon ton SyntheticLR
            "right_value": BehaviorSubject(1),  # adapte selon ton SyntheticLR
        }
        self.outputs = {
            "label": BehaviorSubject("center"),
        }

    def execute(self):
        v  = self.inputs["value"].value
        lv = self.inputs["left_value"].value
        rv = self.inputs["right_value"].value
        if v == lv:
            self.outputs["label"].on_next("left")
        elif v == rv:
            self.outputs["label"].on_next("right")
        else:
            self.outputs["label"].on_next("center")
