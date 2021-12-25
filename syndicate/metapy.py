class staticproperty:
    """For use as @staticproperty, like @property, but for static properties of classes.
    Read-only for now."""
    def __init__(self, getter):
        self.getter = getter
    def __get__(self, inst, cls=None):
        return self.getter()

class classproperty:
    """For use as @classproperty, like @property, but for class-side properties of classes.
    Read-only for now."""
    def __init__(self, getter):
        self.getter = getter
    def __get__(self, inst, cls=None):
        return self.getter(cls)
