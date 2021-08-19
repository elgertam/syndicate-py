from . import actor

def _ignore(*args, **kwargs):
    pass

def _default_sync(turn, peer):
    turn.send(peer, True)

class During(actor.Entity):
    def __init__(self, on_add=None, on_msg=None, on_sync=None, name=None, inert_ok=False):
        self.facets = {}
        self._on_add = on_add or _ignore
        self._on_msg = on_msg or _ignore
        self._on_sync = on_sync or _default_sync
        self.name = name
        self.inert_ok = inert_ok
        self.flatten_arg = True

    def __repr__(self):
        if self.name is None:
            return super().__repr__()
        return self.name

    def _wrap(self, v):
        return v if self.flatten_arg and isinstance(v, tuple) else (v,)

    def on_publish(self, turn, v, handle):
        facet = turn.facet(lambda turn: self._on_add(turn, *self._wrap(v)))
        if self.inert_ok:
            facet.prevent_inert_check()
        self.facets[handle] = facet

    def on_retract(self, turn, handle):
        facet = self.facets.pop(handle, None)
        if facet is not None:
            turn.stop(facet)

    def on_message(self, turn, v):
        self._on_msg(turn, *self._wrap(v))

    def on_sync(self, turn, peer):
        self._on_sync(turn, peer)

    # decorator
    def add_handler(self, on_add):
        self._on_add = on_add
        return self

    # decorator
    def msg_handler(self, on_msg):
        self._on_msg = on_msg
        return self

    # decorator
    def sync_handler(self, on_sync):
        self._on_sync = on_sync
        return self
