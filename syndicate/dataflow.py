from . import mapset

class Graph:
    def __init__(self):
        self.edges_forward = {}
        self.edges_reverse = {}
        self.damaged_nodes = set()
        self.active_subject = None

    def with_subject(self, subject_id, f):
        old_subject = self.active_subject
        self.active_subject = subject_id
        try:
            return f()
        finally:
            self.active_subject = old_subject

    def record_observation(self, object_id):
        if self.active_subject is not None:
            mapset.add(self.edges_forward, object_id, self.active_subject)
            mapset.add(self.edges_reverse, self.active_subject, object_id)

    def record_damage(self, object_id):
        self.damaged_nodes.add(object_id)

    def forget_subject(self, subject_id):
        for oid in self.edges_reverse.pop(subject_id, set()):
            mapset.discard(self.edges_forward, oid, subject_id)

    def observers_of(self, object_id):
        return list(self.edges_forward.get(object_id, []))

    def repair_damage(self, repair_fn):
        repaired_this_round = set()
        while True:
            workset = self.damaged_nodes - repaired_this_round
            self.damaged_nodes = set()

            if not workset:
                break

            repaired_this_round = repaired_this_round | workset

            for object_id in workset:
                for subject_id in self.observers_of(object_id):
                    self.forget_subject(subject_id)
                    self.with_subject(subject_id, lambda: repair_fn(subject_id))

__nextFieldId = 0

class Field:
    def __init__(self, graph, initial=None, name=None):
        global __nextFieldId
        self.id = name
        if self.id is None:
            self.id = str(__nextFieldId)
            __nextFieldId = __nextFieldId + 1
        self.graph = graph
        self._value = initial

    @property
    def value(self):
        self.graph.record_observation(self)
        return self._value

    @value.setter
    def value(self, new_value):
        if self._value != new_value:
            self.graph.record_damage(self)
            self._value = new_value

    @property
    def update(self):
        self.graph.record_damage(self)
        return self.value

    def changed(self):
        self.graph.record_damage(self)
