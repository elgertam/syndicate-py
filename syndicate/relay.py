import sys
import asyncio
import websockets
import logging

from preserves import Embedded, stringify
from preserves.fold import map_embeddeds

from . import actor, encode, transport, Decoder, gatekeeper
from .during import During
from .actor import _inert_ref, Turn
from .idgen import IdGenerator
from .schema import externalProtocol as protocol, sturdy, transportAddress

class InboundAssertion:
    def __init__(self, remote_handle, local_handle, wire_symbols):
        self.remote_handle = remote_handle
        self.local_handle = local_handle
        self.wire_symbols = wire_symbols

_next_local_oid = IdGenerator()

class WireSymbol:
    def __init__(self, oid, ref):
        self.oid = oid
        self.ref = ref
        self.count = 0

    def __repr__(self):
        return '<ws:%d/%d:%r>' % (self.oid, self.count, self.ref)

class Membrane:
    def __init__(self):
        self.oid_map = {}
        self.ref_map = {}

    def _get(self, map, key, is_transient, ws_maker):
        ws = map.get(key, None)
        if ws is None:
            ws = ws_maker()
            self.oid_map[ws.oid] = ws
            self.ref_map[ws.ref] = ws
        if not is_transient:
            ws.count = ws.count + 1
        return ws

    def get_ref(self, local_ref, is_transient, ws_maker):
        return self._get(self.ref_map, local_ref, is_transient, ws_maker)

    def get_oid(self, remote_oid, ws_maker):
        return self._get(self.oid_map, remote_oid, False, ws_maker)

    def drop(self, ws):
        ws.count = ws.count - 1
        if ws.count == 0:
            del self.oid_map[ws.oid]
            del self.ref_map[ws.ref]

# There are other kinds of relay. This one has exactly two participants connected to each other.
class TunnelRelay:
    def __init__(self,
                 turn,
                 address,
                 gatekeeper_peer = None,
                 gatekeeper_oid = 0,
                 on_connected = None,
                 on_disconnected = None,
                 ):
        self.facet = turn._facet
        self.facet.on_stop(self._shutdown)
        self.address = address
        self.gatekeeper_peer = gatekeeper_peer
        self.gatekeeper_oid = gatekeeper_oid
        self._reset()
        self.facet.linked_task(
            lambda facet: self._reconnecting_main(asyncio.get_running_loop(),
                                                  on_connected = on_connected,
                                                  on_disconnected = on_disconnected))

    def _reset(self):
        self.inbound_assertions = {} # map remote handle to InboundAssertion
        self.outbound_assertions = {} # map local handle to wire_symbols
        self.exported_references = Membrane()
        self.imported_references = Membrane()
        self.pending_turn = []
        self._connected = False
        self.gatekeeper_handle = None

    @property
    def connected(self):
        return self._connected

    def _shutdown(self, turn):
        self._disconnect()

    def deregister(self, handle):
        for ws in self.outbound_assertions.pop(handle, ()):
            self.exported_references.drop(ws)

    def _lookup(self, local_oid):
        ws = self.exported_references.oid_map.get(local_oid, None)
        return _inert_ref if ws is None else ws.ref

    def register(self, assertion, maybe_handle):
        exported = []
        rewritten = map_embeddeds(
            lambda r: Embedded(self.rewrite_ref_out(r, maybe_handle is None, exported)),
            assertion)
        if maybe_handle is not None:
            self.outbound_assertions[maybe_handle] = exported
        return rewritten

    def rewrite_ref_out(self, r, is_transient, exported):
        if isinstance(r.entity, RelayEntity) and r.entity.relay == self:
            # TODO attenuation
            return sturdy.WireRef.yours(sturdy.Oid(r.entity.oid), ())
        else:
            ws = self.exported_references.get_ref(
                r, is_transient, lambda: WireSymbol(next(_next_local_oid), r))
            exported.append(ws)
            return sturdy.WireRef.mine(sturdy.Oid(ws.oid))

    def rewrite_in(self, turn, assertion):
        imported = []
        rewritten = map_embeddeds(
            lambda wire_ref: Embedded(self.rewrite_ref_in(turn, wire_ref, imported)),
            assertion)
        return (rewritten, imported)

    def rewrite_ref_in(self, turn, wire_ref, imported):
        if wire_ref.VARIANT.name == 'mine':
            oid = wire_ref.oid.value
            ws = self.imported_references.get_oid(
                oid, lambda: WireSymbol(oid, turn.ref(RelayEntity(self, oid))))
            imported.append(ws)
            return ws.ref
        else:
            oid = wire_ref.oid.value
            local_ref = self._lookup(oid)
            attenuation = wire_ref.attenuation
            if len(attenuation) > 0:
                raise NotImplementedError('Non-empty attenuations not yet implemented') # TODO
            return local_ref

    def _on_disconnected(self):
        self._connected = False
        def retract_inbound(turn):
            for ia in self.inbound_assertions.values():
                turn.retract(ia.local_handle)
            if self.gatekeeper_handle is not None:
                turn.retract(self.gatekeeper_handle)
            self._reset()
        Turn.run(self.facet, retract_inbound)
        self._disconnect()

    def _on_connected(self):
        self._connected = True
        if self.gatekeeper_peer is not None:
            def connected_action(turn):
                gk = self.rewrite_ref_in(turn,
                                         sturdy.WireRef.mine(sturdy.Oid(self.gatekeeper_oid)),
                                         [])
                self.gatekeeper_handle = turn.publish(self.gatekeeper_peer, Embedded(gk))
            Turn.run(self.facet, connected_action)

    def _on_event(self, v):
        Turn.run(self.facet, lambda turn: self._handle_event(turn, v))

    def _handle_event(self, turn, v):
        packet = protocol.Packet.decode(v)
        variant = packet.VARIANT.name
        if variant == 'Turn': self._handle_turn_events(turn, packet.value.value)
        elif variant == 'Error': self._on_error(turn, packet.value.message, packet.value.detail)

    def _on_error(self, turn, message, detail):
        self.facet.log.error('Error from server: %r (detail: %r)', message, detail)
        self._disconnect()

    def _handle_turn_events(self, turn, events):
        for e in events:
            ref = self._lookup(e.oid.value)
            event = e.event
            variant = event.VARIANT.name
            if variant == 'Assert':
                self._handle_publish(turn, ref, event.value.assertion.value, event.value.handle.value)
            elif variant == 'Retract':
                self._handle_retract(turn, ref, event.value.handle.value)
            elif variant == 'Message':
                self._handle_message(turn, ref, event.value.body.value)
            elif variant == 'Sync':
                self._handle_sync(turn, ref, event.value.peer)

    def _handle_publish(self, turn, ref, assertion, remote_handle):
        (assertion, imported) = self.rewrite_in(turn, assertion)
        self.inbound_assertions[remote_handle] = \
            InboundAssertion(remote_handle, turn.publish(ref, assertion), imported)

    def _handle_retract(self, turn, ref, remote_handle):
        ia = self.inbound_assertions.pop(remote_handle, None)
        if ia is None:
            raise ValueError('Peer retracted invalid handle %s' % (remote_handle,))
        for ws in ia.wire_symbols:
            self.imported_references.drop(ws)
        turn.retract(ia.local_handle)

    def _handle_message(self, turn, ref, message):
        (message, imported) = self.rewrite_in(turn, message)
        if len(imported) > 0:
            raise ValueError('Cannot receive transient reference')
        turn.send(ref, message)

    def _handle_sync(self, turn, ref, wire_peer):
        imported = []
        peer = self.rewrite_ref_in(turn, wire_peer, imported)
        def done(turn):
            turn.send(peer, True)
            for ws in imported:
                self.imported_references.drop(ws)
        turn.sync(ref, done)

    def _send(self, remote_oid, turn_event):
        if len(self.pending_turn) == 0:
            def flush_pending(turn):
                packet = protocol.Packet.Turn(protocol.Turn(self.pending_turn))
                self.pending_turn = []
                self._send_bytes(encode(packet))
            actor.queue_task(lambda: Turn.run(self.facet, flush_pending))
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
    def from_str(turn, conn_str, **kwargs):
        return transport.connection_from_str(turn, conn_str, **kwargs)

