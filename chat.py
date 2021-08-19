import sys
import asyncio
import random
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

def main_facet(turn, root_facet, ds):
    print('main_facet', ds)
    f = turn._facet
    turn.publish(ds, Present(me))

    def on_presence(turn, who):
        print('%s joined' % (who,))
        return lambda turn: print('%s left' % (who,))
    turn.publish(ds, dataspace.Observe(P.rec('Present', P.CAPTURE),
                                       During(turn, on_add = on_presence).ref))

    def on_says(turn, who, what):
        print('%s says %r' % (who, what))
    turn.publish(ds, dataspace.Observe(P.rec('Says', P.CAPTURE, P.CAPTURE),
                                       During(turn, on_msg = on_says).ref))

    async def accept_input():
        reader = asyncio.StreamReader()
        await actor.find_loop().connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader),
            sys.stdin)
        while True:
            line = (await reader.readline()).decode('utf-8')
            if not line:
                actor.Turn.external(f, lambda turn: turn.stop(root_facet))
                break
            actor.Turn.external(f, lambda turn: turn.send(ds, Says(me, line.strip())))
    turn.linked_task(accept_input())

def main(turn):
    root_facet = turn._facet

    def handle_gatekeeper(turn, gk):
        turn.publish(gk.embeddedValue, gatekeeper.Resolve(cap, ds_receiver))
    gk_receiver = During(turn, on_add = handle_gatekeeper).ref

    def handle_ds(turn, ds):
        return turn.facet(lambda turn: main_facet(turn, root_facet, ds.embeddedValue))
    ds_receiver = During(turn, on_add = handle_ds).ref

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
