import sys
import asyncio
import websockets
import logging

from preserves import Embedded, stringify
from preserves.fold import map_embeddeds

from . import actor, encode, transport, Decoder, gatekeeper, turn
from .during import During
from .actor import _inert_ref
from .idgen import IdGenerator
from .schema import protocol, sturdy, transportAddress

class InboundAssertion:
    def __init__(self, remote_handle, local_handle, pins):
        self.remote_handle = remote_handle
        self.local_handle = local_handle
        self.pins = pins

class WireSymbol:
    def __init__(self, oid, ref, membrane):
        self.oid = oid
        self.ref = ref
        self.membrane = membrane
        self.count = 0

    def __repr__(self):
        return '<ws:%d/%d:%r>' % (self.oid, self.count, self.ref)

    def grab(self, pins):
        self.count = self.count + 1
        pins.append(self)

    def drop(self):
        self.count = self.count - 1
        if self.count == 0:
            del self.membrane.oid_map[self.oid]
            del self.membrane.ref_map[self.ref]

class Membrane:
    def __init__(self):
        self.oid_map = {}
        self.ref_map = {}

    def _get(self, pins, map, key, is_transient, ws_maker):
        ws = map.get(key, None)
        if ws is None and ws_maker is not None:
            ws = ws_maker()
            self.oid_map[ws.oid] = ws
            self.ref_map[ws.ref] = ws
        if not is_transient and ws is not None:
            ws.grab(pins)
        return ws

    def get_ref(self, pins, local_ref, is_transient, ws_maker):
        return self._get(pins, self.ref_map, local_ref, is_transient, ws_maker)

    def get_oid(self, pins, remote_oid, ws_maker):
        return self._get(pins, self.oid_map, remote_oid, False, ws_maker)

def drop_all(wss):
    for ws in wss:
        ws.drop()

