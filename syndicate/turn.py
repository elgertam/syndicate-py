from .actor import Turn

def __setup():
    from .actor import _active
    from types import FunctionType
    import sys

    mod = sys.modules[__name__]

    def install_definition(name, definition):
        def handler(*args, **kwargs):
            return definition(_active.turn, *args, **kwargs)
        setattr(mod, name, handler)

    for (name, definition) in Turn.__dict__.items():
        if name[0] == '_':
            continue
        elif type(definition) == FunctionType:
            install_definition(name, definition)
        else:
            pass

__setup()

def run(facet, action):
    Turn.run(facet, action)

def external(facet, action, loop=None):
    Turn.external(facet, action, loop=loop)

def active_facet():
    return Turn.active._facet
