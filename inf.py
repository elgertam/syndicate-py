from syndicate import relay, turn
from syndicate.during import During
import logging

@relay.service(name='inf', debug=True)
@During().add_handler
def main(args):
    logging.info(f'in main {args}')
    turn.on_stop(lambda: logging.info(f'args retracted {args}'))