# There are other kinds of relay. This one has exactly two participants connected to each other.
class TunnelRelay:
    def __init__(self,
                 address,
                 gatekeeper_peer = None,
                 gatekeeper_oid = 0,
                 publish_service = None,
                 publish_oid = 0,
                 on_connected = None,
                 on_disconnected = None,
                 ):
        self.facet = turn.active_facet()
        self.facet.on_stop(self._shutdown)
        self.address = address
        self.gatekeeper_peer = gatekeeper_peer
        self.gatekeeper_oid = gatekeeper_oid
        self.publish_service = publish_service
        self.publish_oid = publish_oid
        self._reset()
        self.facet.linked_task(
            lambda facet: self._reconnecting_main(asyncio.get_running_loop(),
                                                  on_connected = on_connected,
                                                  on_disconnected = on_disconnected))

    def _reset(self):
        self.inbound_assertions = {} # map remote handle to InboundAssertion
        self.outbound_assertions = {} # map local handle to `WireSymbol`s
        self.exported_references = Membrane()
        self.imported_references = Membrane()
        self.pending_turn = []
        self._connected = False
        self.gatekeeper_handle = None
        if self.publish_service is None:
            self.next_local_oid = IdGenerator(initial_value=0)
        else:
            self.next_local_oid = IdGenerator(initial_value=(self.publish_oid + 1))
            # Very specific specialization of logic in rewrite_ref_out
            ws = WireSymbol(self.publish_oid, self.publish_service, self.exported_references)
            self.exported_references.get_ref([], self.publish_service, False, lambda: ws)

    @property
    def connected(self):
        return self._connected

    def _shutdown(self):
        self._disconnect()

    def deregister(self, handle):
        drop_all(self.outbound_assertions.pop(handle, ()))

    def _lookup_exported_oid(self, local_oid, pins):
        ws = self.exported_references.get_oid(pins, local_oid, None)
        if ws is None:
            return _inert_ref
        return ws.ref

    def register_imported_oid(self, remote_oid, pins):
        self.imported_references.get_oid(pins, remote_oid, None)

    def register(self, target_oid, assertion, maybe_handle):
        pins = []
        self.register_imported_oid(target_oid, pins)
        rewritten = map_embeddeds(
            lambda r: Embedded(self.rewrite_ref_out(r, maybe_handle is None, pins)),
            assertion)
        if maybe_handle is not None:
            self.outbound_assertions[maybe_handle] = pins
        return rewritten

    def rewrite_ref_out(self, r, is_transient, pins):
        if isinstance(r.entity, RelayEntity) and r.entity.relay == self:
            # TODO attenuation
            return sturdy.WireRef.yours(sturdy.Oid(r.entity.oid), ())
        else:
            ws = self.exported_references.get_ref(
                pins, r, is_transient, lambda: WireSymbol(next(self.next_local_oid), r,
                                                          self.exported_references))
            return sturdy.WireRef.mine(sturdy.Oid(ws.oid))

    def rewrite_in(self, assertion, pins):
        rewritten = map_embeddeds(
            lambda wire_ref: Embedded(self.rewrite_ref_in(wire_ref, pins)),
            assertion)
        return rewritten

    def rewrite_ref_in(self, wire_ref, pins):
        if wire_ref.VARIANT.name == 'mine':
            oid = wire_ref.oid.value
            ws = self.imported_references.get_oid(
                pins, oid, lambda: WireSymbol(oid, turn.ref(RelayEntity(self, oid)),
                                              self.imported_references))
            return ws.ref
        else:
            oid = wire_ref.oid.value
            local_ref = self._lookup_exported_oid(oid, pins)
            attenuation = wire_ref.attenuation
            if len(attenuation) > 0:
                raise NotImplementedError('Non-empty attenuations not yet implemented') # TODO
            return local_ref

    def _on_disconnected(self):
        self._connected = False
        def retract_inbound():
            for ia in self.inbound_assertions.values():
                turn.retract(ia.local_handle)
            if self.gatekeeper_handle is not None:
                turn.retract(self.gatekeeper_handle)
            self._reset()
        turn.run(self.facet, retract_inbound)
        self._disconnect()

    def _on_connected(self):
        self._connected = True
        if self.gatekeeper_peer is not None:
            def connected_action():
                gk = self.rewrite_ref_in(sturdy.WireRef.mine(sturdy.Oid(self.gatekeeper_oid)), [])
                self.gatekeeper_handle = turn.publish(self.gatekeeper_peer, Embedded(gk))
            turn.run(self.facet, connected_action)

    def _on_event(self, v):
        turn.run(self.facet, lambda: self._handle_event(v))

    def _handle_event(self, v):
        packet = protocol.Packet.decode(v)
        variant = packet.VARIANT.name
        if variant == 'Turn': self._handle_turn_events(packet.value.value)
        elif variant == 'Error': self._on_error(packet.value.message, packet.value.detail)

    def _on_error(self, message, detail):
        self.facet.log.error('Error from server: %r (detail: %r)', message, detail)
        self._disconnect()

    def _handle_turn_events(self, events):
        for e in events:
            pins = []
            ref = self._lookup_exported_oid(e.oid.value, pins)
            event = e.event
            variant = event.VARIANT.name
            if variant == 'Assert':
                self._handle_publish(pins, ref, event.value.assertion.value, event.value.handle.value)
            elif variant == 'Retract':
                self._handle_retract(pins, ref, event.value.handle.value)
            elif variant == 'Message':
                self._handle_message(pins, ref, event.value.body.value)
            elif variant == 'Sync':
                self._handle_sync(pins, ref, event.value.peer)

    def _handle_publish(self, pins, ref, assertion, remote_handle):
        assertion = self.rewrite_in(assertion, pins)
        self.inbound_assertions[remote_handle] = \
            InboundAssertion(remote_handle, turn.publish(ref, assertion), pins)

    def _handle_retract(self, pins, ref, remote_handle):
        ia = self.inbound_assertions.pop(remote_handle, None)
        if ia is None:
            raise ValueError('Peer retracted invalid handle %s' % (remote_handle,))
        drop_all(ia.pins)
        drop_all(pins)
        turn.retract(ia.local_handle)

    def _handle_message(self, pins, ref, message):
        message = self.rewrite_in(message, pins)
        for ws in pins:
            if ws.count == 1:
                raise ValueError('Cannot receive transient reference')
        turn.send(ref, message)
        drop_all(pins)

    def _handle_sync(self, pins, ref, wire_peer):
        peer = self.rewrite_ref_in(wire_peer, pins)
        def done():
            turn.send(peer, True)
            drop_all(pins)
        turn.sync(ref, done)

    def _send(self, remote_oid, turn_event):
        if len(self.pending_turn) == 0:
            def flush_pending():
                packet = protocol.Packet.Turn(protocol.Turn(self.pending_turn))
                self.pending_turn = []
                self._send_bytes(encode(packet))
            actor.queue_task(lambda: turn.run(self.facet, flush_pending))
        self.pending_turn.append(protocol.TurnEvent(protocol.Oid(remote_oid), turn_event))

    def _send_bytes(self, bs):
        raise Exception('subclassresponsibility')

    def _disconnect(self):
        raise Exception('subclassresponsibility')

    async def _reconnecting_main(self, loop, on_connected=None, on_disconnected=None):
        should_run = True
        while should_run and self.facet.alive:
            did_connect = await self.main(loop, on_connected=(on_connected or _default_on_connected))
            should_run = await (on_disconnected or _default_on_disconnected)(self, did_connect)

    @staticmethod
    def from_str(conn_str, **kwargs):
        return transport.connection_from_str(conn_str, **kwargs)

