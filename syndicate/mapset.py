def add(m, k, v):
    s = m.get(k)
    if s is None:
        s = set()
        m[k] = s
    s.add(v)

def discard(m, k, v):
    s = m.get(k)
    if s is None:
        return
    s.discard(v)
    if not s:
        m.pop(k)
