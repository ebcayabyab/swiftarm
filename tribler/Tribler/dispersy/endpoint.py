# Python 2.5 features
from __future__ import with_statement

import errno
import select
import socket
import sys
import threading
from time import time

from candidate import Candidate
from traceback import print_exc

if __debug__:
    from dprint import dprint

if sys.platform == 'win32':
    SOCKET_BLOCK_ERRORCODE = 10035    # WSAEWOULDBLOCK
else:
    import errno
    SOCKET_BLOCK_ERRORCODE = errno.EWOULDBLOCK

TUNNEL_PREFIX = "ffffffff".decode("HEX")
DEBUG = False

class Endpoint(object):
    def __init__(self):
        self._total_up = 0
        self._total_down = 0

    @property
    def total_up(self):
        return self._total_up

    @property
    def total_down(self):
        return self._total_down

    def get_address(self):
        raise NotImplementedError()

    def send(self, candidates, packets):
        raise NotImplementedError()

class DummyEndpoint(Endpoint):
    """
    A dummy socket class.

    When Dispersy starts it does not yet have an endpoint object, however, it may (under certain
    conditions) start sending packets anyway.

    To avoid problems we initialize the Dispersy socket to this dummy object that will do nothing
    but throw away all packets it is supposed to sent.
    """
    def get_address(self):
        return ("0.0.0.0", 0)

    def send(self, candidates, packets):
        if __debug__: dprint("Thrown away ", sum(len(data) for data in packets), " bytes worth of outgoing data to ", ",".join(str(candidate) for candidate in candidates), level="warning")

class StandaloneEndpoint(Endpoint):
    def __init__(self, dispersy, port, ip="0.0.0.0"):
        super(StandaloneEndpoint, self).__init__()
        self._running = True
        self._dispersy = dispersy
        self._thread = threading.Thread(name="StandaloneEndpoint", target=self._loop, args=(port, ip))
        self._thread.daemon = True

        while True:
            try:
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 870400)
                self._socket.bind((ip, port))
                self._socket.setblocking(0)
                if __debug__: dprint("Listening at ", port, force=True)
            except socket.error:
                port += 1
                continue
            break

    def get_address(self):
        return self._socket.getsockname()

    def start(self):
        self._thread.start()

    def stop(self, timeout=10.0):
        self._running = False
        self._thread.join(timeout)

    def _loop(self, port, ip):
        recvfrom = self._socket.recvfrom
        register = self._dispersy.callback.register
        dispersythread_data_came_in = self.dispersythread_data_came_in
        POLLIN, POLLOUT = select.POLLIN, select.POLLOUT
        poll = select.poll()
        poll.register(self._socket, POLLIN)
        do_poll = poll.poll

        while self._running:
            for _, event in do_poll(1.0):
                if event & POLLIN:
                    packets = []
                    try:
                        while True:
                            (data, sock_addr) = recvfrom(65535)
                            packets.append((sock_addr, data))
                    except socket.error:
                        pass

                    finally:
                        if packets:
                            if __debug__:
                                if DEBUG:
                                    for sock_addr, data in packets:
                                        try:
                                            name = self._dispersy.convert_packet_to_meta_message(data, load=False, auto_load=False).name
                                        except:
                                            name = "???"
                                        print >> sys.stderr, "endpoint: %.1f %30s <- %15s:%-5d %4d bytes" % (time(), name, sock_addr[0], sock_addr[1], len(data))

                            self._total_down += sum(len(data) for _, data in packets)
                            register(dispersythread_data_came_in, (packets,))

    def dispersythread_data_came_in(self, packets):
        self._dispersy.on_incoming_packets([(Candidate(sock_addr, False), data) for sock_addr, data in packets])

    def send(self, candidates, packets):
        assert isinstance(candidates, (tuple, list, set)), type(candidates)
        assert all(isinstance(candidate, Candidate) for candidate in candidates)
        assert isinstance(packets, (tuple, list, set)), type(packets)
        assert all(isinstance(packet, str) for packet in packets)
        assert all(len(packet) > 0 for packet in packets)

        self._total_up += sum(len(data) for data in packets) * len(candidates)
        wan_address = self._dispersy.wan_address

        for candidate in candidates:
            sock_addr = candidate.get_destination_address(wan_address)
            assert self._dispersy.is_valid_remote_address(sock_addr)

            for data in packets:
                if __debug__:
                    if DEBUG:
                        try:
                            name = self._dispersy.convert_packet_to_meta_message(data, load=False, auto_load=False).name
                        except:
                            name = "???"
                        print >> sys.stderr, "endpoint: %.1f %30s -> %15s:%-5d %4d bytes" % (time(), name, sock_addr[0], sock_addr[1], len(data))

                if candidate.tunnel:
                    data = TUNNEL_PREFIX + data
                try:
                    self._socket.sendto(data, sock_addr)
                except socket.error:
                    return False

        # return True when something has been send
        return candidates and packets