# decorator
def connect(turn, conn_str, cap, **kwargs):
    def prepare_resolution_handler(handler):
        @During().add_handler
        def handle_gatekeeper(turn, gk):
            gatekeeper.resolve(turn, gk.embeddedValue, cap)(handler)
        return transport.connection_from_str(
            turn,
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

    def on_publish(self, turn, assertion, handle):
        self._send(protocol.Event.Assert(protocol.Assert(
            protocol.Assertion(self.relay.register(assertion, handle)),
            protocol.Handle(handle))))

    def on_retract(self, turn, handle):
        self.relay.deregister(handle)
        self._send(protocol.Event.Retract(protocol.Retract(protocol.Handle(handle))))

    def on_message(self, turn, message):
        self._send(protocol.Event.Message(protocol.Message(
            protocol.Assertion(self.relay.register(message, None)))))

    def on_sync(self, turn, peer):
        exported = []
        entity = SyncPeerEntity(self.relay, peer, exported)
        rewritten = Embedded(self.relay.rewrite_ref_out(turn.ref(entity), False, exported))
        self._send(protocol.Event.Sync(protocol.Sync(rewritten)))

class SyncPeerEntity(actor.Entity):
    def __init__(self, relay, peer, exported):
        self.relay = relay
        self.peer = peer
        self.exported = exported

    def on_message(self, turn, body):
        self.relay.exported_references.drop(self.exported[0])
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
    def __init__(self, turn, address, **kwargs):
        super().__init__(turn, address, **kwargs)
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
    def __init__(self, turn, address, **kwargs):
        super().__init__(turn, address, **kwargs)
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
    def __init__(self, turn, address, input_fileobj = sys.stdin, output_fileobj = sys.stdout, **kwargs):
        super().__init__(turn, address, **kwargs)
        self.input_fileobj = input_fileobj
        self.output_fileobj = output_fileobj
        self.reader = asyncio.StreamReader()

    async def _create_connection(self, loop):
        return await loop.connect_read_pipe(lambda: self, self.input_fileobj)

    def _send_bytes(self, bs):
        self.output_fileobj.buffer.write(bs)
        self.output_fileobj.buffer.flush()
