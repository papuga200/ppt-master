#!/usr/bin/env python3
"""
PPT Master - exp_svg inspection: plane geometry helpers

Rectangles are [x0, y0, x1, y1] in slide pixels; points are (x, y). Pure functions, no I/O.

Usage:
    Imported by checks.py; not a command.

Dependencies:
    None (only uses standard library)
"""

from __future__ import annotations

import math
import re
import sys
from typing import Iterable, Optional, Sequence

if __name__ == "__main__" and any(arg in {"-h", "--help", "help"} for arg in sys.argv[1:]):
    print(__doc__)
    raise SystemExit(0)

Rect = Sequence[float]
Point = Sequence[float]


def width(r: Rect) -> float:
    return max(0.0, r[2] - r[0])


def height(r: Rect) -> float:
    return max(0.0, r[3] - r[1])


def area(r: Rect) -> float:
    return width(r) * height(r)


def center(r: Rect) -> tuple[float, float]:
    return ((r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0)


def union(rects: Iterable[Rect]) -> Optional[list[float]]:
    rects = [r for r in rects if r]
    if not rects:
        return None
    return [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]


def intersection(a: Rect, b: Rect) -> Optional[list[float]]:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1, y1]


def inflate(r: Rect, dx: float, dy: Optional[float] = None) -> list[float]:
    dy = dx if dy is None else dy
    return [r[0] - dx, r[1] - dy, r[2] + dx, r[3] + dy]


def contains_rect(outer: Rect, inner: Rect, tol: float = 0.5) -> bool:
    return inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol


def contains_point(r: Rect, p: Point, tol: float = 0.0) -> bool:
    return r[0] - tol <= p[0] <= r[2] + tol and r[1] - tol <= p[1] <= r[3] + tol


def overflow(outer: Rect, inner: Rect) -> dict:
    """How far inner sticks out of outer on each side (0 when inside)."""
    return {"left": max(0.0, outer[0] - inner[0]), "top": max(0.0, outer[1] - inner[1]),
            "right": max(0.0, inner[2] - outer[2]), "bottom": max(0.0, inner[3] - outer[3])}


def dist_point_rect(p: Point, r: Rect) -> float:
    dx = max(r[0] - p[0], 0.0, p[0] - r[2])
    dy = max(r[1] - p[1], 0.0, p[1] - r[3])
    return math.hypot(dx, dy)


def dist_rect_rect(a: Rect, b: Rect) -> float:
    dx = max(b[0] - a[2], 0.0, a[0] - b[2])
    dy = max(b[1] - a[3], 0.0, a[1] - b[3])
    return math.hypot(dx, dy)


def dist_point_segment(p: Point, a: Point, b: Point) -> tuple[float, float]:
    """Distance and the parameter t in [0, 1] of the closest point."""
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    vx, vy = bx - ax, by - ay
    denom = vx * vx + vy * vy
    t = 0.0 if denom == 0 else max(0.0, min(1.0, ((p[0] - ax) * vx + (p[1] - ay) * vy) / denom))
    cx, cy = ax + t * vx, ay + t * vy
    return math.hypot(p[0] - cx, p[1] - cy), t


def polyline_length(points: Sequence[Point]) -> float:
    return sum(math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]) for i in range(len(points) - 1))


def dist_point_polyline(p: Point, points: Sequence[Point]) -> tuple[float, float]:
    """Distance to the polyline and the arc-length position of the closest point."""
    best, best_s, s = float("inf"), 0.0, 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        d, t = dist_point_segment(p, a, b)
        if d < best:
            best, best_s = d, s + t * seg
        s += seg
    if len(points) == 1:
        best = math.hypot(p[0] - points[0][0], p[1] - points[0][1])
    return best, best_s


def _seg_intersects_rect(a: Point, b: Point, r: Rect) -> bool:
    """Liang-Barsky clip test."""
    x0, y0 = a
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - r[0]), (dx, r[2] - x0), (-dy, y0 - r[1]), (dy, r[3] - y0)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def polyline_hits_rect(points: Sequence[Point], r: Rect) -> bool:
    return any(_seg_intersects_rect(points[i], points[i + 1], r) for i in range(len(points) - 1))


def direction(points: Sequence[Point], at_end: bool, min_len: float = 2.0) -> Optional[tuple[float, float]]:
    """Unit tangent leaving the start (at_end False) or arriving at the end (at_end True)."""
    if len(points) < 2:
        return None
    if at_end:
        tip = points[-1]
        for q in reversed(points[:-1]):
            dx, dy = tip[0] - q[0], tip[1] - q[1]
            d = math.hypot(dx, dy)
            if d >= min_len:
                return dx / d, dy / d
    else:
        tip = points[0]
        for q in points[1:]:
            dx, dy = q[0] - tip[0], q[1] - tip[1]
            d = math.hypot(dx, dy)
            if d >= min_len:
                return dx / d, dy / d
    return None


def angle_deg(v: tuple[float, float]) -> float:
    return math.degrees(math.atan2(v[1], v[0]))


def angle_diff(a: float, b: float) -> float:
    d = (a - b + 180.0) % 360.0 - 180.0
    return abs(d)


def point_in_polygon(p: Point, poly: Sequence[Point]) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xin > x:
                inside = not inside
    return inside


def overlap_area(a: Rect, a_outline: Optional[Sequence[Point]], b: Rect, b_outline: Optional[Sequence[Point]]) -> float:
    """Area shared by two shapes: exact for axis-aligned boxes, grid-sampled when an outline is given."""
    inter = intersection(a, b)
    if inter is None:
        return 0.0
    if not a_outline and not b_outline:
        return area(inter)
    step = max(0.5, math.sqrt(area(inter)) / 40.0)
    count = 0
    y = inter[1] + step / 2
    while y < inter[3]:
        x = inter[0] + step / 2
        while x < inter[2]:
            if (not a_outline or point_in_polygon((x, y), a_outline)) and (not b_outline or point_in_polygon((x, y), b_outline)):
                count += 1
            x += step
        y += step
    return count * step * step


_RGB_RE = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)")
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_color(value: Optional[str]) -> Optional[tuple[float, float, float]]:
    if not value:
        return None
    value = value.strip()
    m = _RGB_RE.search(value)
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3))
    m = _HEX_RE.match(value)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return float(int(h[0:2], 16)), float(int(h[2:4], 16)), float(int(h[4:6], 16))
    return None


def color_distance(a: Optional[str], b: Optional[str]) -> Optional[float]:
    ca, cb = parse_color(a), parse_color(b)
    if ca is None or cb is None:
        return None
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(ca, cb)))


def luminance(value: Optional[str]) -> Optional[float]:
    c = parse_color(value)
    if c is None:
        return None

    def lin(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def hex_of(value: Optional[str]) -> Optional[str]:
    c = parse_color(value)
    if c is None:
        return value
    return "#%02X%02X%02X" % tuple(int(round(v)) for v in c)