class RawserverEndpoint(Endpoint):
    def __init__(self, rawserver, dispersy, port, ip="0.0.0.0"):
        super(RawserverEndpoint, self).__init__()

        while True:
            try:
                self._socket = rawserver.create_udpsocket(port, ip)
                if __debug__: dprint("Dispersy listening at ", port, force=True)
            except socket.error:
                port += 1
                continue
            break

        self._rawserver = rawserver
        self._rawserver.start_listening_udp(self._socket, self)
        self._dispersy = dispersy
        self._sendqueue_lock = threading.Lock()
        self._sendqueue = []

    def get_address(self):
        return self._socket.getsockname()

    def data_came_in(self, packets):
        # called on the Tribler rawserver

        # the rawserver SUCKS.  every now and then exceptions are not shown and apparently we are
        # sometimes called without any packets...
        if packets:
            self._total_down += sum(len(data) for _, data in packets)

            if __debug__:
                if DEBUG:
                    for sock_addr, data in packets:
                        try:
                            name = self._dispersy.convert_packet_to_meta_message(data, load=False, auto_load=False).name
                        except:
                            name = "???"
                        print >> sys.stderr, "endpoint: %.1f %30s <- %15s:%-5d %4d bytes" % (time(), name, sock_addr[0], sock_addr[1], len(data))
            self._dispersy.callback.register(self.dispersythread_data_came_in, (packets, time()))

    def dispersythread_data_came_in(self, packets, timestamp):
        # iterator = ((self._dispersy.get_candidate(sock_addr), data.startswith(TUNNEL_PREFIX), sock_addr, data) for sock_addr, data in packets)
        # self._dispersy.on_incoming_packets([(candidate if candidate else self._dispersy.create_candidate(WalkCandidate, sock_addr, tunnel), data[4:] if tunnel else data)
        #                                     for candidate, tunnel, sock_addr, data
        #                                     in iterator],
        #                                    True,
        #                                    timestamp)
        iterator = ((data.startswith(TUNNEL_PREFIX), sock_addr, data) for sock_addr, data in packets)
        self._dispersy.on_incoming_packets([(Candidate(sock_addr, tunnel), data[4:] if tunnel else data)
                                            for tunnel, sock_addr, data
                                            in iterator],
                                           True,
                                           timestamp)

    def send(self, candidates, packets):
        assert isinstance(candidates, (tuple, list, set)), type(candidates)
        assert all(isinstance(candidate, Candidate) for candidate in candidates)
        assert isinstance(packets, (tuple, list, set)), type(packets)
        assert all(isinstance(packet, str) for packet in packets)
        assert all(len(packet) > 0 for packet in packets)

        self._total_up += sum(len(data) for data in packets) * len(candidates)
        wan_address = self._dispersy.wan_address

        with self._sendqueue_lock:
            for candidate in candidates:
                sock_addr = candidate.get_destination_address(wan_address)
                assert self._dispersy.is_valid_remote_address(sock_addr)

                for data in packets:
                    if __debug__:
                        if DEBUG:
                            try:
                                name = self._dispersy.convert_packet_to_meta_message(data, load=False, auto_load=False).name
                            except:
                                name = "???"
                            print >> sys.stderr, "endpoint: %.1f %30s -> %15s:%-5d %4d bytes" % (time(), name, sock_addr[0], sock_addr[1], len(data))

                    if candidate.tunnel:
                        data = TUNNEL_PREFIX + data

                    if self._sendqueue:
                        self._sendqueue.append((data, sock_addr))

                    else:
                        try:
                            self._socket.sendto(data, sock_addr)
                        except socket.error, e:
                            if e[0] == SOCKET_BLOCK_ERRORCODE:
                                self._sendqueue.append((data, sock_addr))
                                print >> sys.stderr, time(), "sendqueue overflowing", len(self._sendqueue), "(first schedule)"
                                self._rawserver.add_task(self._process_sendqueue, 0.1)

            # return True when something has been send
            return candidates and packets

    def _process_sendqueue(self):
        print >> sys.stderr, time(), "sendqueue overflowing", len(self._sendqueue)

        with self._sendqueue_lock:
            while self._sendqueue:
                data, sock_addr = self._sendqueue.pop(0)
                try:
                    self._socket.sendto(data, sock_addr)

                except socket.error, e:
                    if e[0] == SOCKET_BLOCK_ERRORCODE:
                        self._sendqueue.insert(0, (data, sock_addr))
                        self._rawserver.add_task(self._process_sendqueue, 0.1)
                        break
                    else:
                        print_exc()

