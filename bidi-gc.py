import sys
import argparse
import asyncio
import random
import syndicate
from syndicate import patterns as P, actor, dataspace, Record, Embedded, turn
from syndicate.during import Handler
from syndicate.schema import sturdy

parser = argparse.ArgumentParser(description='Test bidirectional object reference GC.',
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('--address', metavar='\'<tcp "HOST" PORT>\'',
                    help='transport address of the server',
                    default='<ws "ws://localhost:9001/">')
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

#
# Here's a trace from a live session of this running against syndicate-rs:
#
#     B --> server: [[1, <assert <Boot #!⌜141/402:00007f3e50021ef0⌝> 3>]]
#
#     A --> server: [[1, <assert <Observe <rec Boot [<bind <_>>]> #!⌜151/422:00007f3e50025090⌝> 3>]]
#     A <-- server: [[1, <assert [#!⌜141/402:00007f3e50021ef0⌝] 633>]]
#     A --> server: [[2, <assert <One #!⌜151/422:00007f3e5c009b00⌝> 5>]]
#
#     B <-- server: [[1, <assert <One #!⌜151/422:00007f3e5c009b00⌝> 643>]]
#     B --> server: [[1, <retract 3>], [2, <assert <Two> 5>]]
#
#     A <-- server: [[2, <assert <Two> 653>]]
#     A <-- server: [[1, <retract 633>]]
#     A --> server: [[2, <message <Three>>]]
#
#     B <-- server: [[1, <message <Three>>]]
#

Boot = Record.makeConstructor('Boot', 'b')
One = Record.makeConstructor('One', 'a')
Two = Record.makeConstructor('Two', '')
Three = Record.makeConstructor('Three', '')

@actor.run_system(name = 'bidi-gc', debug = False)
def main():
    root_facet = turn.active_facet()

    @syndicate.relay.connect(args.address, sturdy.SturdyRef.decode(syndicate.parse(args.cap)),
                             on_disconnected = lambda _relay, _did_connect: sys.exit(1))
    def on_connected(ds):
        if args.start:
            # We are "A".

            @dataspace.observe(ds, P.rec('Boot', P.CAPTURE))
            @Handler().add_handler
            def on_b(b):
                print('A got B', b)
                @Handler().add_handler
                def a(two):
                    print('A got assertion:', two)
                    turn.send(b.embeddedValue, Three())
                    def on_two_retracted():
                        print('Assertion', two, 'from B went')
                        turn.retract(one_handle)
                    return on_two_retracted
                one_handle = turn.publish(b.embeddedValue, One(Embedded(turn.ref(a))))
                return lambda: print('B\'s Boot record went')
        else:
            # We are "B".

            @Handler().add_handler
            def b(one):
                print('B got assertion:', one)
                print('boot_handle =', boot_handle)
                turn.retract(boot_handle)
                turn.publish(One._a(one).embeddedValue, Two())
                return lambda: print('B facet stopping')
            @b.msg_handler
            def b_msg(three):
                print('B got message:', three)
            boot_handle = turn.publish(ds, Boot(Embedded(turn.ref(b))))
