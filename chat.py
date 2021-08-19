import sys
import asyncio
import random
import syndicate
from syndicate import patterns as P, actor, dataspace
from syndicate.schema import simpleChatProtocol, gatekeeper, sturdy
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

    @dataspace.during(turn, ds, P.rec('Present', P.CAPTURE))
    def on_presence(turn, who):
        print('%s joined' % (who,))
        return lambda turn: print('%s left' % (who,))

    @dataspace.on_message(turn, ds, P.rec('Says', P.CAPTURE, P.CAPTURE))
    def on_says(turn, who, what):
        print('%s says %r' % (who, what))

    @turn.linked_task()
    async def accept_input():
        reader = asyncio.StreamReader()
        await actor.find_loop().connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        while line := (await reader.readline()).decode('utf-8'):
            actor.Turn.external(f, lambda turn: turn.send(ds, Says(me, line.strip())))
        actor.Turn.external(f, lambda turn: turn.stop(root_facet))

def main(turn):
    root_facet = turn._facet

    @During().add_handler
    def handle_gatekeeper(turn, gk):
        @During().add_handler
        def handle_ds(turn, ds):
            return turn.facet(lambda turn: main_facet(turn, root_facet, ds.embeddedValue))
        turn.publish(gk.embeddedValue, gatekeeper.Resolve(cap, turn.ref(handle_ds)))

    conn = syndicate.relay.TunnelRelay.from_str(turn,
                                                conn_str,
                                                gatekeeper_peer = turn.ref(handle_gatekeeper))

actor.start_actor_system(main, name = 'chat', debug = False)
