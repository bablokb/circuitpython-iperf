# -----------------------------------------------------------------------------
# CircuitPython iperf3-library.
#
# Original code from Damien P. George.
#
# Adapted to CircuitPython with minor modifications by Bernhard Bablok
#
# See examples/server.py and examples/client.py for usage.
#
# Website: https://github.com/bablokb/circuitpython-iperf
#
# -----------------------------------------------------------------------------

"""
Pure Python, iperf3-compatible network performance test tool.

MIT license

Copyright (c) 2024-     Bernhard Bablok
Copyright (c) 2018-2019 Damien P. George

Supported modes: server & client, TCP & UDP, normal & reverse
"""

import os, struct
import time, select, wifi
from socketpool import SocketPool
import json

# add some functions not available in CircuitPython
if hasattr(time,'monotonic_ns'):
    TICKS_PER_SEC = 1_000_000_000
    def ticks():
        return time.monotonic_ns()
    def ticks_diff(arg1, arg2):
        return arg1-arg2
else:
    # only ms resolution available
    TICKS_PER_SEC = 1000
    _TICKS_PERIOD     = 1<<29
    _TICKS_MAX        = _TICKS_PERIOD-1
    _TICKS_HALFPERIOD = _TICKS_PERIOD//2

    import supervisor
    def ticks():
        return supervisor.ticks_ms()
    def ticks_diff(ticks1, ticks2):
        """ Compute the signed difference between two ticks values,
        assuming that they are within 2**28 ticks """
        diff = (ticks1 - ticks2) & _TICKS_MAX
        diff = ((diff + _TICKS_HALFPERIOD) & _TICKS_MAX) - _TICKS_HALFPERIOD
        return diff

def pollable_is_sock(pollable, sock):
    return pollable[0] == sock

# iperf3 cookie size, last byte is null byte
COOKIE_SIZE = 37

# iperf3 commands
TEST_START = 1
TEST_RUNNING = 2
TEST_END = 4
PARAM_EXCHANGE = 9
CREATE_STREAMS = 10
EXCHANGE_RESULTS = 13
DISPLAY_RESULTS = 14
IPERF_DONE = 16

cmd_string = {
    TEST_START: 'TEST_START',
    TEST_RUNNING: 'TEST_RUNNING',
    TEST_END: 'TEST_END',
    PARAM_EXCHANGE: 'PARAM_EXCHANGE',
    CREATE_STREAMS: 'CREATE_STREAMS',
    EXCHANGE_RESULTS: 'EXCHANGE_RESULTS',
    DISPLAY_RESULTS: 'DISPLAY_RESULTS',
    IPERF_DONE: 'IPERF_DONE',
    }

def fmt_size(val, div):
    for mult in ('', 'K', 'M', 'G'):
        if val < 10:
            return '% 5.2f %s' % (val, mult)
        elif val < 100:
            return '% 5.1f %s' % (val, mult)
        elif mult == 'G' or val < 1000:
            return '% 5.0f %s' % (val, mult)
        else:
            val /= div

