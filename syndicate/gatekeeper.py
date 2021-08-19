from .schema import gatekeeper
from .during import During

# decorator
def resolve(turn, gk, cap, *args, **kwargs):
    def configure_handler(handler):
        def unwrapping_handler(turn, wrapped_ref):
            return handler(turn, wrapped_ref.embeddedValue)
        return _resolve(turn, gk, cap)(During(*args, **kwargs).add_handler(unwrapping_handler))
    return configure_handler

# decorator
def _resolve(turn, gk, cap):
    def publish_resolution_request(entity):
        turn.publish(gk, gatekeeper.Resolve(cap, turn.ref(entity)))
        return entity
    return publish_resolution_request