class TunnelEndpoint(Endpoint):
    def __init__(self, swift_process, dispersy):
        super(TunnelEndpoint, self).__init__()
        self._swift = swift_process
        self._dispersy = dispersy
        self._session = "ffffffff".decode("HEX")

    def get_def(self):
        class DummyDef(object):
            def get_roothash(self):
                return "dispersy"
            def get_roothash_as_hex(self):
                return "dispersy".encode("HEX")
        return DummyDef()

    def get_address(self):
        return ("0.0.0.0", self._swift.listenport)

    def send(self, candidates, packets):
        assert isinstance(candidates, (tuple, list, set)), type(candidates)
        assert all(isinstance(candidate, Candidate) for candidate in candidates)
        assert isinstance(packets, (tuple, list, set)), type(packets)
        assert all(isinstance(packet, str) for packet in packets)
        assert all(len(packet) > 0 for packet in packets)

        self._total_up += sum(len(data) for data in packets) * len(candidates)
        wan_address = self._dispersy.wan_address

        self._swift.splock.acquire()
        try:
            for candidate in candidates:
                sock_addr = candidate.get_destination_address(wan_address)
                assert self._dispersy.is_valid_remote_address(sock_addr)

                for data in packets:
                    if __debug__:
                        if DEBUG:
                            try:
                                name = self._dispersy.convert_packet_to_meta_message(data, load=False, auto_load=False).name
                            except:
                                name = "???"
                            print >> sys.stderr, "endpoint: %.1f %30s -> %15s:%-5d %4d bytes" % (time(), name, sock_addr[0], sock_addr[1], len(data))
                    self._swift.send_tunnel(self._session, sock_addr, data)

            # return True when something has been send
            return candidates and packets

        finally:
            self._swift.splock.release()

    def i2ithread_data_came_in(self, session, sock_addr, data):
        # assert session == self._session, [session, self._session]
        if __debug__:
            if DEBUG:
                try:
                    name = self._dispersy.convert_packet_to_meta_message(data, load=False, auto_load=False).name
                except:
                    name = "???"
                print >> sys.stderr, "endpoint: %.1f %30s <- %15s:%-5d %4d bytes" % (time(), name, sock_addr[0], sock_addr[1], len(data))
        self._total_down += len(data)
        self._dispersy.callback.register(self.dispersythread_data_came_in, (sock_addr, data, time()))

    def dispersythread_data_came_in(self, sock_addr, data, timestamp):
        # candidate = self._dispersy.get_candidate(sock_addr) or self._dispersy.create_candidate(WalkCandidate, sock_addr, True)
        self._dispersy.on_incoming_packets([(Candidate(sock_addr, True), data)], True, timestamp)
