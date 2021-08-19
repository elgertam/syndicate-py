from .schema import dataspace
from .during import During

# decorator
def observe(turn, ds, pattern):
    def publish_observer(entity):
        turn.publish(ds, dataspace.Observe(pattern, turn.ref(entity)))
        return entity
    return publish_observer

# decorator
def on_message(turn, ds, pattern):
    return lambda on_msg: observe(turn, ds, pattern)(During().msg_handler(on_msg))

# decorator
def during(turn, ds, pattern):
    return lambda on_add: observe(turn, ds, pattern)(During().add_handler(on_add))
