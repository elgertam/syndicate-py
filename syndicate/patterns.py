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

# Simple, stupid single-level quasiquotation.
def quote(p):
    if isinstance(p, unquote):
        return p.pattern
    if p.VARIANT == P.Pattern.DDiscard.VARIANT:
        return lit(preserve(p))
    if p.VARIANT == P.Pattern.DBind.VARIANT:
        return rec('bind', quote(p.value.pattern))
    if p.VARIANT == P.Pattern.DLit.VARIANT:
        return lit(preserve(p))
    if p.VARIANT == P.Pattern.DCompound.VARIANT:
        p = p.value
        if p.VARIANT == P.DCompound.rec.VARIANT:
            return rec('rec', lit(p.label), arr(*map(quote, p.fields)))
        if p.VARIANT == P.DCompound.arr.VARIANT:
            return rec('arr', arr(*map(quote, p.items)))
        if p.VARIANT == P.DCompound.dict.VARIANT:
            return rec('dict', dict(*map(lambda kv: (kv[0], quote(kv[1])), p.entries.items())))
    raise Exception(f'Unhandled case in quote: {repr(p)}')

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
