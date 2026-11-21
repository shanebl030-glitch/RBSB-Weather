"""A small GRIB2 reader: just enough for NOAA GFS wind on a latitude/longitude grid (2.2.0).

GRIB2 is the World Meteorological Organization's binary format for gridded
weather data. RBSB-Weather reads it itself so that no extra package is needed:

* grids: template 3.0 (regular latitude/longitude), any scanning direction
  except "boustrophedon" rows;
* products: template 4.0 (an analysis or forecast at a level), which gives
  the parameter (category/number), level and forecast time;
* packing: templates 5.0 (simple), 5.2 (complex) and 5.3 (complex with 1st or
  2nd order spatial differencing; NOAA's GFS uses this);
* bitmaps (section 6): missing points come back as NaN / None.

JPEG2000 (5.40) and PNG (5.41) packing aren't supported: GFS doesn't use them,
and they'd need image libraries. Such messages raise Grib2Error.

numpy is used when installed; without it, a pure-Python path gives the same
values (a few times slower: well under a second for a 1° GFS field).

Checked against ecCodes (ECMWF's reference library) on a real NOAA GFS file and
on files written with every supported packing; see tests/test_grib2.py.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Optional

try:
    import numpy as _np
except Exception:          # pragma: no cover - depends on the system
    _np = None

MAX_POINTS = 4_000_000     # refuse absurd grids (a damaged file can't make us allocate GBs)


class Grib2Error(Exception):
    pass


@dataclass
class Grid:
    ni: int                 # points along a row (longitude)
    nj: int                 # rows (latitude)
    la1: float
    lo1: float
    la2: float
    lo2: float
    di: float
    dj: float
    scan: int


@dataclass
class Message:
    discipline: int
    category: int
    number: int
    level_type: int
    level: float
    forecast_hours: Optional[float]
    reference_time: tuple            # (year, month, day, hour, minute, second), UTC
    grid: Grid
    values: object = field(repr=False)   # numpy float array (NaN = missing) or list (None = missing),
                                         # in the file's scanning order

    def rows_north_to_south(self):
        """Values as nj rows from north to south, each west to east (as a numpy (nj, ni)
        array, or a list of lists without numpy)."""
        g = self.grid
        if g.scan & 0x30:
            raise Grib2Error("Unsupported scanning mode (columns first or alternating rows).")
        flip_rows = bool(g.scan & 0x40)          # +j: south to north
        flip_cols = bool(g.scan & 0x80)          # -i: east to west
        if _np is not None and not isinstance(self.values, list):
            a = self.values.reshape(g.nj, g.ni)
            if flip_rows:
                a = a[::-1]
            if flip_cols:
                a = a[:, ::-1]
            return a
        rows = [list(self.values[j * g.ni:(j + 1) * g.ni]) for j in range(g.nj)]
        if flip_rows:
            rows.reverse()
        if flip_cols:
            rows = [r[::-1] for r in rows]
        return rows


# --------------------------------------------------------------------- helpers
def _u(b: bytes, off: int, n: int) -> int:
    return int.from_bytes(b[off:off + n], "big")


def _s(b: bytes, off: int, n: int) -> int:
    """GRIB2 signed integer: sign-magnitude (top bit is the sign), not two's complement."""
    v = _u(b, off, n)
    top = 1 << (8 * n - 1)
    return -(v & (top - 1)) if v & top else v


def _float32(b: bytes, off: int) -> float:
    return struct.unpack(">f", b[off:off + 4])[0]


def _unpack(data: bytes, bitpos: int, count: int, width: int):
    """`count` unsigned integers of `width` bits starting at bit `bitpos`."""
    if count <= 0:
        return [] if _np is None else _np.zeros(0, _np.int64)
    if width == 0:
        return [0] * count if _np is None else _np.zeros(count, _np.int64)
    if width > 63:
        raise Grib2Error("Packed values wider than 63 bits.")
    end_bit = bitpos + count * width
    if (end_bit + 7) // 8 > len(data):
        raise Grib2Error("The data section is shorter than its description says.")
    if _np is not None:
        first, last = bitpos // 8, (end_bit + 7) // 8
        bits = _np.unpackbits(_np.frombuffer(data, _np.uint8, last - first, first))
        bits = bits[bitpos - first * 8: bitpos - first * 8 + count * width].reshape(count, width)
        weights = (1 << _np.arange(width - 1, -1, -1, dtype=_np.int64))
        return bits.astype(_np.int64) @ weights
    out = []
    mask = (1 << width) - 1
    step = 2048                                     # values per block: keeps big-int maths cheap
    pos = bitpos
    remaining = count
    while remaining:
        n = min(step, remaining)
        first = pos // 8
        last = (pos + n * width + 7) // 8
        chunk = int.from_bytes(data[first:last], "big")
        total = (last - first) * 8
        shift = total - (pos - first * 8) - width
        for _ in range(n):
            out.append((chunk >> shift) & mask)
            shift -= width
        pos += n * width
        remaining -= n
    return out


