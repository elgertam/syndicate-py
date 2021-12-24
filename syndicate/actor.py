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

# decorator
def run_system(**kwargs):
    return lambda boot_proc: start_actor_system(boot_proc, **kwargs)

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

def remove_noerror(collection, item):
    try:
        collection.remove(item)
    except ValueError:
        pass

class Actor:
    def __init__(self, boot_proc, name = None, initial_assertions = {}, daemon = False):
        self.name = name or 'a' + str(next(_next_actor_number))
        self._daemon = daemon
        if not daemon:
            adjust_engine_inhabitant_count(1)
        self.root = Facet(self, None)
        self.outbound = initial_assertions or {}
        self.exit_reason = None  # None -> running, True -> terminated OK, exn -> error
        self.exit_hooks = []
        self._log = None
        Turn.run(Facet(self, self.root, set(self.outbound.keys())), stop_if_inert_after(boot_proc))

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

    def cancel_at_exit(self, hook):
        remove_noerror(self.exit_hooks, hook)

    def _terminate(self, turn, exit_reason):
        if self.exit_reason is not None: return
        self.log.debug('Terminating %r with exit_reason %r', self, exit_reason)
        self.exit_reason = exit_reason
        if exit_reason != True:
            self.log.error('crashed: %s' % (exit_reason,))
        for h in self.exit_hooks:
            h(turn)
        self.root._terminate(turn, exit_reason == True)
        if not self._daemon:
            adjust_engine_inhabitant_count(-1)

    def _pop_outbound(self, handle, clear_from_source_facet):
        e = self.outbound.pop(handle)
        if e and clear_from_source_facet:
            try:
                e.source_facet.handles.remove(handle)
            except KeyError:
                pass
        return e

class Facet:
    def __init__(self, actor, parent, initial_handles=None):
        self.id = next(_next_facet_id)
        self.actor = actor
        self.parent = parent
        if parent:
            parent.children.add(self)
        self.children = set()
        self.handles = initial_handles or set()
        self.shutdown_actions = []
        self.linked_tasks = []
        self.alive = True
        self.inert_check_preventers = 0
        self._log = None

    @property
    def log(self):
        if self._log is None:
            if self.parent is None:
                p = self.actor.log
            else:
                p = self.parent.log
            self._log = p.getChild(str(self.id))
        return self._log

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

    def cancel_on_stop(self, a):
        remove_noerror(self.shutdown_actions, a)

    def isinert(self):
        return \
            len(self.children) == 0 and \
            len(self.handles) == 0 and \
            len(self.linked_tasks) == 0 and \
            self.inert_check_preventers == 0

    def prevent_inert_check(self):
        armed = True
        self.inert_check_preventers = self.inert_check_preventers + 1
        def disarm():
            nonlocal armed
            if not armed: return
            armed = False
            self.inert_check_preventers = self.inert_check_preventers - 1
        return disarm

    def linked_task(self, coro_fn, loop = None):
        task = None
        def cancel_linked_task(turn):
            nonlocal task
            if task is not None:
                remove_noerror(self.linked_tasks, task)
                task.cancel()
                task = None
                self.cancel_on_stop(cancel_linked_task)
                self.actor.cancel_at_exit(cancel_linked_task)
        async def guarded_task():
            try:
                await coro_fn(self)
            finally:
                Turn.external(self, cancel_linked_task)
        task = find_loop(loop).create_task(guarded_task())
        self.linked_tasks.append(task)
        self.on_stop(cancel_linked_task)
        self.actor.at_exit(cancel_linked_task)

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
                with ActiveFacet(turn, self.parent or self):
                    for h in self.shutdown_actions:
                        h(turn)
            for h in self.handles:
                # Optimization: don't clear from source facet, the source facet is us and we're
                # about to clear our handles in one fell swoop.
                turn._retract(self.actor._pop_outbound(h, clear_from_source_facet=False))
            self.handles.clear()

            if orderly:
                if parent:
                    if parent.isinert():
                        parent._terminate(turn, True)
                else:
                    self.actor._terminate(turn, True)

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

def find_loop(loop = None):
    return asyncio.get_running_loop() if loop is None else loop

def queue_task(thunk, loop = None):
    async def task():
        await ensure_awaitable(thunk())
    return find_loop(loop).create_task(task())

