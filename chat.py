import sys
import asyncio
import random
import syndicate
from syndicate import patterns as P, actor, dataspace, gatekeeper
from syndicate.schema import simpleChatProtocol, sturdy
from syndicate.during import During

Present = simpleChatProtocol.Present
Says = simpleChatProtocol.Says

conn_str = '<ws "ws://localhost:8001/">'
cap_str = '<ref "syndicate" [] #[pkgN9TBmEd3Q04grVG4Zdw==]>'
cap = sturdy.SturdyRef.decode(syndicate.parse(cap_str))

def main(turn):
    root_facet = turn._facet

    @syndicate.relay.connect(turn, conn_str, cap)
    def on_connected(turn, ds):
        me = 'user_' + str(random.randint(10, 1000))

        turn.publish(ds, Present(me))

        @dataspace.during(turn, ds, P.rec('Present', P.CAPTURE), inert_ok=True)
        def on_presence(turn, who):
            print('%s joined' % (who,))
            turn.on_stop(lambda turn: print('%s left' % (who,)))

        @dataspace.on_message(turn, ds, P.rec('Says', P.CAPTURE, P.CAPTURE))
        def on_says(turn, who, what):
            print('%s says %r' % (who, what))

        @turn.linked_task()
        async def accept_input(f):
            reader = asyncio.StreamReader()
            await actor.find_loop().connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
            while line := (await reader.readline()).decode('utf-8'):
                actor.Turn.external(f, lambda turn: turn.send(ds, Says(me, line.strip())))
            actor.Turn.external(f, lambda turn: turn.stop(root_facet))

actor.start_actor_system(main, name = 'chat', debug = False)
