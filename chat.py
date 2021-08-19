import sys
import asyncio
import random
import threading
import syndicate
from syndicate import patterns as P, actor
from syndicate.schema import simpleChatProtocol, gatekeeper, sturdy, dataspace
from syndicate.during import During

Present = simpleChatProtocol.Present
Says = simpleChatProtocol.Says

conn_str = '<ws "ws://localhost:8001/">'
cap_str = '<ref "syndicate" [] #[pkgN9TBmEd3Q04grVG4Zdw==]>'
cap = sturdy.SturdyRef.decode(syndicate.parse(cap_str))

# sys.stderr.write(
#     'Usage: chat.py [ <tcp "HOST" PORT> | <ws "ws://HOST[:PORT]/"> | <unix "PATH"> ]\n')
# sys.exit(1)

me = 'user_' + str(random.randint(10, 1000))

_print = print
def print(*items):
    _print(*items)
    sys.stdout.flush()

def on_presence(turn, who):
    print('%s joined' % (who,))
    return lambda turn: print('%s left' % (who,))

def main_facet(turn, root_facet, ds):
    print('main_facet', ds)
    f = turn._facet
    turn.publish(ds, Present(me))
    turn.publish(ds, dataspace.Observe(P.rec('Present', P.CAPTURE),
                                       During(turn, on_add = on_presence).ref))
    turn.publish(ds, dataspace.Observe(P.rec('Says', P.CAPTURE, P.CAPTURE), During(
        turn,
        on_msg = lambda turn, who, what: print('%s says %r' % (who, what))).ref))

    loop = asyncio.get_running_loop()
    def accept_input():
        while True:
            line = sys.stdin.readline()
            if not line:
                actor.Turn.external(loop, f, lambda turn: turn.stop(root_facet))
                break
            actor.Turn.external(loop, f, lambda turn: turn.send(ds, Says(me, line.strip())))
    threading.Thread(target=accept_input, daemon=True).start()

def main(turn):
    root_facet = turn._facet
    gk_receiver = During(turn, on_add = lambda turn, gk: turn.publish(
        gk.embeddedValue, gatekeeper.Resolve(cap, ds_receiver))).ref
    ds_receiver = During(turn, on_add = lambda turn, ds: turn.facet(
        lambda turn: main_facet(turn, root_facet, ds.embeddedValue))).ref

    disarm = turn.prevent_inert_check()
    async def on_connected(tr):
        disarm()
        print('-'*50, 'Connected')
    async def on_disconnected(tr, did_connect):
        if did_connect:
            print('-'*50, 'Disconnected')
        else:
            await asyncio.sleep(2)
        return True

    conn = syndicate.relay.TunnelRelay.from_str(turn,
                                                conn_str,
                                                gatekeeper_peer = gk_receiver,
                                                on_connected = on_connected,
                                                on_disconnected = on_disconnected)

actor.start_actor_system(main, name = 'chat', debug = False)
