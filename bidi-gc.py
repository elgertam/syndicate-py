import sys
import argparse
import asyncio
import random
import syndicate
from syndicate import patterns as P, actor, dataspace, Record, Embedded
from syndicate.during import Handler
from syndicate.schema import sturdy

parser = argparse.ArgumentParser(description='Test bidirectional object reference GC.',
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('--address', metavar='\'<tcp "HOST" PORT>\'',
                    help='transport address of the server',
                    default='<ws "ws://localhost:8001/">')
parser.add_argument('--cap', metavar='\'<ref ...>\'',
                    help='capability for the dataspace on the server',
                    default='<ref "syndicate" [] #[pkgN9TBmEd3Q04grVG4Zdw==]>')
parser.add_argument('--start',
                    help='make this instance kick off the procedure',
                    action='store_true')
args = parser.parse_args()

#   A             B             DS
# -----         -----         ------
#
#                 ---1:Boot(b)---o
#
#   ------2:Observe(Boot($))-----o
#   o----------3:[b]--------------
#
#   ---4:One(a)---o
#
#                 -------1-------x
#   x------------3----------------
#
#   (At this point, B has no outgoing
#   assertions, but has one incoming
#   assertion.)
#
#   o---5:Two()----
#
#   ----Three()--->

Boot = Record.makeConstructor('Boot', 'b')
One = Record.makeConstructor('One', 'a')
Two = Record.makeConstructor('Two', '')
Three = Record.makeConstructor('Three', '')

@actor.run_system(name = 'bidi-gc', debug = False)
def main(turn):
    root_facet = turn._facet

    @syndicate.relay.connect(turn, args.address, sturdy.SturdyRef.decode(syndicate.parse(args.cap)),
                             on_disconnected = lambda _relay, _did_connect: sys.exit(1))
    def on_connected(turn, ds):
        if args.start:
            # We are "A".

            @dataspace.observe(turn, ds, P.rec('Boot', P.CAPTURE))
            @Handler().add_handler
            def on_b(turn, b):
                print('A got B', b)
                @Handler().add_handler
                def a(turn, two):
                    print('A got assertion:', two)
                    turn.send(b.embeddedValue, Three())
                    def on_two_retracted(turn):
                        print('Assertion', two, 'from B went')
                        turn.retract(one_handle)
                    return on_two_retracted
                one_handle = turn.publish(b.embeddedValue, One(Embedded(turn.ref(a))))
                return lambda turn: print('B\'s Boot record went')
        else:
            # We are "B".

            @Handler().add_handler
            def b(turn, one):
                print('B got assertion:', one)
                print('boot_handle =', boot_handle)
                turn.retract(boot_handle)
                turn.publish(One._a(one).embeddedValue, Two())
                return lambda turn: print('B facet stopping')
            @b.msg_handler
            def b_msg(turn, three):
                print('B got message: ', three)
            boot_handle = turn.publish(ds, Boot(Embedded(turn.ref(b))))
