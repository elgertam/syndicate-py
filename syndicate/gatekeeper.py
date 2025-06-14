from .schema import rpc, gatekeeper
from .during import During
from . import turn

# decorator
def resolve(gk, cap, *args, **kwargs):
    def configure_handler(handler):
        def unwrapping_handler(r):
            resolved = rpc.Result.decode(r)
            if resolved.VARIANT.name == 'Ok':
                return handler(resolved.value.value.embeddedValue)
            raise Exception('Could not resolve reference: ' + repr(resolved))
        return _resolve(gk, cap)(During(*args, **kwargs).add_handler(unwrapping_handler))
    return configure_handler

# decorator
def _resolve(gk, cap):
    def publish_resolution_request(entity):
        turn.publish(gk, gatekeeper.Resolve(cap, turn.ref(entity)))
        return entity
    return publish_resolution_request
