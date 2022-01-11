import asyncio
import inspect
import logging
import sys
import traceback
import threading

from preserves import Embedded, preserve

from .idgen import IdGenerator
from .metapy import staticproperty
from .dataflow import Graph, Field

log = logging.getLogger(__name__)

_next_actor_number = IdGenerator()
_next_handle = IdGenerator()
_next_facet_id = IdGenerator()

_active = threading.local()
_active.turn = None

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
        self._dataflow_graph = None
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

    @property
    def dataflow_graph(self):
        if self._dataflow_graph is None:
            self._dataflow_graph = Graph()
        return self._dataflow_graph

    def at_exit(self, hook):
        self.exit_hooks.append(hook)

    def cancel_at_exit(self, hook):
        remove_noerror(self.exit_hooks, hook)

    def _repair_dataflow_graph(self):
        if self._dataflow_graph is not None:
            self._dataflow_graph.repair_damage(lambda a: a())

    def _terminate(self, exit_reason):
        if self.exit_reason is not None: return
        self.log.debug('Terminating %r with exit_reason %r', self, exit_reason)
        self.exit_reason = exit_reason
        if exit_reason != True:
            self.log.error('crashed: %s' % (exit_reason,))
        for h in self.exit_hooks:
            h()
        self.root._terminate(exit_reason == True)
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
    @staticproperty
    def active():
        return _active.turn._facet

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

    def on_stop_or_crash(self, a):
        def cleanup():
            self.cancel_on_stop(cleanup)
            self.actor.cancel_at_exit(cleanup)
            a()
        self.on_stop(cleanup)
        self.actor.at_exit(cleanup)
        return cleanup

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
        @self.on_stop_or_crash
        def cancel_linked_task():
            nonlocal task
            if task is not None:
                remove_noerror(self.linked_tasks, task)
                task.cancel()
                task = None
        async def guarded_task():
            try:
                await coro_fn(self)
            finally:
                Turn.external(self, cancel_linked_task)
        task = find_loop(loop).create_task(guarded_task())
        self.linked_tasks.append(task)

    def _terminate(self, orderly):
        if not self.alive: return
        self.log.debug('%s terminating %r', 'orderly' if orderly else 'disorderly', self)
        self.alive = False

        parent = self.parent
        if parent:
            parent.children.remove(self)

        with ActiveFacet(self):
            for child in list(self.children):
                child._terminate(orderly)
            if orderly:
                with ActiveFacet(self.parent or self):
                    for h in self.shutdown_actions:
                        h()
            turn = Turn.active
            for h in self.handles:
                # Optimization: don't clear from source facet, the source facet is us and we're
                # about to clear our handles in one fell swoop.
                turn._retract(self.actor._pop_outbound(h, clear_from_source_facet=False))
            self.handles.clear()

            if orderly:
                if parent:
                    if parent.isinert():
                        parent._terminate(True)
                else:
                    self.actor._terminate(True)

