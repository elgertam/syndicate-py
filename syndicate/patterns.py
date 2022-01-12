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
    def __escape_schema__(self):
        return self

uCAPTURE = unquote(CAPTURE)
u_ = unquote(_)

# Given
#
#   Run = <run @name string @input any @output any>
#
# then these all produce the same pattern:
#
# P.rec('Observe', P.quote(P.rec('run', P.lit('N'), P.uCAPTURE, P.bind(P.u_))), P._)
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

def unlit(p):
    if not hasattr(p, 'VARIANT'):
        p = P.Pattern.decode(p)
    if p.VARIANT == P.Pattern.DLit.VARIANT:
        return p.value.value.value
    if p.VARIANT != P.Pattern.DCompound.VARIANT:
        raise Exception('Pattern does not represent a literal value')
    p = p.value
    if p.VARIANT == P.DCompound.rec.VARIANT:
        return Record(p.label, map(unlit, p.fields))
    if p.VARIANT == P.DCompound.arr.VARIANT:
        return list(map(unlit, p.items))
    if p.VARIANT == P.DCompound.dict.VARIANT:
        return _dict(map(lambda kv: (kv[0], unlit(kv[1])), p.entries.items()))
    raise Exception('unreachable')

def rec(labelstr, *members):
    return _rec(Symbol(labelstr), *members)

def _rec(label, *members):
    return P.Pattern.DCompound(P.DCompound.rec(label, members))

def arr(*members):
    return P.Pattern.DCompound(P.DCompound.arr(members))

def dict(*kvs):
    return P.Pattern.DCompound(P.DCompound.dict(_dict(kvs)))