def _padded(bits: int) -> int:
    return (bits + 7) // 8 * 8


# --------------------------------------------------------------------- reading
def messages(buf: bytes) -> list[Message]:
    """Every GRIB2 message in `buf` (GRIB1 or unsupported messages raise Grib2Error)."""
    out = []
    pos = buf.find(b"GRIB")
    while pos != -1 and pos + 16 <= len(buf):
        edition = buf[pos + 7]
        if edition != 2:
            raise Grib2Error(f"Not a GRIB2 message (edition {edition}).")
        total = _u(buf, pos + 8, 8)
        if total < 16 + 4 or pos + total > len(buf):
            raise Grib2Error("The GRIB2 file is cut short.")
        msg = buf[pos:pos + total]
        if msg[-4:] != b"7777":
            raise Grib2Error("A GRIB2 message doesn't end with 7777 (damaged file).")
        out.extend(_read_message(msg))
        pos = buf.find(b"GRIB", pos + total)
    if not out:
        raise Grib2Error("No GRIB2 data in the file.")
    return out


def _read_message(msg: bytes) -> list[Message]:
    discipline = msg[6]
    off = 16
    ref_time = (0, 0, 0, 0, 0, 0)
    grid = None
    prod = None
    rep = None
    bitmap = None
    results = []
    while off < len(msg) - 4:
        length = _u(msg, off, 4)
        num = msg[off + 4]
        if length < 5 or off + length > len(msg):
            raise Grib2Error("A GRIB2 section has an impossible length (damaged file).")
        sec = msg[off:off + length]
        if num == 1:
            ref_time = (_u(sec, 12, 2), sec[14], sec[15], sec[16], sec[17], sec[18])
        elif num == 3:
            grid = _grid(sec)
        elif num == 4:
            prod = _product(sec)
        elif num == 5:
            rep = _representation(sec)
        elif num == 6:
            ind = sec[5]
            if ind == 0:
                bitmap = sec[6:]
            elif ind == 255:
                bitmap = None
            elif ind != 254:                         # 254 = reuse the previous bitmap
                raise Grib2Error("Predefined bitmaps aren't supported.")
        elif num == 7:
            if grid is None or prod is None or rep is None:
                raise Grib2Error("A GRIB2 data section came before its descriptions.")
            vals = _decode(sec[5:], rep, grid.ni * grid.nj, bitmap)
            results.append(Message(discipline, prod[0], prod[1], prod[2], prod[3], prod[4],
                                   ref_time, grid, vals))
        off += length
    return results


def _grid(sec: bytes) -> Grid:
    tmpl = _u(sec, 12, 2)
    if tmpl != 0:
        raise Grib2Error(f"Only latitude/longitude grids are supported (this is template 3.{tmpl}).")
    ni, nj = _u(sec, 30, 4), _u(sec, 34, 4)
    if ni <= 0 or nj <= 0 or ni * nj > MAX_POINTS:
        raise Grib2Error("The grid size is impossible (damaged file).")
    basic, sub = _u(sec, 38, 4), _u(sec, 42, 4)
    unit = 1e-6 if basic in (0, 0xFFFFFFFF) or sub in (0, 0xFFFFFFFF) else basic / sub
    la1, lo1 = _s(sec, 46, 4) * unit, _s(sec, 50, 4) * unit
    la2, lo2 = _s(sec, 55, 4) * unit, _s(sec, 59, 4) * unit
    di, dj = _u(sec, 63, 4) * unit, _u(sec, 67, 4) * unit
    return Grid(ni, nj, la1, lo1, la2, lo2, di, dj, sec[71])


_HOURS = {0: 1 / 60, 1: 1, 2: 24, 10: 3, 11: 6, 12: 12, 13: 1 / 3600}


def _product(sec: bytes) -> tuple:
    tmpl = _u(sec, 7, 2)
    cat, num = sec[9], sec[10]
    if tmpl not in (0, 1, 8):            # these share the layout we read below
        return cat, num, 255, float("nan"), None
    unit, ftime = sec[17], _s(sec, 18, 4)
    level_type = sec[22]
    scale, value = _s(sec, 23, 1), _s(sec, 24, 4)
    level = value / (10 ** scale) if scale else float(value)
    hours = ftime * _HOURS[unit] if unit in _HOURS else None
    return cat, num, level_type, level, hours


def _representation(sec: bytes) -> dict:
    tmpl = _u(sec, 9, 2)
    if tmpl not in (0, 2, 3):
        raise Grib2Error(f"Unsupported GRIB2 packing (template 5.{tmpl}).")
    r = {"tmpl": tmpl, "R": _float32(sec, 11), "E": _s(sec, 15, 2), "D": _s(sec, 17, 2), "nbits": sec[19]}
    if tmpl in (2, 3):
        r.update(split=sec[21], missing=sec[22], ng=_u(sec, 31, 4), ref_w=sec[35], bits_w=sec[36],
                 ref_l=_u(sec, 37, 4), inc_l=sec[41], last_l=_u(sec, 42, 4), bits_l=sec[46])
        if r["missing"] != 0:
            raise Grib2Error("Missing-value management inside the data isn't supported.")
    if tmpl == 3:
        r.update(order=sec[47], ie=sec[48])
        if r["order"] not in (1, 2) or r["ie"] == 0:
            raise Grib2Error("Unsupported spatial differencing.")
    return r


