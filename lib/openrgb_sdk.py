import socket
import struct

PROTOCOL = 3
MAGIC = b"ORGB"

REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 40
SET_CLIENT_NAME = 50
DEVICE_LIST_UPDATED = 100
RESIZEZONE = 1000
UPDATELEDS = 1050
SETCUSTOMMODE = 1100
UPDATEMODE = 1101


class Reader:
    def __init__(self, buf):
        self.buf = buf
        self.pos = 0

    def u8(self):
        return self.take("<B")

    def u16(self):
        return self.take("<H")

    def u32(self):
        return self.take("<I")

    def i32(self):
        return self.take("<i")

    def take(self, fmt):
        v = struct.unpack_from(fmt, self.buf, self.pos)[0]
        self.pos += struct.calcsize(fmt)
        return v

    def string(self):
        n = self.u16()
        s = self.buf[self.pos:self.pos + n]
        self.pos += n
        return s.rstrip(b"\x00").decode(errors="replace")

    def skip(self, n):
        self.pos += n


def parse_mode(r):
    start = r.pos
    name = r.string()
    value = r.i32()
    r.u32()  # flags
    r.u32(); r.u32()  # speed min/max
    r.u32(); r.u32()  # brightness min/max
    r.u32(); r.u32()  # colors min/max
    r.u32()  # speed
    r.u32()  # brightness
    r.u32()  # direction
    color_mode = r.u32()
    n = r.u16()
    r.skip(4 * n)
    return {"name": name, "value": value, "color_mode": color_mode, "raw": bytes(r.buf[start:r.pos])}


def parse_zone(r):
    name = r.string()
    ztype = r.i32()
    leds_min = r.u32()
    leds_max = r.u32()
    leds_count = r.u32()
    matrix = r.u16()
    r.skip(matrix)
    return {"name": name, "type": ztype, "leds_min": leds_min, "leds_max": leds_max, "leds_count": leds_count}


def parse_controller(buf):
    r = Reader(buf)
    size = r.u32()
    dev = {"type": r.i32(), "name": r.string(), "vendor": r.string(), "description": r.string(),
           "version": r.string(), "serial": r.string(), "location": r.string()}
    n_modes = r.u16()
    dev["active_mode"] = r.i32()
    dev["modes"] = [parse_mode(r) for _ in range(n_modes)]
    dev["zones"] = [parse_zone(r) for _ in range(r.u16())]
    n_leds = r.u16()
    dev["leds"] = []
    for _ in range(n_leds):
        dev["leds"].append((r.string(), r.u32()))
    n_colors = r.u16()
    r.skip(4 * n_colors)
    dev["num_leds"] = n_leds
    dev["num_colors"] = n_colors
    if r.pos != size:
        raise ValueError(f"controller data parse mismatch: consumed {r.pos} of {size}")
    return dev


class OpenRGBClient:
    def __init__(self, host="127.0.0.1", port=6742, name="omarchy-lights", timeout=5):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.send(0, REQUEST_PROTOCOL_VERSION, struct.pack("<I", PROTOCOL))
        self.server_protocol = struct.unpack("<I", self.wait(REQUEST_PROTOCOL_VERSION))[0]
        self.send(0, SET_CLIENT_NAME, name.encode() + b"\x00")

    def send(self, dev, pkt_id, payload=b""):
        self.sock.sendall(MAGIC + struct.pack("<III", dev, pkt_id, len(payload)) + payload)

    def recv_exact(self, n):
        out = b""
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError("openrgb server closed connection")
            out += chunk
        return out

    def recv(self):
        hdr = self.recv_exact(16)
        if hdr[:4] != MAGIC:
            raise ConnectionError("bad magic from openrgb server")
        dev, pkt_id, size = struct.unpack("<III", hdr[4:])
        return dev, pkt_id, self.recv_exact(size) if size else b""

    def wait(self, pkt_id):
        while True:
            dev, pid, data = self.recv()
            if pid == pkt_id:
                return data

    def controller_count(self):
        self.send(0, REQUEST_CONTROLLER_COUNT)
        return struct.unpack("<I", self.wait(REQUEST_CONTROLLER_COUNT))[0]

    def controller(self, idx):
        self.send(idx, REQUEST_CONTROLLER_DATA, struct.pack("<I", PROTOCOL))
        return parse_controller(self.wait(REQUEST_CONTROLLER_DATA))

    def resize_zone(self, idx, zone, size):
        self.send(idx, RESIZEZONE, struct.pack("<ii", zone, size))

    def set_custom_mode(self, idx):
        self.send(idx, SETCUSTOMMODE)

    def update_mode(self, idx, mode_idx, mode_raw):
        body = struct.pack("<i", mode_idx) + mode_raw
        self.send(idx, UPDATEMODE, struct.pack("<I", 4 + len(body)) + body)

    def update_leds(self, idx, colors):
        body = struct.pack("<H", len(colors)) + b"".join(struct.pack("<I", (r) | (g << 8) | (b << 16)) for r, g, b in colors)
        self.send(idx, UPDATELEDS, struct.pack("<I", 4 + len(body)) + body)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
