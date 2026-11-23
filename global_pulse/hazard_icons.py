"""Vector glyphs; marker severity colors and verification rings remain unchanged."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_PATHS = {
    "earthquake": (((-1,0),(-.6,0),(-.33,-.68),(-.03,.75),(.23,-.42),(.47,0),(1,0)),),
    "cyclone": (((.15,0),(.34,-.22),(.15,-.48),(-.27,-.51),(-.63,-.2),(-.64,.25),(-.3,.65),(.27,.76),(.82,.42),(1,-.06)),),
    "tornado": (((-1,-.7),(1,-.7)),((-.8,-.3),(.72,-.3)),((-.5,.1),(.5,.1)),((-.2,.5),(.31,.5)),((.05,.9),(.18,.9))),
    "flood": (((-1,-.45),(-.67,-.7),(-.33,-.45),(0,-.2),(.33,-.45),(.67,-.7),(1,-.45)),((-1,.35),(-.67,.1),(-.33,.35),(0,.6),(.33,.35),(.67,.1),(1,.35))),
    "tsunami": (((-1,.65),(-.7,.2),(-.48,-.45),(.02,-.82),(.59,-.7),(.8,-.32),(.45,-.43),(.2,-.15),(.44,.36),(1,.65),(-1,.65)),),
    "storm": (((.3,-.95),(-.73,.15),(-.02,.15),(-.3,.95),(.78,-.25),(.04,-.25),(.3,-.95)),),
    "wildfire": (((0,-.98),(.1,-.34),(.54,-.55),(.83,.1),(.55,.73),(0,.92),(-.61,.69),(-.83,.12),(-.52,-.32),(-.24,.13),(0,-.98)),),
    "volcano": (((-1,.75),(-.36,-.24),(.36,-.24),(1,.75),(-1,.75)),((-.22,-.5),(-.43,-.93)),((.13,-.48),(.2,-.98)),((.43,-.47),(.69,-.74))),
    "winter": (((0,-1),(0,1)),((-.87,-.5),(.87,.5)),((-.87,.5),(.87,-.5)),((-.3,-.7),(0,-.45),(.3,-.7)),((-.3,.7),(0,.45),(.3,.7))),
    "heat_drought": (((-.45,-.45),(.45,-.45),(.45,.45),(-.45,.45),(-.45,-.45)),((0,-.67),(0,-1)),((0,.67),(0,1)),((-.67,0),(-1,0)),((.67,0),(1,0)),((-.67,-.67),(-.95,-.95)),((.67,.67),(.95,.95))),
    "landslide": (((-1,.8),(-.53,-.8),(.9,.8),(-1,.8)),((-.13,-.2),(.1,.14),(.4,.13),(.66,.48)),((.67,.48),(.27,.48)),((.67,.48),(.67,.1))),
    "other": (((0,-.98),(.95,0),(0,.98),(-.95,0),(0,-.98)),((0,-.46),(0,.15)),((0,.48),(0,.54))),
}

def draw_hazard_glyph(painter,center,radius,kind,color):
    paths=_PATHS.get(kind)
    if not paths:
        return
    painter.save()
    try:
        painter.translate(center)
        painter.scale(radius,radius)
        painter.setPen(QPen(QColor(color),.17,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for coordinates in paths:
            path=QPainterPath(QPointF(*coordinates[0]))
            for coordinate in coordinates[1:]:
                path.lineTo(QPointF(*coordinate))
            painter.drawPath(path)
    finally:
        painter.restore()

def hazard_icon(kind):
    image=QPixmap(22,22)
    image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    try:
        draw_hazard_glyph(painter,QPointF(11,11),8,kind,"#c9b2f4")
    finally:
        painter.end()
    return QIcon(image)