def queue_task_threadsafe(thunk, loop = None):
    async def task():
        await ensure_awaitable(thunk())
    return asyncio.run_coroutine_threadsafe(task(), find_loop(loop))

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
            Turn.run(facet.actor.root, lambda turn: facet.actor._terminate(turn, ei[1]))
        else:
            turn._deliver()

    @classmethod
    def external(cls, facet, action, loop = None):
        return queue_task_threadsafe(lambda: cls.run(facet, action), loop)

    def __init__(self, facet):
        self._facet = facet
        self.queues = {}

    @property
    def log(self):
        return self._facet.log

    def ref(self, entity):
        return Ref(self._facet, entity)

    # this actually can work as a decorator as well as a normal method!
    def facet(self, boot_proc):
        new_facet = Facet(self._facet.actor, self._facet)
        with ActiveFacet(self, new_facet):
            stop_if_inert_after(boot_proc)(self)
        return new_facet

    def prevent_inert_check(self):
        return self._facet.prevent_inert_check()

    # decorator
    def linked_task(self, loop = None):
        return lambda coro_fn: self._facet.linked_task(coro_fn, loop = loop)

    def stop(self, facet = None, continuation = None):
        if facet is None:
            facet = self._facet
        if facet.parent is None:
            self.stop_actor()
        else:
            if continuation is not None:
                facet.on_stop(continuation)
            facet._terminate(self, True)

    # can also be used as a decorator
    def on_stop(self, a):
        self._facet.on_stop(a)

    def spawn(self, boot_proc, name = None, initial_handles = None, daemon = False):
        def action(turn):
            new_outbound = {}
            if initial_handles is not None:
                for handle in initial_handles:
                    new_outbound[handle] = \
                        self._facet.actor._pop_outbound(handle, clear_from_source_facet=True)
            queue_task(lambda: Actor(boot_proc,
                                     name = name,
                                     initial_assertions = new_outbound,
                                     daemon = daemon))
        self._enqueue(self._facet, action)

    def stop_actor(self):
        self._enqueue(self._facet.actor.root, lambda turn: self._facet.actor._terminate(turn, True))

    def crash(self, exn):
        self._enqueue(self._facet.actor.root, lambda turn: self._facet.actor._terminate(turn, exn))

    def publish(self, ref, assertion):
        handle = next(_next_handle)
        self._publish(ref, assertion, handle)
        return handle

    def _publish(self, ref, assertion, handle):
        # TODO: attenuation
        assertion = preserve(assertion)
        facet = self._facet
        e = OutboundAssertion(facet, handle, ref)
        facet.actor.outbound[handle] = e
        facet.handles.add(handle)
        def action(turn):
            e.established = True
            self.log.debug('%r <-- publish %r handle %r', ref, assertion, handle)
            ref.entity.on_publish(turn, assertion, handle)
        self._enqueue(ref.facet, action)

    def retract(self, handle):
        if handle is not None:
            e = self._facet.actor._pop_outbound(handle, clear_from_source_facet=True)
            if e is not None:
                self._retract(e)

    def replace(self, ref, handle, assertion):
        new_handle = None if assertion is None else self.publish(ref, assertion)
        self.retract(handle)
        return new_handle

    def _retract(self, e):
        # Assumes e has already been removed from self._facet.actor.outbound and the
        # appropriate set of handles
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
        target_actor = target_facet.actor
        if target_actor not in self.queues:
            self.queues[target_actor] = []
        self.queues[target_actor].append((target_facet, action))

    def _deliver(self):
        for (actor, q) in self.queues.items():
            # Stupid python scoping bites again
            def make_deliver_q(actor, q): # gratuitous
                def deliver_q(turn):
                    saved_facet = turn._facet
                    for (facet, action) in q:
                        turn._facet = facet
                        action(turn)
                    turn._facet = saved_facet
                return lambda: Turn.run(actor.root, deliver_q)
            queue_task(make_deliver_q(actor, q))
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
    def __init__(self, source_facet, handle, ref):
        self.source_facet = source_facet
        self.handle = handle
        self.ref = ref
        self.established = False

    def __repr__(self):
        return '<OutboundAssertion src=%r handle=%s ref=%r%s>' % \
            (self.source_facet, self.handle, self.ref, ' established' if self.established else '')

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
