from syndicate import relay, Symbol, Record, patterns as P, actor, dataspace, turn
from syndicate.during import During

FibRequest = Record.makeConstructor('fib', 'n k')

def fib(n):
    if n <= 2:
        return n
    else:
        return fib(n - 1) + fib(n - 2)

@relay.service(name='fib-server')
@During().add_handler
def main(req):
    turn.log.info('Got request %r' % (req,))
    turn.on_stop(lambda: turn.log.info('Request %r retracted' % (req,)))

    if FibRequest.isClassOf(req):
        result = fib(FibRequest._n(req))
        turn.log.info('Publishing reply %r to request %r' % (result, req))
        turn.publish(FibRequest._k(req).embeddedValue, result)
