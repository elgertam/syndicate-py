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
    # Alternative: turn.on_stop(lambda: turn.log.info('...'))
    @turn.on_stop
    def handle_retraction():
        turn.log.info('Request %r retracted' % (req,))

    if FibRequest.isClassOf(req):
        n = FibRequest._n(req)
        result = fib(n)
        turn.log.info('Publishing reply %r to request %r' % (result, n))
        turn.publish(FibRequest._k(req).embeddedValue, result)
    else:
        turn.log.info('Got bad request %r' % (req,))
