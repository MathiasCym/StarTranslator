"""Page geometry for nested DrawingML groups; font points never scale with groups."""
import math
from pptx.enum.shapes import MSO_SHAPE_TYPE

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
IDENTITY = (1., 0., 0., 1., 0., 0.)


def compose(a, b):
    aa, ab, ac, ad, ax, ay = a
    ba, bb, bc, bd, bx, by = b
    return (aa*ba+ac*bb, ab*ba+ad*bb, aa*bc+ac*bd, ab*bc+ad*bd,
            aa*bx+ac*by+ax, ab*bx+ad*by+ay)


def point(m, x, y):
    a, b, c, d, tx, ty = m
    return a*x+c*y+tx, b*x+d*y+ty


def group_matrix(shape):
    xf = shape._element.grpSpPr.xfrm
    if xf is None: return IDENTITY
    def pair(tag, x, y, default):
        node = xf.find(f'{{{A}}}{tag}')
        return default if node is None else (float(node.get(x)), float(node.get(y)))
    ox, oy = pair('off', 'x', 'y', (0, 0))
    ex, ey = pair('ext', 'cx', 'cy', (1, 1))
    cx, cy = pair('chOff', 'x', 'y', (0, 0))
    wx, wy = pair('chExt', 'cx', 'cy', (ex, ey))
    sx, sy = ex/(wx or 1), ey/(wy or 1)
    m = (sx, 0, 0, sy, ox-cx*sx, oy-cy*sy)
    angle = math.radians(float(xf.get('rot', '0'))/60000)
    fx, fy = (-1 if xf.get('flipH') == '1' else 1), (-1 if xf.get('flipV') == '1' else 1)
    co, si = math.cos(angle), math.sin(angle)
    rotate = (co*fx, si*fx, -si*fy, co*fy, 0, 0)
    x, y = ox+ex/2, oy+ey/2
    rotate = (*rotate[:4], x-rotate[0]*x-rotate[2]*y, y-rotate[1]*x-rotate[3]*y)
    return compose(rotate, m)


def walk_shapes(items, prefix, transform=IDENTITY):
    for index, shape in enumerate(items):
        key = f'{prefix}/shape{index}'
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from walk_shapes(shape.shapes, key, compose(transform, group_matrix(shape)))
        else:
            yield key, shape, transform


def dimensions(shape, transform):
    a, b, c, d, _, _ = transform
    return round(shape.width*math.hypot(a, b)), round(shape.height*math.hypot(c, d))


def bounds(shape, transform):
    points = [point(transform, shape.left+x, shape.top+y)
              for x, y in ((0, 0), (shape.width, 0), (0, shape.height), (shape.width, shape.height))]
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)