# decorator
def connect(conn_str, cap, **kwargs):
    def prepare_resolution_handler(handler):
        @During().add_handler
        def handle_gatekeeper(gk):
            gatekeeper.resolve(gk.embeddedValue, cap)(handler)
        return transport.connection_from_str(
            conn_str,
            gatekeeper_peer = turn.ref(handle_gatekeeper),
            **kwargs)
    return prepare_resolution_handler

class RelayEntity(actor.Entity):
    def __init__(self, relay, oid):
        self.relay = relay
        self.oid = oid

    def __repr__(self):
        return '<Relay %s %s>' % (stringify(self.relay.address), self.oid)

    def _send(self, e):
        self.relay._send(self.oid, e)

    def on_publish(self, assertion, handle):
        self._send(protocol.Event.Assert(protocol.Assert(
            protocol.Assertion(self.relay.register(self.oid, assertion, handle)),
            protocol.Handle(handle))))

    def on_retract(self, handle):
        self.relay.deregister(handle)
        self._send(protocol.Event.Retract(protocol.Retract(protocol.Handle(handle))))

    def on_message(self, message):
        self._send(protocol.Event.Message(protocol.Message(
            protocol.Assertion(self.relay.register(self.oid, message, None)))))

    def on_sync(self, peer):
        pins = []
        self.relay.register_imported_oid(self.oid, pins)
        entity = SyncPeerEntity(self.relay, peer, pins)
        rewritten = Embedded(self.relay.rewrite_ref_out(turn.ref(entity), False, pins))
        self._send(protocol.Event.Sync(protocol.Sync(rewritten)))

class SyncPeerEntity(actor.Entity):
    def __init__(self, relay, peer, pins):
        self.relay = relay
        self.peer = peer
        self.pins = pins

    def on_message(self, body):
        drop_all(self.pins)
        turn.send(self.peer, body)

async def _default_on_connected(relay):
    relay.facet.log.info('Connected')

async def _default_on_disconnected(relay, did_connect):
    if did_connect:
        # Reconnect immediately
        relay.facet.log.info('Disconnected')
    else:
        await asyncio.sleep(2)
    return True

