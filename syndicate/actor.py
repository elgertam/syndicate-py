import asyncio
import inspect
import logging
import sys
import traceback

from preserves import Embedded, preserve

from .idgen import IdGenerator

log = logging.getLogger(__name__)

_next_actor_number = IdGenerator()
_next_handle = IdGenerator()
_next_facet_id = IdGenerator()

def start_actor_system(boot_proc, debug = False, name = None, configure_logging = True):
    if configure_logging:
        logging.basicConfig(level = logging.DEBUG if debug else logging.INFO)
    loop = asyncio.get_event_loop()
    if debug:
        loop.set_debug(True)
    queue_task(lambda: Actor(boot_proc, name = name), loop = loop)
    loop.run_forever()
    while asyncio.all_tasks(loop):
        loop.stop()
        loop.run_forever()
    loop.close()

def adjust_engine_inhabitant_count(delta):
    loop = asyncio.get_running_loop()
    if not hasattr(loop, '__syndicate_inhabitant_count'):
        loop.__syndicate_inhabitant_count = 0
    loop.__syndicate_inhabitant_count = loop.__syndicate_inhabitant_count + delta
    if loop.__syndicate_inhabitant_count == 0:
        log.debug('Inhabitant count reached zero')
        loop.stop()

class Actor:
    def __init__(self, boot_proc, name = None, initial_assertions = {}, daemon = False):
        self.name = name or 'a' + str(next(_next_actor_number))
        self._daemon = daemon
        if not daemon:
            adjust_engine_inhabitant_count(1)
        self.root = Facet(self, None)
        self.exit_reason = None  # None -> running, True -> terminated OK, exn -> error
        self.exit_hooks = []
        self._log = None
        Turn.run(Facet(self, self.root, initial_assertions = initial_assertions),
                 stop_if_inert_after(boot_proc))

    def __repr__(self):
        return '<Actor:%s>' % (self.name,)

    @property
    def daemon(self):
        return self._daemon

    @daemon.setter
    def daemon(self, value):
        if self._daemon != value:
            self._daemon = value
            adjust_engine_inhabitant_count(-1 if value else 1)

    @property
    def alive(self):
        return self.exit_reason is None

    @property
    def log(self):
        if self._log is None:
            self._log = logging.getLogger('syndicate.Actor.%s' % (self.name,))
        return self._log

    def at_exit(self, hook):
        self.exit_hooks.append(hook)

    def terminate(self, turn, exit_reason):
        if self.exit_reason is not None: return
        self.log.debug('Terminating %r with exit_reason %r', self, exit_reason)
        self.exit_reason = exit_reason
        if exit_reason != True:
            self.log.error('crashed: %s' % (exit_reason,))
        for h in self.exit_hooks:
            h(turn)
        def finish_termination():
            Turn.run(self.root,
                     lambda turn: self.root._terminate(turn, exit_reason == True),
                     zombie_turn = True)
            if not self._daemon:
                adjust_engine_inhabitant_count(-1)
        queue_task(finish_termination)

class Facet:
    def __init__(self, actor, parent, initial_assertions = {}):
        self.id = next(_next_facet_id)
        self.actor = actor
        self.parent = parent
        if parent:
            parent.children.add(self)
        self.children = set()
        self.outbound = initial_assertions
        self.shutdown_actions = []
        self.alive = True
        self.inert_check_preventers = 0

    @property
    def log(self):
        return self.actor.log

    def _repr_labels(self):
        pieces = []
        f = self
        while f.parent is not None:
            pieces.append(str(f.id))
            f = f.parent
        pieces.append(self.actor.name)
        pieces.reverse()
        return ':'.join(pieces)

    def __repr__(self):
        return '<Facet:%s>' % (self._repr_labels(),)

    def on_stop(self, a):
        self.shutdown_actions.append(a)

    def isinert(self):
        return len(self.children) == 0 and len(self.outbound) == 0 and self.inert_check_preventers == 0

    def prevent_inert_check(self):
        armed = True
        self.inert_check_preventers = self.inert_check_preventers + 1
        def disarm():
            nonlocal armed
            if not armed: return
            armed = False
            self.inert_check_preventers = self.inert_check_preventers - 1
        return disarm

    def _terminate(self, turn, orderly):
        if not self.alive: return
        self.log.debug('%s terminating %r', 'orderly' if orderly else 'disorderly', self)
        self.alive = False

        parent = self.parent
        if parent:
            parent.children.remove(self)

        with ActiveFacet(turn, self):
            for child in list(self.children):
                child._terminate(turn, orderly)
            if orderly:
                for h in self.shutdown_actions:
                    h(turn)
            for e in self.outbound.values():
                turn._retract(e)
            self.outbound.clear()

            if orderly:
                if parent:
                    if parent.isinert():
                        Turn.run(parent, lambda turn: parent._terminate(turn, True))
                else:
                    Turn.run(self.actor.root,
                             lambda turn: self.actor.terminate(turn, True),
                             zombie_turn = True)

class ActiveFacet:
    def __init__(self, turn, facet):
        self.turn = turn
        self.outer_facet = None
        self.inner_facet = facet

    def __enter__(self):
        self.outer_facet = self.turn._facet
        self.turn._facet = self.inner_facet
        return None

    def __exit__(self, t, v, tb):
        self.turn._facet = self.outer_facet
        self.outer_facet = None

async def ensure_awaitable(value):
    if inspect.isawaitable(value):
        return await value
    else:
        return value

def queue_task(thunk, loop = asyncio):
    async def task():
        await ensure_awaitable(thunk())
    return loop.create_task(task())

def queue_task_threadsafe(thunk, loop):
    async def task():
        await ensure_awaitable(thunk())
    return asyncio.run_coroutine_threadsafe(task(), loop)

