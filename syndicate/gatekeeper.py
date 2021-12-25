from .schema import gatekeeper
from .during import During
from . import turn

# decorator
def resolve(gk, cap, *args, **kwargs):
    def configure_handler(handler):
        def unwrapping_handler(wrapped_ref):
            return handler(wrapped_ref.embeddedValue)
        return _resolve(gk, cap)(During(*args, **kwargs).add_handler(unwrapping_handler))
    return configure_handler

# decorator
def _resolve(gk, cap):
    def publish_resolution_request(entity):
        turn.publish(gk, gatekeeper.Resolve(cap, turn.ref(entity)))
        return entity
    return publish_resolution_request
