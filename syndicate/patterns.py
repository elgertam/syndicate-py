from .schema import dataspacePatterns as P
from . import Symbol, Record

_dict = dict  ## we're about to shadow the builtin

_ = P.Pattern.DDiscard(P.DDiscard())

def bind(p):
    return P.Pattern.DBind(P.DBind(p))

CAPTURE = bind(_)

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
