from syndicate import relay, Symbol, Record, patterns as P, actor, dataspace, turn, Embedded
from syndicate.during import During

FibRequest = Record.makeConstructor('fib', 'n k')

@relay.service(name='fib-client')
@During().add_handler
def main(n, server):
    server = server.embeddedValue
    turn.log.info('Client asked to send a request to solve %r to server %r' % (n, server))

    @During().add_handler
    def k(result):
        turn.log.info('Client got reply %r for n %r' % (result, n))

    turn.publish(server, FibRequest(n, Embedded(turn.ref(k))))
