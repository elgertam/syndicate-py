from .schema import dataspace

# decorator
def observe(turn, ds, pattern):
    def publish_observer(entity):
        turn.publish(ds, dataspace.Observe(pattern, turn.ref(entity)))
        return entity
    return publish_observer
