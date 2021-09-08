from . import actor

def _ignore(*args, **kwargs):
    pass

def _default_sync(turn, peer):
    turn.send(peer, True)

class Handler(actor.Entity):
    def __init__(self, on_add=None, on_msg=None, on_sync=None, name=None, inert_ok=True):
        self.retraction_handlers = {}
        self._on_add = self._wrap_add_handler(on_add) or _ignore
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

    def _wrap_add_handler(self, handler):
        return handler

    def on_publish(self, turn, v, handle):
        retraction_handler = self._on_add(turn, *self._wrap(v))
        if retraction_handler is not None:
            self.retraction_handlers[handle] = retraction_handler

    def on_retract(self, turn, handle):
        retraction_handler = self.retraction_handlers.pop(handle, None)
        if retraction_handler is not None:
            retraction_handler(turn)

    def on_message(self, turn, v):
        self._on_msg(turn, *self._wrap(v))

    def on_sync(self, turn, peer):
        self._on_sync(turn, peer)

    # decorator
    def add_handler(self, on_add):
        self._on_add = self._wrap_add_handler(on_add)
        return self

    # decorator
    def msg_handler(self, on_msg):
        self._on_msg = on_msg
        return self

    # decorator
    def sync_handler(self, on_sync):
        self._on_sync = on_sync
        return self

class During(Handler):
    def _wrap_add_handler(self, handler):
        def facet_handler(turn, *args):
            @turn.facet
            def facet(turn):
                if self.inert_ok:
                    turn.prevent_inert_check()
                maybe_stop_action = handler(turn, *args)
                if maybe_stop_action is not None:
                    turn.on_stop(maybe_stop_action)
            return lambda turn: turn.stop(facet)
        return facet_handler
