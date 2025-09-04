import struct
import time
import sys

try:
    import network
    import usocket as socket
    import ussl as ssl
    const = lambda x: x
except ImportError:
    import socket
    import ssl
    def const(x): return x

HDR_LEN = const(5)
HDR_FMT = "!BHH"

MSG_RSP = const(0)
MSG_LOGIN = const(2)
MSG_PING = const(17)
MSG_TWEET = const(12)
MSG_EMAIL = const(13)
MSG_NOTIFY = const(14)
MSG_BRIDGE = const(15)
MSG_HW_SYNC = const(16)
MSG_HW_INFO = const(17)
MSG_PROPERTY = const(19)
MSG_HW = const(20)

MSG_REDIRECT  = const(41) # in app
MSG_DBG_PRINT  = const(55) # in app

STA_SUCCESS = const(200)

HB_PERIOD = const(10)
NON_BLK_SOCK = const(0)
MIN_SOCK_TO = const(1) # 1 second
MAX_SOCK_TO = const(30) # 30 seconds
RECONNECT_DELAY = const(1) # 1 second
TASK_PERIOD_RES = const(50) # 50 ms

RE_TX_DELAY = const(2)
MAX_TX_RETRIES = const(3)

MAX_VIRTUAL_PINS = const(128)

DISCONNECTED = const(0)
CONNECTING = const(1)
AUTHENTICATING = const(2)
AUTHENTICATED = const(3)

E_OVERFLOW = const('gnrc_overflow')
E_NOT_CONN = const('not_conn')

class EventEmitter:
    def __init__(self):
        self._events = {}

    def on(self, event, func=None):
        if func is None:
            def D(func):
                self.on(event, func)
                return func
            return D

        if event not in self._events:
            self._events[event] = []
        self._events[event].append(func)

    def emit(self, event, *args, **kwargs):
        if event in self._events:
            for func in self._events[event]:
                func(*args, **kwargs)

