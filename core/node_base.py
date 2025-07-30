from abc import ABC, abstractmethod
from rx.subject import BehaviorSubject

class BasePlugin(ABC):
    def __init__(self):
        self.inputs = {}   # str → BehaviorSubject
        self.outputs = {}  # str → BehaviorSubject
        self._values = {}  # cache local pour les entrées

        self.setup()

    @abstractmethod
    def setup(self):
        """Initialise self.inputs et self.outputs (avec BehaviorSubject)."""
        pass

    @abstractmethod
    def execute(self, **kwargs):
        """Retourne un dict : {"out1": value1}"""
        pass

    def set_input(self, pin_name, value):
        print(f"[DEBUG] {self.name}.set_input({pin_name}, {value})")

        self._values[pin_name] = value
        try:
            print(f"[DEBUG] {self.name}.execute({self._values})")

            result = self.execute(**self._values)  # ✅ Ne saute pas si une entrée est None
            for out_name, out_value in result.items():
                self.outputs[out_name].on_next(out_value)
        except Exception as e:
            print(f"[ERROR] Execution failed in {self.name}: {e}")


    def get_output(self, name):
        return self.outputs.get(name, None)

    def cleanup(self):
        """Nettoie les abonnements."""
        for s in self.inputs.values():
            s.on_completed()
        for s in self.outputs.values():
            s.on_completed()
