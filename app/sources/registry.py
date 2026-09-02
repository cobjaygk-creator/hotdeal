from app.sources.arca import ArcaSource
from app.sources.clien import ClienSource
from app.sources.coolenjoy import CoolenjoySource
from app.sources.damoang import DamoangSource
from app.sources.dealbada import DealbadaSource
from app.sources.eomisae import EomisaeSource
from app.sources.ppomppu import PpomppuSource
from app.sources.quasarzone import QuasarzoneSource
from app.sources.ruliweb import RuliwebSource

SOURCE_LABELS = {
    "ppomppu": "뽐뿌",
    "clien": "클리앙",
    "ruliweb": "루리웹",
    "eomisae": "어미새",
    "dealbada": "딜바다",
    "quasarzone": "퀘이사존",
    "coolenjoy": "쿨엔조이",
    "arca": "아카라이브",
    "damoang": "다모앙",
}

ALL_SOURCES = [
    PpomppuSource(),
    ArcaSource(),
    QuasarzoneSource(),
    ClienSource(),
    RuliwebSource(),
    DamoangSource(),
    CoolenjoySource(),
    EomisaeSource(),
    DealbadaSource(),
]


def get_sources(names: list[str] | None = None):
    if not names:
        return list(ALL_SOURCES)
    wanted = {n.lower() for n in names}
    return [s for s in ALL_SOURCES if s.name in wanted]