class Turn:
    @classmethod
    def run(cls, facet, action, zombie_turn = False):
        if not zombie_turn:
            if not facet.actor.alive: return
            if not facet.alive: return
        turn = cls(facet)
        try:
            action(turn)
        except:
            ei = sys.exc_info()
            facet.log.error('%s', ''.join(traceback.format_exception(*ei)))
            Turn.run(facet.actor.root, lambda turn: facet.actor.terminate(turn, ei[1]))
        else:
            turn._deliver()

    @classmethod
    def external(cls, loop, facet, action):
        return queue_task_threadsafe(lambda: cls.run(facet, action), loop)

    def __init__(self, facet):
        self._facet = facet
        self.queues = {}

    @property
    def log(self):
        return self._facet.log

    def ref(self, entity):
        return Ref(self._facet, entity)

    def facet(self, boot_proc):
        new_facet = Facet(self._facet.actor, self._facet)
        with ActiveFacet(self, new_facet):
            stop_if_inert_after(boot_proc)(self)
        return new_facet

    def prevent_inert_check(self):
        return self._facet.prevent_inert_check()

    def stop(self, facet = None, continuation = None):
        if facet is None:
            facet = self._facet
        def action(turn):
            facet._terminate(turn, True)
            if continuation is not None:
                continuation(turn)
        self._enqueue(facet.parent, action)

    def spawn(self, boot_proc, name = None, initial_assertions = None, daemon = False):
        def action(turn):
            new_outbound = {}
            if initial_assertions is not None:
                for handle in initial_assertions:
                    new_outbound[handle] = self._facet.outbound.pop(handle)
            queue_task(lambda: Actor(boot_proc,
                                     name = name,
                                     initial_assertions = new_outbound,
                                     daemon = daemon))
        self._enqueue(self._facet, action)

    def stop_actor(self):
        self._enqueue(self._facet.actor.root, lambda turn: self._facet.actor.terminate(turn, True))

    def crash(self, exn):
        self._enqueue(self._facet.actor.root, lambda turn: self._facet.actor.terminate(turn, exn))

    def publish(self, ref, assertion):
        handle = next(_next_handle)
        self._publish(ref, assertion, handle)
        return handle

    def _publish(self, ref, assertion, handle):
        # TODO: attenuation
        assertion = preserve(assertion)
        e = OutboundAssertion(handle, ref)
        self._facet.outbound[handle] = e
        def action(turn):
            e.established = True
            self.log.debug('%r <-- publish %r handle %r', ref, assertion, handle)
            ref.entity.on_publish(turn, assertion, handle)
        self._enqueue(ref.facet, action)

    def retract(self, handle):
        if handle is not None:
            e = self._facet.outbound.pop(handle, None)
            if e is not None:
                self._retract(e)

    def replace(self, ref, handle, assertion):
        new_handle = None if assertion is None else self.publish(ref, assertion)
        self.retract(handle)
        return new_handle

    def _retract(self, e):
        # Assumes e has already been removed from self._facet.outbound
        def action(turn):
            if e.established:
                e.established = False
                self.log.debug('%r <-- retract handle %r', e.ref, e.handle)
                e.ref.entity.on_retract(turn, e.handle)
        self._enqueue(e.ref.facet, action)

    def sync(self, ref, k):
        class SyncContinuation(Entity):
            def on_message(self, turn, _value):
                k(turn)
        self._sync(ref, self.ref(SyncContinuation()))

    def _sync(self, ref, peer):
        peer = preserve(peer)
        def action(turn):
            self.log.debug('%r <-- sync peer %r', ref, peer)
            ref.entity.on_sync(turn, peer)
        self._enqueue(ref.facet, action)

    def send(self, ref, message):
        # TODO: attenuation
        message = preserve(message)
        def action(turn):
            self.log.debug('%r <-- message %r', ref, message)
            ref.entity.on_message(turn, message)
        self._enqueue(ref.facet, action)

    def _enqueue(self, target_facet, action):
        if target_facet not in self.queues:
            self.queues[target_facet] = []
        self.queues[target_facet].append(action)

    def _deliver(self):
        for (facet, q) in self.queues.items():
            # Stupid python scoping bites again
            def make_deliver_q(facet, q): # gratuitous
                def deliver_q(turn):
                    for action in q:
                        action(turn)
                return lambda: Turn.run(facet, deliver_q)
            queue_task(make_deliver_q(facet, q))
        self.queues = {}

def stop_if_inert_after(action):
    def wrapped_action(turn):
        action(turn)
        def check_action(turn):
            if (turn._facet.parent is not None and not turn._facet.parent.alive) \
               or turn._facet.isinert():
                turn.stop()
        turn._enqueue(turn._facet, check_action)
    return wrapped_action

class Ref:
    def __init__(self, facet, entity):
        self.facet = facet
        self.entity = entity

    def __repr__(self):
        return '<Ref:%s/%r>' % (self.facet._repr_labels(), self.entity)

class OutboundAssertion:
    def __init__(self, handle, ref):
        self.handle = handle
        self.ref = ref
        self.established = False

# Can act as a mixin
class Entity:
    def on_publish(self, turn, v, handle):
        pass

    def on_retract(self, turn, handle):
        pass

    def on_message(self, turn, v):
        pass

    def on_sync(self, turn, peer):
        turn.send(peer, True)

_inert_actor = None
_inert_facet = None
_inert_ref = None
_inert_entity = Entity()
def __boot_inert(turn):
    global _inert_actor, _inert_facet, _inert_ref
    _inert_actor = turn._facet.actor
    _inert_facet = turn._facet
    _inert_ref = turn.ref(_inert_entity)
async def __run_inert():
    Actor(__boot_inert, name = '_inert_actor')
asyncio.get_event_loop().run_until_complete(__run_inert())
