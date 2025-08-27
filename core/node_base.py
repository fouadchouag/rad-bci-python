# core/node_base.py
from abc import ABC, abstractmethod
from rx.subject import BehaviorSubject
import uuid
import traceback

class BasePlugin(ABC):
    def __init__(self):
        # Nom unique lisible dans les logs
        self.name = f"{self.__class__.__name__}_{uuid.uuid4().hex[:6]}"

        # Pins
        self.inputs = {}    # str -> BehaviorSubject (optionnel selon ton framework)
        self.outputs = {}   # str -> BehaviorSubject
        self._values = {}   # cache local des entrées (dernier état connu)

        # Initialisation spécifique au plugin
        self.setup()

    # ---------- à implémenter par les plugins ----------
    @abstractmethod
    def setup(self):
        """Initialise self.inputs et self.outputs (avec BehaviorSubject)."""
        pass

    @abstractmethod
    def execute(self, **kwargs):
        """
        À surcharger.
        Peut être défini de 3 façons compatibles :
          - def execute(self, in_data=None, **kwargs)
          - def execute(self, in_data)
          - def execute(self, **kwargs)
        Doit idéalement retourner un dict {out_pin: value}, ou {}.
        (Si le plugin fait déjà self.outputs['x'].on_next(...), retourner {}.)
        """
        pass

    # ---------- API commune ----------
    def set_input(self, pin_name, value):
        print(f"[DEBUG] {self.name}.set_input({pin_name}, {value})")
        self._values[pin_name] = value

        # On tente plusieurs signatures d'execute() pour supporter anciens & nouveaux plugins
        result = None
        try:
            # 1) Meilleure compat : execute(in_data=vals, **vals)
            print(f"[DEBUG] {self.name}.execute({self._values})  [try in_data=..., **kwargs]")
            result = self.execute(in_data=dict(self._values), **self._values)
        except TypeError:
            try:
                # 2) Plugins "kwargs only" : execute(**vals)
                print(f"[DEBUG] {self.name}.execute(**vals)  [fallback kwargs only]")
                result = self.execute(**self._values)
            except TypeError:
                try:
                    # 3) Plugins "in_data only" : execute(vals)
                    print(f"[DEBUG] {self.name}.execute(in_data)  [fallback single dict arg]")
                    result = self.execute(dict(self._values))
                except TypeError:
                    # 4) Dernière chance : sans arg (certains plugins ne lisent que self._values)
                    print(f"[DEBUG] {self.name}.execute()  [fallback no-args]")
                    result = self.execute()
                except Exception as e:
                    print(f"[ERROR] Execution failed in {self.name} (in_data only): {e}")
                    traceback.print_exc()
                    result = None
            except Exception as e:
                print(f"[ERROR] Execution failed in {self.name} (kwargs only): {e}")
                traceback.print_exc()
                result = None
        except Exception as e:
            print(f"[ERROR] Execution failed in {self.name} (in_data+kwargs): {e}")
            traceback.print_exc()
            result = None

        # Toujours normaliser le résultat -> dict
        if result is None:
            result = {}
        elif not isinstance(result, dict):
            # On ne forçe pas l’émission sauvage si le plugin a choisi un autre retour.
            # On log et on ignore (les plugins émettent souvent via on_next eux-mêmes).
            print(f"[DEBUG] {self.name}: execute() returned a non-dict result, ignoring.")
            result = {}

        # Émettre les sorties retournées explicitement par le plugin (si présentes)
        for out_name, out_value in result.items():
            self._safe_emit(out_name, out_value)

    def _safe_emit(self, out_name, value):
        subj = self.outputs.get(out_name)
        if subj is None:
            # Sortie inconnue -> ignorer pour rester permissif
            print(f"[DEBUG] {self.name}: unknown output pin '{out_name}', ignored.")
            return
        try:
            subj.on_next(value)
        except Exception as e:
            print(f"[ERROR] {self.name}: failed to emit on '{out_name}': {e}")
            traceback.print_exc()

    def get_output(self, name):
        return self.outputs.get(name, None)

    # ---------- cycle de vie ----------
    def cleanup(self):
        """Nettoie les abonnements (appelé par le framework quand nécessaire)."""
        for s in self.inputs.values():
            try:
                s.on_completed()
            except Exception:
                pass
        for s in self.outputs.values():
            try:
                s.on_completed()
            except Exception:
                pass

    # Alias utile (plusieurs plugins appellent on_remove)
    def on_remove(self):
        self.cleanup()
