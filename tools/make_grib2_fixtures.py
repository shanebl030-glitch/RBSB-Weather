#!/usr/bin/env python3
"""Make the GRIB2 test files in tests/data (run once; needs the ecCodes Python package).

* gfs_2p5_wind10m.grib2: the real NOAA GFS 10 m U and V wind (2.5 degree, 120 h
  forecast) taken unchanged from the pygrib project's sample file
  sampledata/gfs.t12z.pgrbf120.2p5deg.grib2 (NOAA data: public domain).
* synthetic files written by ecCodes with each packing RBSB-Weather reads:
  complex packing with 2nd and 1st order spatial differencing, complex packing,
  simple packing, a bitmap with missing points, south-to-north rows, and a
  constant field.
The expected values, as ecCodes decodes them, go to grib2_expected.json.

Created By Shane BlackbuRn
"""
import hashlib, json, math, sys
from pathlib import Path
import eccodes

OUT = Path(__file__).resolve().parents[1] / "tests" / "data"
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/pygrib_src/sampledata/gfs.t12z.pgrbf120.2p5deg.grib2")


def digest(vals):
    return hashlib.sha256(json.dumps([None if (v is None or v != v) else round(v, 3) for v in vals]).encode()).hexdigest()


def summary(h, vals, miss=None):
    pts = [0, 1, len(vals) // 3, len(vals) // 2, len(vals) - 1]
    clean = [None if (miss is not None and v == miss) else v for v in vals]
    return {"ni": eccodes.codes_get(h, "Ni"), "nj": eccodes.codes_get(h, "Nj"),
            "category": eccodes.codes_get(h, "parameterCategory"), "number": eccodes.codes_get(h, "parameterNumber"),
            "packing": eccodes.codes_get(h, "packingType"), "scan": eccodes.codes_get(h, "scanningMode", int),
            "samples": {str(i): (None if clean[i] is None else round(clean[i], 6)) for i in pts},
            "sha256_3dp": digest(clean), "missing": sum(1 for v in clean if v is None)}


expected = {}
# 1) the real GFS 10 m winds
eccodes.codes_grib_multi_support_on()
wind = bytearray()
with open(SRC, "rb") as f:
    while (h := eccodes.codes_grib_new_from_file(f)) is not None:
        if (eccodes.codes_get(h, "typeOfFirstFixedSurface", int) == 103 and eccodes.codes_get(h, "level") == 10
                and eccodes.codes_get(h, "parameterCategory") == 2 and eccodes.codes_get(h, "parameterNumber") in (2, 3)):
            msg = eccodes.codes_get_message(h)
            if msg not in wind:
                wind += msg
        eccodes.codes_release(h)
eccodes.codes_grib_multi_support_off()
(OUT / "gfs_2p5_wind10m.grib2").write_bytes(bytes(wind))
eccodes.codes_grib_multi_support_on()
res = []
with open(OUT / "gfs_2p5_wind10m.grib2", "rb") as f:
    while (h := eccodes.codes_grib_new_from_file(f)) is not None:
        if eccodes.codes_get(h, "typeOfFirstFixedSurface", int) == 103 and eccodes.codes_get(h, "level") == 10:
            res.append(summary(h, list(eccodes.codes_get_values(h))))
        eccodes.codes_release(h)
eccodes.codes_grib_multi_support_off()
expected["gfs_2p5_wind10m.grib2"] = res


# 2) synthetic: a 1 degree global wind-like field
def field(ni, nj, k):
    return [12 * math.sin(math.radians(j * 180 / (nj - 1)) * 3 + k) * math.cos(math.radians(i * 360 / ni) * 2)
            + 4 * math.sin(i * 0.31 + j * 0.17 + k) for j in range(nj) for i in range(ni)]


def make(name, packing, ni=360, nj=181, order=None, scan=0, bitmap=False, const=False, number=2, decimals=2):
    h = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    eccodes.codes_set(h, "Ni", ni)
    eccodes.codes_set(h, "Nj", nj)
    eccodes.codes_set(h, "latitudeOfFirstGridPointInDegrees", 90.0 if not scan & 0x40 else -90.0)
    eccodes.codes_set(h, "latitudeOfLastGridPointInDegrees", -90.0 if not scan & 0x40 else 90.0)
    eccodes.codes_set(h, "longitudeOfFirstGridPointInDegrees", 0.0)
    eccodes.codes_set(h, "longitudeOfLastGridPointInDegrees", 360.0 - 360.0 / ni)
    eccodes.codes_set(h, "iDirectionIncrementInDegrees", 360.0 / ni)
    eccodes.codes_set(h, "jDirectionIncrementInDegrees", 180.0 / (nj - 1))
    eccodes.codes_set(h, "jScansPositively", 1 if scan & 0x40 else 0)
    eccodes.codes_set(h, "discipline", 0)
    eccodes.codes_set(h, "parameterCategory", 2)
    eccodes.codes_set(h, "parameterNumber", number)
    eccodes.codes_set(h, "typeOfFirstFixedSurface", 103)
    eccodes.codes_set(h, "scaleFactorOfFirstFixedSurface", 0)
    eccodes.codes_set(h, "scaledValueOfFirstFixedSurface", 10)
    vals = [7.25] * (ni * nj) if const else field(ni, nj, number)
    if bitmap:
        eccodes.codes_set(h, "bitmapPresent", 1)
        eccodes.codes_set(h, "missingValue", 9999)
        vals = [9999 if (i % 7 == 0 or 40 < i < 90) else v for i, v in enumerate(vals)]
    # packing type, then a bit count, then the values: without bitsPerValue ecCodes
    # packs complex fields with 0 bits (a flat field)
    eccodes.codes_set(h, "packingType", packing)
    if order:
        eccodes.codes_set(h, "orderOfSpatialDifferencing", order)
    eccodes.codes_set(h, "bitsPerValue", 16)
    eccodes.codes_set_values(h, vals)
    (OUT / name).write_bytes(eccodes.codes_get_message(h))
    eccodes.codes_release(h)
    with open(OUT / name, "rb") as f:
        h = eccodes.codes_grib_new_from_file(f)
        expected[name] = [summary(h, list(eccodes.codes_get_values(h)), 9999 if bitmap else None)]
        eccodes.codes_release(h)


make("syn_1deg_csd2.grib2", "grid_complex_spatial_differencing", order=2)
make("syn_1deg_csd2_v.grib2", "grid_complex_spatial_differencing", order=2, number=3)
make("syn_small_csd1.grib2", "grid_complex_spatial_differencing", ni=37, nj=19, order=1)
make("syn_small_complex.grib2", "grid_complex", ni=37, nj=19)
make("syn_small_simple.grib2", "grid_simple", ni=37, nj=19)
make("syn_small_bitmap.grib2", "grid_simple", ni=37, nj=19, bitmap=True)
make("syn_small_bitmap_csd2.grib2", "grid_complex_spatial_differencing", ni=37, nj=19, order=2, bitmap=True)
make("syn_small_south_first.grib2", "grid_complex_spatial_differencing", ni=37, nj=19, order=2, scan=0x40)
make("syn_small_constant.grib2", "grid_complex_spatial_differencing", ni=37, nj=19, order=2, const=True)
(OUT / "grib2_expected.json").write_text(json.dumps(expected, indent=1) + "\n")
for k, v in expected.items():
    print(k, [(x["packing"], x["ni"], x["nj"], x["missing"]) for x in v], (OUT / k).stat().st_size, "bytes")