class ActiveFacet:
    def __init__(self, facet):
        self.turn = Turn.active
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
    @staticproperty
    def active():
        t = getattr(_active, 'turn', False)
        if t is False:
            t = _active.turn = None
        return t

    @classmethod
    def run(cls, facet, action, zombie_turn = False):
        if not zombie_turn:
            if not facet.actor.alive: return
            if not facet.alive: return
        turn = cls(facet)
        try:
            saved = Turn.active
            _active.turn = turn
            try:
                action()
                facet.actor._repair_dataflow_graph()
            finally:
                _active.turn = saved
        except:
            ei = sys.exc_info()
            facet.log.error('%s', ''.join(traceback.format_exception(*ei)))
            Turn.run(facet.actor.root, lambda: facet.actor._terminate(ei[1]))
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
        with ActiveFacet(new_facet):
            stop_if_inert_after(boot_proc)()
        return new_facet

    def prevent_inert_check(self):
        return self._facet.prevent_inert_check()

    # decorator
    def linked_task(self, loop = None):
        return lambda coro_fn: self._facet.linked_task(coro_fn, loop = loop)

    def stop(self, facet = None, continuation = None):
        if facet is None:
            facet = self._facet
        if continuation is not None:
            facet.on_stop(continuation)
        facet._terminate(True)

    # can also be used as a decorator
    def on_stop(self, a):
        self._facet.on_stop(a)

    # can also be used as a decorator
    def on_stop_or_crash(self, a):
        self._facet.on_stop_or_crash(a)

    def spawn(self, boot_proc, name = None, initial_handles = None, daemon = False):
        def action():
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
        self._enqueue(self._facet.actor.root, lambda: self._facet.actor._terminate(True))

    def crash(self, exn):
        self._enqueue(self._facet.actor.root, lambda: self._facet.actor._terminate(exn))

    def field(self, initial_value=None, name=None):
        return Field(self._facet.actor.dataflow_graph, initial_value, name)

    # can also be used as a decorator
    def dataflow(self, a):
        f = self._facet
        f.prevent_inert_check()
        def subject():
            if not f.alive: return
            with ActiveFacet(f):
                a()
        f.on_stop(lambda: f.actor.dataflow_graph.forget_subject(subject))
        f.actor.dataflow_graph.with_subject(subject, lambda: subject())

    def publish_dataflow(self, assertion_function):
        endpoint = DataflowPublication(assertion_function)
        self.dataflow(lambda: endpoint.update())

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
        def action():
            e.established = True
            self.log.debug('%r <-- publish %r handle %r', ref, assertion, handle)
            ref.entity.on_publish(assertion, handle)
        self._enqueue(ref.facet, action)

    def retract(self, handle):
        if handle is not None:
            e = self._facet.actor._pop_outbound(handle, clear_from_source_facet=True)
            if e is not None:
                self._retract(e)

    def replace(self, ref, handle, assertion):
        if assertion is None or ref is None:
            new_handle = None
        else:
            new_handle = self.publish(ref, assertion)
        self.retract(handle)
        return new_handle

    def _retract(self, e):
        # Assumes e has already been removed from self._facet.actor.outbound and the
        # appropriate set of handles
        def action():
            if e.established:
                e.established = False
                self.log.debug('%r <-- retract handle %r', e.ref, e.handle)
                e.ref.entity.on_retract(e.handle)
        self._enqueue(e.ref.facet, action)

    def sync(self, ref, k):
        class SyncContinuation(Entity):
            def on_message(self, _value):
                k()
        self._sync(ref, self.ref(SyncContinuation()))

    def _sync(self, ref, peer):
        peer = preserve(peer)
        def action():
            self.log.debug('%r <-- sync peer %r', ref, peer)
            ref.entity.on_sync(peer)
        self._enqueue(ref.facet, action)

    def send(self, ref, message):
        # TODO: attenuation
        message = preserve(message)
        def action():
            self.log.debug('%r <-- message %r', ref, message)
            ref.entity.on_message(message)
        self._enqueue(ref.facet, action)

    # decorator
    def after(self, delay_seconds):
        def decorate(action):
            @self.linked_task()
            async def task(facet):
                await asyncio.sleep(delay_seconds)
                Turn.external(facet, action)
        return decorate

    def _enqueue(self, target_facet, action):
        target_actor = target_facet.actor
        if target_actor not in self.queues:
            self.queues[target_actor] = []
        self.queues[target_actor].append((target_facet, action))

    def _deliver(self):
        for (actor, q) in self.queues.items():
            # Stupid python scoping bites again
            def make_deliver_q(actor, q): # gratuitous
                def deliver_q():
                    turn = Turn.active
                    saved_facet = turn._facet
                    for (facet, action) in q:
                        turn._facet = facet
                        action()
                    turn._facet = saved_facet
                return lambda: Turn.run(actor.root, deliver_q)
            queue_task(make_deliver_q(actor, q))
        self.queues = {}

def stop_if_inert_after(action):
    def wrapped_action():
        turn = Turn.active
        action()
        def check_action():
            if (turn._facet.parent is not None and not turn._facet.parent.alive) \
               or turn._facet.isinert():
                turn.stop()
        turn._enqueue(turn._facet, check_action)
    return wrapped_action

class DataflowPublication:
    def __init__(self, assertion_function):
        self.assertion_function = assertion_function
        self.handle = None
        self.target = None
        self.assertion = None

    def update(self):
        (next_target, next_assertion) = self.assertion_function() or (None, None)
        if next_target != self.target or next_assertion != self.assertion_function:
            self.target = next_target
            self.assertion = next_assertion
            self.handle = Turn.active.replace(self.target, self.handle, self.assertion)

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
    def on_publish(self, v, handle):
        pass

    def on_retract(self, handle):
        pass

    def on_message(self, v):
        pass

    def on_sync(self, peer):
        Turn.active.send(peer, True)

_inert_actor = None
_inert_facet = None
_inert_ref = None
_inert_entity = Entity()
def __boot_inert():
    global _inert_actor, _inert_facet, _inert_ref
    _inert_actor = Turn.active._facet.actor
    _inert_facet = Turn.active._facet
    _inert_ref = Turn.active.ref(_inert_entity)
async def __run_inert():
    Actor(__boot_inert, name = '_inert_actor')
def __setup_inert():
    def setup_main():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(__run_inert())
        loop.close()
    t = threading.Thread(target=setup_main)
    t.start()
    t.join()
__setup_inert()