class Stats:
    def __init__(self, param):
        # pacing_timer is in us, convert to our resolution
        self.pacing_timer = param['pacing_timer'] * (TICKS_PER_SEC/1e6)
        self.udp = param.get('udp', False)
        self.reverse = param.get('reverse', False)
        self.running = False

    def start(self):
        self.running = True
        self.t0 = self.t1 = ticks()
        self.nb0 = self.nb1 = 0 # num bytes
        self.np0 = self.np1 = 0 # num packets
        self.nm0 = self.nm1 = 0 # num lost packets
        if self.udp:
            if self.reverse:
                extra = '         Jitter    Lost/Total Datagrams'
            else:
                extra = '         Total Datagrams'
        else:
            extra = ''
        print('Interval           Transfer     Bitrate' + extra)

    def max_dt_ms(self):
        if not self.running:
            return -1
        return max(0,
                   (self.pacing_timer - ticks_diff(ticks(), self.t1)) //
                   (TICKS_PER_SEC/1000)
                   )

    def add_bytes(self, n):
        if not self.running:
            return
        self.nb0 += n
        self.nb1 += n
        self.np0 += 1
        self.np1 += 1

    def add_lost_packets(self, n):
        self.np0 += n
        self.np1 += n
        self.nm0 += n
        self.nm1 += n

    def print_line(self, ta, tb, nb, np, nm, extra=''):
        dt = tb - ta
        print(' %5.2f-%-5.2f  sec %sBytes %sbits/sec' % (ta, tb, fmt_size(nb, 1024), fmt_size(nb * 8 / dt, 1000)), end='')
        if self.udp:
            if self.reverse:
                print(' %6.3f ms  %u/%u (%.1f%%)' % (0, nm, np, 100 * nm / (max(1, np + nm))), end='')
            else:
                print('  %u' % np, end='')
        print(extra)

    def update(self, final=False):
        if not self.running:
            return
        t2 = ticks()
        dt = ticks_diff(t2, self.t1)
        if final or dt > self.pacing_timer:
            ta = ticks_diff(self.t1, self.t0) * TICKS_PER_SEC
            tb = ticks_diff(t2, self.t0) * TICKS_PER_SEC
            #self.print_line(ta, tb, self.nb1, self.np1, self.nm1)
            self.t1 = t2
            self.nb1 = 0
            self.np1 = 0
            self.nm1 = 0

    def stop(self):
        self.update(True)
        self.running = False
        self.t3 = ticks()
        dt = ticks_diff(self.t3, self.t0)
        print('- ' * 30)
        self.print_line(0, dt / TICKS_PER_SEC,
                        self.nb0, self.np0, self.nm0, '  sender')

    def report_receiver(self, stats):
        st = stats['streams'][0]
        dt = st['end_time'] - st['start_time']
        self.print_line(st['start_time'], st['end_time'], st['bytes'], st['packets'], st['errors'], '  receiver')
        return

def recvn(s, n):
    data = b''
    buf = bytearray(min(n,8192))
    while len(data) < n:
        n_bytes = s.recv_into(buf)
        data += buf[:n_bytes]
    return data

def recvinto(s, buf):
    if hasattr(s, 'readinto'):
        return s.readinto(buf)
    else:
        return s.recv_into(buf)

def recvninto(s, buf):
    if hasattr(s, 'readinto'):
        n = s.readinto(buf)
        assert n == len(buf)
    else:
        mv = memoryview(buf)
        off = 0
        while off < len(buf):
            off += s.recv_into(mv[off:])

def make_cookie():
    cookie_chars = b'abcdefghijklmnopqrstuvwxyz234567'
    cookie = bytearray(COOKIE_SIZE)
    for i, x in enumerate(os.urandom(COOKIE_SIZE - 1)):
        cookie[i] = cookie_chars[x & 31]
    return cookie

