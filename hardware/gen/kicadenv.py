"""Где лежат системные библиотеки KiCad и как заткнуть отладочные окна wx.

Скрипты писались под KiCad 7 в Linux, но должны запускаться и из KiCad 10
в Windows: пути к библиотекам ищем, а не прописываем.
"""
import glob
import os


def _pick(cands):
    for p in cands:
        if p and os.path.isdir(p):
            return p
    return cands[-1] if cands else ""


def share_dir():
    """Каталог share/kicad с footprints/ и symbols/."""
    env = os.environ.get("KICAD_SHARE")
    win = sorted(glob.glob("C:/Program Files/KiCad/*/share/kicad"), reverse=True)
    mac = ["/Applications/KiCad/KiCad.app/Contents/SharedSupport"]
    return _pick([env, "/usr/share/kicad", "/usr/local/share/kicad"] + win + mac)


FPDIR = os.path.join(share_dir(), "footprints")
SYMDIR = os.path.join(share_dir(), "symbols")


def textbox(t):
    """Габарит надписи. В KiCad 10 у EDA_TEXT::GetTextBox появился аргумент."""
    try:
        return t.GetTextBox()
    except TypeError:
        return t.GetTextBox(None)


def quiet():
    """KiCad 10 сыплет модальными окнами wxAssert на устаревшие вызовы API.

    В скриптовой сборке отвечать на них некому - плата собирается вслепую,
    а окно висит до конца таймаута. Ассерты выключаем.
    """
    try:
        import wx

        wx.DisableAsserts()
    except Exception:
        pass
