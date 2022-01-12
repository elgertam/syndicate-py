from .schema import dataspacePatterns as P
from . import Symbol, Record
from preserves import preserve

_dict = dict  ## we're about to shadow the builtin

_ = P.Pattern.DDiscard(P.DDiscard())

def bind(p):
    return P.Pattern.DBind(P.DBind(p))

CAPTURE = bind(_)

class unquote:
    def __init__(self, pattern):
        self.pattern = pattern

uCAPTURE = unquote(CAPTURE)
u_ = unquote(_)

# Given
#
#   Run = <run @name string @input any @output any>
#
# then these all produce the same pattern:
#
# P.rec('Observe', P.quote(P.rec('run', P.lit('N'), P.unquote(P.CAPTURE), P.bind(P.unquote(P._)))), P._)
#
# P.rec('Observe', P.quote(P.quote(Run('N', P.unquote(P.uCAPTURE), P.unquote(P.bind(P.u_))))), P._)
#
# P.quote(Record(Symbol('Observe'),
#                [P.quote(Run('N', P.unquote(P.uCAPTURE), P.unquote(P.bind(P.u_)))),
#                 P.u_]))

# Simple, stupid single-level quasiquotation.
def quote(p):
    if isinstance(p, unquote):
        return p.pattern
    p = preserve(p)
    if isinstance(p, list) or isinstance(p, tuple):
        return arr(*map(quote, p))
    elif isinstance(p, set) or isinstance(p, frozenset):
        raise Exception('Cannot represent literal set in dataspace pattern')
    elif isinstance(p, _dict):
        return dict(*((k, quote(pp)) for (k, pp) in p.items()))
    elif isinstance(p, Record):
        return _rec(p.key, *map(quote, p.fields))
    else:
        return P.Pattern.DLit(P.DLit(P.AnyAtom.decode(p)))

def lit(v):
    if isinstance(v, list) or isinstance(v, tuple):
        return arr(*map(lit, v))
    elif isinstance(v, set) or isinstance(v, frozenset):
        raise Exception('Cannot represent literal set in dataspace pattern')
    elif isinstance(v, _dict):
        return dict(*((k, lit(vv)) for (k, vv) in v.items()))
    elif isinstance(v, Record):
        return _rec(v.key, *map(lit, v.fields))
    else:
        return P.Pattern.DLit(P.DLit(P.AnyAtom.decode(v)))

def rec(labelstr, *members):
    return _rec(Symbol(labelstr), *members)

def _rec(label, *members):
    return P.Pattern.DCompound(P.DCompound.rec(label, members))

def arr(*members):
    return P.Pattern.DCompound(P.DCompound.arr(members))

def dict(*kvs):
    return P.Pattern.DCompound(P.DCompound.dict(_dict(kvs)))