def server(debug=False):
    # Listen for a connection
    pool = SocketPool(wifi.radio)
    ai = pool.getaddrinfo('0.0.0.0', 5201)
    ai = ai[0]
    print('Server listening on', ai[-1])
    s_listen = pool.socket(ai[0], SocketPool.SOCK_STREAM)
    s_listen.setsockopt(SocketPool.SOL_SOCKET,
                        SocketPool.SO_REUSEADDR, 1)
    s_listen.bind(ai[-1])
    s_listen.listen(1)
    s_ctrl, addr = s_listen.accept()

    # Read client's cookie
    cookie = recvn(s_ctrl, COOKIE_SIZE)
    if debug:
        print(cookie)

    # Ask for parameters
    s_ctrl.sendall(bytes([PARAM_EXCHANGE]))

    # Get parameters
    n = struct.unpack('>I', recvn(s_ctrl, 4))[0]
    param = recvn(s_ctrl, n)
    param = json.loads(str(param, 'ascii'))
    if debug:
        print(param)
    reverse = param.get('reverse', False)

    # Ask to create streams
    s_ctrl.sendall(bytes([CREATE_STREAMS]))

    if param.get('tcp', False):
        # Accept stream
        s_data, addr = s_listen.accept()
        print('Accepted connection:', addr)
        recvn(s_data, COOKIE_SIZE)
    elif param.get('udp', False):
        # Close TCP connection and open UDP "connection"
        s_listen.close()
        s_data = pool.socket(ai[0], SocketPool.SOCK_DGRAM)
        s_data.bind(ai[-1])
        data, addr = s_data.recvfrom(4)
        s_data.sendto(b'\x12\x34\x56\x78', addr)
    else:
        assert False

    # Start test
    s_ctrl.sendall(bytes([TEST_START]))

    # Run test
    s_ctrl.sendall(bytes([TEST_RUNNING]))

    # Read data, and wait for client to send TEST_END
    poll = select.poll()
    poll.register(s_ctrl, select.POLLIN)
    if reverse:
        poll.register(s_data, select.POLLOUT)
    else:
        poll.register(s_data, select.POLLIN)
    stats = Stats(param)
    stats.start()
    running = True
    data_buf = bytearray(os.urandom(param['len']))
    while running:
        for pollable in poll.poll(stats.max_dt_ms()):
            if pollable_is_sock(pollable, s_ctrl):
                cmd = recvn(s_ctrl, 1)[0]
                if debug:
                    print(cmd_string.get(cmd, 'UNKNOWN_COMMAND'))
                if cmd == TEST_END:
                    running = False
            elif pollable_is_sock(pollable, s_data):
                if reverse:
                    n = s_data.send(data_buf)
                    stats.add_bytes(n)
                else:
                    recvninto(s_data, data_buf)
                    stats.add_bytes(len(data_buf))
        stats.update()

    # Need to continue writing so other side doesn't get blocked waiting for data
    if reverse:
        s_data.close()
    stats.stop()

    # Ask to exchange results
    s_ctrl.sendall(bytes([EXCHANGE_RESULTS]))

    # Get client results
    n = struct.unpack('>I', recvn(s_ctrl, 4))[0]
    results = recvn(s_ctrl, n)
    results = json.loads(str(results, 'ascii'))
    if debug:
        print(results)

    # Send our results
    results = { 
        'cpu_util_total': 1,
        'cpu_util_user': 0.5,
        'cpu_util_system': 0.5,
        'sender_has_retransmits': 1,
        'congestion_used': 'cubic',
        'streams': [{
            'id': 1,
            'bytes': stats.nb0,
            'retransmits': 0,
            'jitter': 0,
            'errors': 0,
            'packets': stats.np0,
            'start_time': 0,
            'end_time': ticks_diff(stats.t3, stats.t0) / TICKS_PER_SEC
        }]
    }
    results = json.dumps(results)
    s_ctrl.sendall(struct.pack('>I', len(results))) 
    s_ctrl.sendall(bytes(results, 'ascii'))

    # Ask to display results
    s_ctrl.sendall(bytes([DISPLAY_RESULTS]))

    # Wait for client to send IPERF_DONE
    cmd = recvn(s_ctrl, 1)[0]
    assert cmd == IPERF_DONE

    # Close all sockets
    s_data.close()
    s_ctrl.close()
    s_listen.close()

