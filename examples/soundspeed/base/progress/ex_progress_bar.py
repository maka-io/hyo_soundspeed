from __future__ import absolute_import, division, print_function, unicode_literals

from time import sleep
from PySide import QtGui

# logging settings
import logging
logger = logging.getLogger()
logger.setLevel(logging.NOTSET)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)  # change to WARNING to reduce verbosity, DEBUG for high verbosity
ch_formatter = logging.Formatter('%(levelname)-9s %(name)s.%(funcName)s:%(lineno)d > %(message)s')
ch.setFormatter(ch_formatter)
logger.addHandler(ch)

from hydroffice.soundspeed.soundspeed import SoundSpeedLibrary


def main():
    app = QtGui.QApplication([])
    lib = SoundSpeedLibrary(qt_progress=QtGui.QProgressDialog)
    lib.progress.start("TEST")
    sleep(0.5)
    lib.progress.update(30)
    sleep(0.5)
    lib.progress.update(60)
    sleep(0.5)
    lib.progress.end()
    app.exec_()

if __name__ == "__main__":
    main()