class ParamApplier:
    """
    Route les edits vers les bons nœuds et appelle set_param(key, value).
    Assumes graph.find_node(name) et que set_param(...) déclenche le refresh
    ET (idéalement) logge PARAM_CHANGE.
    """
    def __init__(self, graph, bench):
        self.g = graph
        self.bench = bench

    def apply(self, key, value):
        node = None
        if key in ("gain", "band"):
            node = self.g.find_node("EEGFilter")  # adapte aux noms réels
        elif key in ("win_s", "overlap"):
            node = self.g.find_node("LiveDisplay") # si fenêtrage côté display
        else:
            node = self.g.find_node("EEGFilter") or self.g.find_node("LiveDisplay")
        if node:
            node.set_param(key, value)
            # Si set_param n'écrit pas de log :
            # self.bench.log("PARAM_CHANGE", f"{key}={value}")