def client(host, debug=False, udp=False, reverse=False,
           bandwidth=10*1024*1024, length=None, ttime=10):
    print('CLIENT MODE:',
          'UDP' if udp else 'TCP', 'receiving' if reverse else 'sending')

    param = {
        'client_version': '3.6',
        'omit': 0,
        'parallel': 1,
        'pacing_timer':1000,
        'time': ttime,
        'bandwidth': bandwidth
    }

    if udp:
        param['udp'] = True
        param['len'] = 1500 - 42 if length is None else length
        udp_interval = TICKS_PER_SEC * 8 * param['len'] // bandwidth
    else:
        param['tcp'] = True
        param['len'] =  3000 if length is None else length

    if reverse:
        param['reverse'] = True

    # Connect to server
    pool = SocketPool(wifi.radio)
    ai = pool.getaddrinfo(host, 5201)[0]
    print('Connecting to', ai[-1])
    s_ctrl = pool.socket(ai[0], SocketPool.SOCK_STREAM)
    s_ctrl.connect(ai[-1])

    # Send our cookie
    cookie = make_cookie()
    if debug:
        print(f"Cookie: {cookie}")
    s_ctrl.sendall(cookie)

    # Object to gather statistics about the run
    stats = Stats(param)

    # Run the main loop, waiting for incoming commands and dat
    ticks_end = param['time'] * TICKS_PER_SEC
    poll = select.poll()
    poll.register(s_ctrl, select.POLLIN)
    s_data = None
    start = None
    udp_packet_id = 0
    while True:
        for pollable in poll.poll(stats.max_dt_ms()):
            if pollable_is_sock(pollable, s_data):
                # Data socket is writable/readable
                t = ticks()
                if ticks_diff(t, start) > ticks_end:
                    if reverse:
                        # Continue to drain any incoming data
                        recvinto(s_data, buf)
                    if stats.running:
                        # End of run
                        s_ctrl.sendall(bytes([TEST_END]))
                        stats.stop()
                else:
                    # Send/receiver data
                    if udp:
                        if reverse:
                            recvninto(s_data, buf)
                            udp_in_sec, udp_in_usec, udp_in_id = struct.unpack_from('>III', buf, 0)
                            #print(udp_in_sec, udp_in_usec, udp_in_id)
                            if udp_in_id != udp_packet_id + 1:
                                stats.add_lost_packets(udp_in_id - (udp_packet_id + 1))
                            udp_packet_id = udp_in_id
                            stats.add_bytes(len(buf))
                        else:
                            #print('UDP send', udp_last_send, t, udp_interval)
                            if t - udp_last_send > udp_interval:
                                udp_last_send += udp_interval
                                udp_packet_id += 1
                                struct.pack_into('>III', buf, 0, t // TICKS_PER_SEC, t % TICKS_PER_SEC, udp_packet_id)
                                n = s_data.sendto(buf, ai[-1])
                                stats.add_bytes(n)
                    else:
                        if reverse:
                            recvninto(s_data, buf)
                            n = len(buf)
                        else:
                            #print('TCP send', len(buf))
                            n = s_data.send(buf)
                        stats.add_bytes(n)

            elif pollable_is_sock(pollable, s_ctrl):
                # Receive command
                cmd = recvn(s_ctrl, 1)[0]
                if debug:
                    print(cmd_string.get(cmd, 'UNKNOWN_COMMAND'))
                if cmd == TEST_START:
                    if reverse:
                        # Start receiving data now, because data socket is open
                        poll.register(s_data, select.POLLIN)
                        start = ticks()
                        stats.start()
                elif cmd == TEST_RUNNING:
                    if not reverse:
                        # Start sending data now
                        poll.register(s_data, select.POLLOUT)
                        start = ticks()
                        if udp:
                            udp_last_send = start - udp_interval
                        stats.start()
                elif cmd == PARAM_EXCHANGE:
                    param_j = json.dumps(param)
                    s_ctrl.sendall(struct.pack('>I', len(param_j))) 
                    s_ctrl.sendall(bytes(param_j, 'ascii'))
                elif cmd == CREATE_STREAMS:
                    if udp:
                        s_data = pool.socket(ai[0], SocketPool.SOCK_DGRAM)
                        s_data.sendto(struct.pack('<I', 123456789), ai[-1])
                        recvn(s_data, 4) # get dummy response from server (=987654321)
                    else:
                        s_data = pool.socket(ai[0], SocketPool.SOCK_STREAM)
                        s_data.connect(ai[-1])
                        s_data.sendall(cookie)
                    buf = bytearray(os.urandom(param['len']))
                elif cmd == EXCHANGE_RESULTS:
                    # Close data socket now that server knows we are finished, to prevent it flooding us
                    poll.unregister(s_data)
                    s_data.close()
                    s_data = None

                    results = {
                        'cpu_util_total': 1,
                        'cpu_util_user': 0.5,
                        'cpu_util_system': 0.5,
                        'sender_has_retransmits': 1,
                        'congestion_used': 'cubic',
                        'streams': [{
                            'id': 1,
                            'bytes': stats.nb0,
                            'retransmits': 0,
                            'jitter': 0,
                            'errors': stats.nm0,
                            'packets': stats.np0,
                            'start_time': 0,
                            'end_time': ticks_diff(stats.t3, stats.t0) / TICKS_PER_SEC
                        }]
                    }
                    results = json.dumps(results)
                    s_ctrl.sendall(struct.pack('>I', len(results))) 
                    s_ctrl.sendall(bytes(results, 'ascii'))

                    n = struct.unpack('>I', recvn(s_ctrl, 4))[0]
                    results = recvn(s_ctrl, n)
                    results = json.loads(str(results, 'ascii'))
                    stats.report_receiver(results)

                elif cmd == DISPLAY_RESULTS:
                    s_ctrl.sendall(bytes([IPERF_DONE]))
                    s_ctrl.close()
                    time.sleep(1) # delay so server is ready for any subsequent client connections
                    return

        stats.update()
