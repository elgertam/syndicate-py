from .schema import dataspace
from .during import During
from . import turn

# decorator
def observe(ds, pattern):
    def publish_observer(entity):
        turn.publish(ds, dataspace.Observe(pattern, turn.ref(entity)))
        return entity
    return publish_observer

# decorator
def on_message(ds, pattern, *args, **kwargs):
    return lambda on_msg: observe(ds, pattern)(During(*args, **kwargs).msg_handler(on_msg))

# decorator
def during(ds, pattern, *args, **kwargs):
    return lambda on_add: observe(ds, pattern)(During(*args, **kwargs).add_handler(on_add))
