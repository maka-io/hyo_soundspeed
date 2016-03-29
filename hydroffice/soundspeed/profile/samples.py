from __future__ import absolute_import, division, print_function, unicode_literals

import os
import numpy as np
import logging

logger = logging.getLogger(__name__)


class Samples(object):
    def __init__(self):
        self.num_samples = 0
        self.depth = None
        self.speed = None
        self.temp = None
        self.sal = None

    def init_depth(self):
        self.depth = np.zeros(self.num_samples)

    def init_speed(self):
        self.speed = np.zeros(self.num_samples)

    def init_temp(self):
        self.temp = np.zeros(self.num_samples)

    def init_sal(self):
        self.sal = np.zeros(self.num_samples)

    def resize(self, count):
        """Resize the arrays (if present) to the new given number of elements"""
        if self.num_samples == count:
            return
        self.num_samples = count

        if self.depth is not None:
            self.depth.resize(count)
        if self.speed is not None:
            self.speed.resize(count)
        if self.temp is not None:
            self.temp.resize(count)
        if self.sal is not None:
            self.sal.resize(count)

    def __repr__(self):
        msg = "  <Samples>\n"
        msg += "    <nr:%s>\n" % self.num_samples
        if self.depth is not None:
            msg += "    <depth sz:%s min:%.3f max:%.3f>\n" % (self.depth.shape[0], self.depth.min(), self.depth.max())
        if self.speed is not None:
            msg += "    <speed sz:%s min:%.3f max:%.3f>\n" % (self.speed.shape[0], self.speed.min(), self.speed.max())
        if self.temp is not None:
            msg += "    <temp sz:%s min:%.3f max:%.3f>\n" % (self.temp.shape[0], self.temp.min(), self.temp.max())
        if self.sal is not None:
            msg += "    <sal sz:%s min:%.3f max:%.3f>\n" % (self.sal.shape[0], self.sal.min(), self.sal.max())
        return msg