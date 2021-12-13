import sys
import argparse
import asyncio
import random
import syndicate
from syndicate import patterns as P, actor, dataspace
from syndicate.schema import simpleChatProtocol, sturdy

parser = argparse.ArgumentParser(description='Simple dataspace-server-mediated text chat.',
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('--address', metavar='\'<tcp "HOST" PORT>\'',
                    help='transport address of the server',
                    default='<ws "ws://localhost:9001/">')
parser.add_argument('--cap', metavar='\'<ref ...>\'',
                    help='capability for the dataspace on the server',
                    default='<ref "syndicate" [] #[pkgN9TBmEd3Q04grVG4Zdw==]>')
args = parser.parse_args()

Present = simpleChatProtocol.Present
Says = simpleChatProtocol.Says

@actor.run_system(name = 'chat', debug = False)
def main(turn):
    root_facet = turn._facet

    @syndicate.relay.connect(turn, args.address, sturdy.SturdyRef.decode(syndicate.parse(args.cap)))
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
