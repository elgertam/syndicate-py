from syndicate import relay
from syndicate.during import During
import logging

@relay.service(name='inf', debug=True)
@During().add_handler
def main(turn, args):
    logging.info(f'in main {turn}, {args}')
    turn.on_stop(lambda turn: logging.info(f'args retracted {args}'))