def _decode(data: bytes, r: dict, npts: int, bitmap: Optional[bytes]):
    present = npts
    mask = None
    if bitmap is not None:
        bits = _unpack(bitmap, 0, npts, 1)
        mask = [bool(b) for b in bits] if _np is None else bits.astype(bool)
        present = int(sum(mask)) if _np is None else int(mask.sum())
    if r["tmpl"] == 0:
        raw = _unpack(data, 0, present, r["nbits"])
    else:
        raw = _complex(data, r, present)
    R, ebin, dec = r["R"], 2.0 ** r["E"], 10.0 ** (-r["D"])
    if _np is not None:
        vals = (R + _np.asarray(raw, _np.float64) * ebin) * dec
        if mask is None:
            return vals
        full = _np.full(npts, _np.nan)
        full[mask] = vals
        return full
    vals = [(R + x * ebin) * dec for x in raw]
    if mask is None:
        return vals
    it = iter(vals)
    return [next(it) if m else None for m in mask]


def _complex(data: bytes, r: dict, n: int):
    """Complex packing (5.2), with spatial differencing (5.3)."""
    pos = 0
    h = []
    hmin = 0
    if r["tmpl"] == 3:
        ie, order = r["ie"], r["order"]
        for _ in range(order):
            h.append(_s(data, pos, ie))
            pos += ie
        hmin = _s(data, pos, ie)
        pos += ie
    bit = pos * 8
    ng = r["ng"]
    if ng <= 0 or ng > n:
        raise Grib2Error("Impossible number of groups (damaged file).")
    refs = _unpack(data, bit, ng, r["nbits"])
    bit = _padded(bit + ng * r["nbits"])
    widths = _unpack(data, bit, ng, r["bits_w"])
    bit = _padded(bit + ng * r["bits_w"])
    lens = _unpack(data, bit, ng, r["bits_l"])
    bit = _padded(bit + ng * r["bits_l"])
    ref_w, ref_l, inc_l = r["ref_w"], r["ref_l"], r["inc_l"]
    if _np is not None:
        widths = widths + ref_w
        lens = ref_l + lens * inc_l
        lens[-1] = r["last_l"]
        if int(lens.sum()) != n:
            raise Grib2Error("The group lengths don't add up (damaged file).")
        out = _np.empty(n, _np.int64)
        k = 0
        for g in range(ng):
            L, W = int(lens[g]), int(widths[g])
            out[k:k + L] = (_unpack(data, bit, L, W) if W else 0) + int(refs[g])
            bit += L * W
            k += L
    else:
        widths = [w + ref_w for w in widths]
        lens = [ref_l + x * inc_l for x in lens]
        lens[-1] = r["last_l"]
        if sum(lens) != n:
            raise Grib2Error("The group lengths don't add up (damaged file).")
        out = []
        for g in range(ng):
            L, W, ref = lens[g], widths[g], refs[g]
            if W:
                out.extend(x + ref for x in _unpack(data, bit, L, W))
            else:
                out.extend([ref] * L)
            bit += L * W
    if r["tmpl"] != 3:
        return out
    return _undifference(out, h, hmin, r["order"])


def _undifference(z, h, hmin, order):
    n = len(z)
    if _np is not None:
        z = _np.asarray(z, _np.int64) + hmin
        f = _np.empty(n, _np.int64)
        if order == 1:
            f[0] = h[0]
            if n > 1:
                f[1:] = h[0] + _np.cumsum(z[1:])
        else:
            # f[i] = z[i] + 2 f[i-1] - f[i-2]: the second difference is z, so cumulative
            # sums twice rebuild it (exact in integers)
            f[0] = h[0]
            if n > 1:
                f[1] = h[1]
            if n > 2:
                d = _np.empty(n - 1, _np.int64)          # first differences
                d[0] = h[1] - h[0]
                d[1:] = d[0] + _np.cumsum(z[2:])
                f[1:] = h[0] + _np.cumsum(d)
        return f
    f = [0] * n
    if order == 1:
        f[0] = h[0]
        for i in range(1, n):
            f[i] = z[i] + hmin + f[i - 1]
    else:
        f[0] = h[0]
        if n > 1:
            f[1] = h[1]
        for i in range(2, n):
            f[i] = z[i] + hmin + 2 * f[i - 1] - f[i - 2]
    return f


def is_grib2(buf: bytes) -> bool:
    return buf[:4] == b"GRIB" and len(buf) >= 16 and buf[7] == 2