class Blynk(EventEmitter):
    def __init__(self, token, server='blynk.cloud', port=None, connect=True, ssl=True):
        EventEmitter.__init__(self)
        self._T = token
        self._S = server
        self._p_ssl = port or (443 if ssl else 80)
        self._do_ssl = ssl
        self._s = None
        self._m_id = 1
        self._state = DISCONNECTED
        self._last_hb_t = 0
        self._hb_pending = 0
        self._events = {}
        self.pro_vs = {}

        self.on('V127', self._on_V127)

    def _on_V127(self, state, *args):
        if int(state[0]):
            self.emit('sync_all')
            self.read_all_pending()

    def _format_msg(self, msg_type, *args):
        data = ('\0'.join(map(str, args))).encode('utf8')
        return struct.pack(HDR_FMT, msg_type, self._m_id, len(data)) + data

    def _handle_rsp(self, data):
        data = data.decode('utf8') if data else ''
        if self._state == AUTHENTICATING:
            status = struct.unpack("!H", self._rx_data)[0]
            if status == STA_SUCCESS:
                self._state = AUTHENTICATED
                self.emit('connect')
                self._last_hb_t = time.ticks_ms()
                print('Blynk authenticated')
                self.sync_all()
            else:
                print('Authentication failed')
                self._close('auth_failed')
        elif self._hb_pending and len(data) == 0:
            self._hb_pending = 0

    def _recv(self, length, timeout=0):
        if self._s is None:
            return None
        self._s.settimeout(timeout)
        try:
            self._rx_data = self._s.recv(length)
        except socket.timeout:
            return None
        except OSError:
            return b''
        if not self._rx_data:
            return b''
        return self._rx_data

    def _close(self, reason=None):
        if self._s:
            self._s.close()
            self._s = None
        self._state = DISCONNECTED
        self._m_id = 1
        self.emit('disconnect', reason)
        print('Blynk disconnected: ', reason)

    def _run_task(self):
        if self._state == AUTHENTICATED:
            diff = time.ticks_diff(time.ticks_ms(), self._last_hb_t)
            if diff > HB_PERIOD * 1000:
                self._last_hb_t = time.ticks_ms()
                if self._hb_pending > 1:
                    return self._close('heartbeat_failed')
                try:
                    self._s.send(self._format_msg(MSG_PING))
                    self._hb_pending += 1
                except OSError:
                    return self._close(E_NOT_CONN)
        elif self._state == DISCONNECTED:
            self.connect()

    def _server_alive(self):
        try:
            self._s.getpeername()
            return True
        except:
            return False

    def connect(self):
        if self._state == DISCONNECTED:
            self._state = CONNECTING
            try:
                self._s = socket.socket()
                if self._do_ssl:
                    #Note: CPython needs ssl.SSLContext().wrap_socket call
                    try:
                        self._s = ssl.wrap_socket(self._s, server_hostname=self._S)
                    # Micropython uses just second arg
                    except TypeError:
                        self._s = ssl.wrap_socket(self._s, ssl_version=ssl.PROTOCOL_TLS)
                addr = socket.getaddrinfo(self._S, self._p_ssl)[0][-1]
                print('Connecting to %s:%d...' % (self._S, self._p_ssl))
                self._s.connect(addr)
                self._s.setblocking(NON_BLK_SOCK)
                self._state = AUTHENTICATING
                hdr = self._format_msg(MSG_LOGIN, self._T)
                self._s.send(hdr)
                self._rx_data = b''
            except OSError as e:
                self._close(str(e))
                time.sleep(RECONNECT_DELAY)
                return False
            return True

    def run(self):
        self._run_task()
        if self._state != AUTHENTICATED:
            return
        data = self._recv(1024)
        if data is None: return
        if not data:
            return self._close(E_NOT_CONN)
        self._rx_data += data

        while len(self._rx_data) >= HDR_LEN:
            msg_type, msg_id, msg_len = struct.unpack(HDR_FMT, self._rx_data[:HDR_LEN])
            if msg_len > len(self._rx_data) - HDR_LEN:
                break
            msg_data = self._rx_data[HDR_LEN:HDR_LEN+msg_len]
            self._rx_data = self._rx_data[HDR_LEN+msg_len:]

            if msg_type == MSG_RSP:
                self._handle_rsp(msg_data)
            elif msg_type == MSG_HW or msg_type == MSG_BRIDGE:
                self._handle_hw(msg_data.decode('utf8').split('\0'))
            elif msg_type == MSG_PING:
                try:
                    self._s.send(self._format_msg(MSG_RSP, status=STA_SUCCESS))
                except OSError:
                    self._close(E_NOT_CONN)
            else:
                print('Unknown message type %d' % msg_type)

    def virtual_write(self, pin, val):
        self._send(self._format_msg(MSG_HW, 'vw', pin, val))

    def send_property(self, pin, prop, val):
        self._send(self._format_msg(MSG_PROPERTY, pin, prop, val))

    def set_property(self, pin, prop, val):
        self.send_property(pin, prop, val)

    def sync_virtual(self, pin):
        self._send(self._format_msg(MSG_HW_SYNC, 'vr', pin))

    def sync_all(self):
        self._send(self._format_msg(MSG_HW_SYNC))

    def _send(self, data, retry=False):
        if self._s is None or self._state != AUTHENTICATED:
            return
        try:
            self._s.send(data)
        except OSError:
            self._close(E_NOT_CONN)

    def _handle_hw(self, data):
        cmd = data.pop(0)
        if cmd == 'vw':
            pin = int(data.pop(0))
            self.emit('V' + str(pin), data)
            if pin in self.pro_vs:
                self.pro_vs[pin](data)
        elif cmd == 'vr':
            pin = int(data.pop(0))
            self.emit('read_V' + str(pin))
        else:
            print('Unknown HW cmd: %s' % cmd)

    def read_all_pending(self):
        for pin in self.pro_vs:
            self.emit('read_V' + str(pin))

