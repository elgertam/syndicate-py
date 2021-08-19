from .schema import dataspacePatterns as P
from . import Symbol

_dict = dict  ## we're about to shadow the builtin

_ = P.Pattern.DDiscard(P.DDiscard())

def bind(p):
    return P.Pattern.DBind(P.DBind(p))

CAPTURE = bind(_)

def lit(v):
    return P.Pattern.DLit(P.DLit(v))

def rec(labelstr, *members):
    return _rec(Symbol(labelstr), *members)

def _rec(label, *members):
    return P.Pattern.DCompound(P.DCompound.rec(
        P.CRec(label, len(members)),
        _dict(enumerate(members))))

def arr(*members):
    return P.Pattern.DCompound(P.DCompound.arr(
        P.CArr(len(members)),
        _dict(enumerate(members))))

def dict(*kvs):
    return P.Pattern.DCompound(P.DCompound.dict(
        P.CDict(),
        _dict(kvs)))