class _StreamTunnelRelay(TunnelRelay, asyncio.Protocol):
    def __init__(self, address, **kwargs):
        super().__init__(address, **kwargs)
        self.decoder = None
        self.stop_signal = None
        self.transport = None

    def connection_lost(self, exc):
        self._on_disconnected()

    def connection_made(self, transport):
        self.transport = transport
        self._on_connected()

    def data_received(self, chunk):
        self.decoder.extend(chunk)
        while True:
            v = self.decoder.try_next()
            if v is None: break
            self._on_event(v)

    def _send_bytes(self, bs):
        if self.transport:
            self.transport.write(bs)

    def _disconnect(self):
        if self.stop_signal:
            def set_stop_signal():
                try:
                    self.stop_signal.set_result(True)
                except:
                    pass
            self.stop_signal.get_loop().call_soon_threadsafe(set_stop_signal)

    async def _create_connection(self, loop):
        raise Exception('subclassresponsibility')

    async def main(self, loop, on_connected=None):
        if self.transport is not None:
            raise Exception('Cannot run connection twice!')

        self.decoder = Decoder(decode_embedded = sturdy.WireRef.decode)
        self.stop_signal = loop.create_future()
        try:
            _transport, _protocol = await self._create_connection(loop)
        except OSError as e:
            log.error('%s: Could not connect to server: %s' % (self.__class__.__qualname__, e))
            return False

        try:
            if on_connected: await on_connected(self)
            await self.stop_signal
            return True
        finally:
            self.transport.close()
            self.transport = None
            self.stop_signal = None
            self.decoder = None

@transport.address(transportAddress.Tcp)
class TcpTunnelRelay(_StreamTunnelRelay):
    async def _create_connection(self, loop):
        return await loop.create_connection(lambda: self, self.address.host, self.address.port)

@transport.address(transportAddress.Unix)
class UnixSocketTunnelRelay(_StreamTunnelRelay):
    async def _create_connection(self, loop):
        return await loop.create_unix_connection(lambda: self, self.address.path)

@transport.address(transportAddress.WebSocket)
class WebsocketTunnelRelay(TunnelRelay):
    def __init__(self, address, **kwargs):
        super().__init__(address, **kwargs)
        self.loop = None
        self.ws = None

    def _send_bytes(self, bs):
        if self.loop:
            def _do_send():
                if self.ws:
                    self.loop.create_task(self.ws.send(bs))
            self.loop.call_soon_threadsafe(_do_send)

    def _disconnect(self):
        if self.loop:
            def _do_disconnect():
                if self.ws:
                    self.loop.create_task(self.ws.close())
            self.loop.call_soon_threadsafe(_do_disconnect)

    def __connection_error(self, e):
        self.facet.log.error('Could not connect to server: %s' % (e,))
        return False

    async def main(self, loop, on_connected=None):
        if self.ws is not None:
            raise Exception('Cannot run connection twice!')

        self.loop = loop

        try:
            self.ws = await websockets.connect(self.address.url)
        except OSError as e:
            return self.__connection_error(e)
        except websockets.exceptions.InvalidHandshake as e:
            return self.__connection_error(e)

        try:
            if on_connected: await on_connected(self)
            self._on_connected()
            while True:
                chunk = await self.ws.recv()
                self._on_event(Decoder(chunk, decode_embedded = sturdy.WireRef.decode).next())
        except websockets.exceptions.WebSocketException:
            pass
        finally:
            self._on_disconnected()

        if self.ws:
            await self.ws.close()
        self.loop = None
        self.ws = None
        return True

@transport.address(transportAddress.Stdio)
class PipeTunnelRelay(_StreamTunnelRelay):
    def __init__(self, address, input_fileobj = sys.stdin, output_fileobj = sys.stdout, **kwargs):
        super().__init__(address, **kwargs)
        self.input_fileobj = input_fileobj
        self.output_fileobj = output_fileobj
        self.reader = asyncio.StreamReader()

    async def _create_connection(self, loop):
        return await loop.connect_read_pipe(lambda: self, self.input_fileobj)

    def _send_bytes(self, bs):
        self.output_fileobj.buffer.write(bs)
        self.output_fileobj.buffer.flush()

def run_stdio_service(entity):
    PipeTunnelRelay(transportAddress.Stdio(), publish_service=turn.ref(entity))

# decorator
def service(**kwargs):
    return lambda entity: \
        actor.start_actor_system(lambda: run_stdio_service(entity), **kwargs)
