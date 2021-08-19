from . import actor

def _ignore(*args, **kwargs):
    pass

def _default_sync(turn, peer):
    turn.send(peer, True)

class During(actor.Entity):
    def __init__(self, turn, on_add=None, on_msg=None, on_sync=None, name=None):
        self.ref = turn.ref(self)
        self.retract_handlers = {}
        self._on_add = on_add or _ignore
        self._on_msg = on_msg or _ignore
        self._on_sync = on_sync or _default_sync
        self.name = name
        self.flatten_arg = True

    def __repr__(self):
        if self.name is None:
            return super().__repr__()
        return self.name

    def _wrap(self, v):
        return v if self.flatten_arg and isinstance(v, tuple) else (v,)

    def on_publish(self, turn, v, handle):
        retract_handler = self._on_add(turn, *self._wrap(v))
        if retract_handler is not None:
            if isinstance(retract_handler, actor.Facet):
                self.retract_handlers[handle] = lambda turn: turn.stop(retract_handler)
            else:
                self.retract_handlers[handle] = retract_handler

    def on_retract(self, turn, handle):
        self.retract_handlers.pop(handle, lambda turn: ())(turn)

    def on_message(self, turn, v):
        self._on_msg(turn, *self._wrap(v))

    def on_sync(self, turn, peer):
        self._on_sync(turn, peer)
