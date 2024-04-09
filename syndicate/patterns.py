from .schema import dataspacePatterns as P
from . import Symbol, Record
from preserves import preserve

_dict = dict  ## we're about to shadow the builtin

_ = P.Pattern.discard()

def bind(p):
    return P.Pattern.bind(p)

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
        return P.Pattern.lit(P.AnyAtom.decode(p))

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
        return P.Pattern.lit(P.AnyAtom.decode(v))

def seq_entries(seq):
    entries = {}
    for i, p in enumerate(seq):
        if p.VARIANT != P.Pattern.discard.VARIANT:
            entries[i] = p
    np = len(seq)
    if np > 0 and (np - 1) not in entries:
        entries[np - 1] = P.Pattern.discard()
    return entries

def unlit_seq(entries):
    seq = []
    if len(entries) > 0:
        try:
            max_k = max(entries.keys())
        except TypeError:
            raise Exception('Pattern entries do not represent a gap-free sequence')
        for i in range(max_k + 1):
            seq.append(unlit(entries[i]))
    return seq

def unlit(p):
    if not hasattr(p, 'VARIANT'):
        p = P.Pattern.decode(p)
    if p.VARIANT == P.Pattern.lit.VARIANT:
        return p.value.value
    if p.VARIANT != P.Pattern.group.VARIANT:
        raise Exception('Pattern does not represent a literal value')
    if p.type.VARIANT == P.GroupType.rec.VARIANT:
        return Record(p.type.label, unlit_seq(p.entries))
    if p.type.VARIANT == P.GroupType.arr.VARIANT:
        return list(unlit_seq(p.entries))
    if p.type.VARIANT == P.GroupType.dict.VARIANT:
        return _dict(map(lambda kv: (kv[0], unlit(kv[1])), p.entries.items()))
    raise Exception('unreachable')

def rec(labelstr, *members):
    return _rec(Symbol(labelstr), *members)

def _rec(label, *members):
    return P.Pattern.group(P.GroupType.rec(label), seq_entries(members))

def arr(*members):
    return P.Pattern.group(P.GroupType.arr(), seq_entries(members))

def dict(*kvs):
    return P.Pattern.group(P.GroupType.dict(), _dict(kvs))
