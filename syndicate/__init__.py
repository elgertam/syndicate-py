__path__ = __import__('pkgutil').extend_path(__path__, __name__)

# This is 'import *' in order to effectively re-export preserves as part of this module's API.
from preserves import *

def __setup():
    from .actor import _active, Turn
    from .metapy import staticproperty
    from types import FunctionType
    import sys

    class turn:
        @staticproperty
        def active():
            t = getattr(_active, 'turn', False)
            if t is False:
                t = _active.turn = None
            return t

        @staticproperty
        def log():
            return turn.active.log

        def run(facet, action):
            return Turn.run(facet, action)

        def external(facet, action, loop=None):
            return Turn.external(facet, action, loop=loop)

        def active_facet():
            return turn.active._facet

    def install_definition(name, definition):
        def handler(*args, **kwargs):
            return definition(turn.active, *args, **kwargs)
        setattr(turn, name, handler)

    for (name, definition) in Turn.__dict__.items():
        if name[0] == '_':
            continue
        elif type(definition) == FunctionType:
            install_definition(name, definition)
        else:
            pass

    return turn

turn = __setup()

from . import relay
