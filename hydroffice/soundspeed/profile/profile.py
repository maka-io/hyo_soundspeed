import os
import time
import numpy as np
import logging

logger = logging.getLogger(__name__)

from hydroffice.soundspeed import __version__ as soundspeed_version
from hydroffice.soundspeed.profile.metadata import Metadata
from hydroffice.soundspeed.profile.samples import Samples
from hydroffice.soundspeed.profile.more import More
from hydroffice.soundspeed.profile.dicts import Dicts
from hydroffice.soundspeed.profile.oceanography import Oceanography as Oc
from hydroffice.soundspeed.profile.ray_tracing.ray_tracing import RayTracing
from hydroffice.soundspeed.profile.ray_tracing.ray_path import RayPath


class Profile(object):
    """"A sound speed profile with 3 sections: metadata, data specific to the task, and additional data"""

    def __init__(self):
        self.meta = Metadata()  # metadata
        self.data = Samples()   # raw data
        self.proc = Samples()   # processed data
        self.sis = Samples()    # sis data
        self.more = More()      # additional fields

        self.woa09 = None
        self.woa13 = None
        self.rtofs = None

    def __repr__(self):
        msg = "<Profile>\n"
        msg += "%s" % self.meta
        msg += "%s" % self.data
        msg += "%s" % self.more
        return msg

    def init_data(self, num_samples):
        if num_samples == 0:
            return

        self.data.num_samples = num_samples
        self.data.init_pressure()
        self.data.init_depth()
        self.data.init_speed()
        self.data.init_temp()
        self.data.init_conductivity()
        self.data.init_sal()
        self.data.init_source()
        self.data.init_flag()

    def init_proc(self, num_samples):
        if num_samples == 0:
            return

        self.proc.num_samples = num_samples
        self.proc.init_pressure()
        self.proc.init_depth()
        self.proc.init_speed()
        self.proc.init_temp()
        self.proc.init_conductivity()
        self.proc.init_sal()
        self.proc.init_source()
        self.proc.init_flag()

    def init_sis(self, num_samples=0):
        self.sis.num_samples = num_samples
        self.sis.init_pressure()
        self.sis.init_depth()
        self.sis.init_speed()
        self.sis.init_temp()
        self.sis.init_conductivity()
        self.sis.init_sal()
        self.sis.init_source()
        self.sis.init_flag()

    def init_more(self, more_fields):
        self.more.init_struct_array(self.data.num_samples, more_fields)

    def data_resize(self, count):
        self.data.resize(count)
        self.more.resize(count)

    @property
    def data_valid(self):
        """Return indices of valid data"""
        return np.equal(self.data.flag, Dicts.flags['valid'])

    @property
    def proc_valid(self):
        """Return indices of valid proc samples"""
        return np.equal(self.proc.flag, Dicts.flags['valid'])

    @property
    def proc_dqa_valid(self):
        """Return indices of DQA valid proc samples"""
        return np.logical_and(self.proc_valid, np.equal(self.proc.source, Dicts.sources['raw']))

    @property
    def sis_valid(self):
        """Return indices of valid sis samples"""
        return np.equal(self.sis.flag, Dicts.flags['valid'])

    @property
    def sis_thinned(self):
        """Return indices of thinned sis samples"""
        return np.equal(self.sis.flag, Dicts.flags['thin'])

    @property
    def proc_invalid_direction(self):
        """Return indices of invalid data for direction"""
        return np.equal(self.proc.flag, Dicts.flags['direction'])  # numpy 1.10.4 if a warning

    def reduce_up_down(self, ssp_direction, use_pressure=False):
        """Reduce the raw data samples based on the passed direction"""
        if self.data.num_samples == 0:  # skipping if there are no data
            return

        # identify max depth
        if use_pressure:
            max_value = self.data.pressure[self.data_valid].max()  # max pressure
            logger.debug("reduce up/down > max pressure: %s" % max_value)

        else:
            max_value = self.data.depth[self.data_valid].max()  # max depth
            logger.debug("reduce up/down > max depth: %s" % max_value)

        # loop through the sample using max depth as turning point
        max_reached = False
        last_value = None
        for i in range(self.data.num_samples):

            if use_pressure:
                value = self.data.pressure[i]
            else:
                value = self.data.depth[i]

            if (ssp_direction == Dicts.ssp_directions['up'] and not max_reached) \
                    or (ssp_direction == Dicts.ssp_directions['down'] and max_reached):
                self.data.flag[i] = Dicts.flags['direction']  # set invalid for direction

            elif ssp_direction == Dicts.ssp_directions['down'] and not max_reached:

                if i != 0:
                    if value <= last_value:
                        # print(last_value, value)
                        self.data.flag[i] = Dicts.flags['direction']  # set invalid for direction
                    else:
                        last_value = value
                else:
                    last_value = value

            elif ssp_direction == Dicts.ssp_directions['up'] and max_reached:

                if i != 0:
                    if value >= last_value:
                        self.data.flag[i] = Dicts.flags['direction']  # set invalid for direction
                    else:
                        last_value = value
                else:
                    last_value = value

            if value == max_value:
                max_reached = True

    def calc_salinity_from_conductivity(self):
        if np.count_nonzero(self.data.pressure):
            pressure = self.data.pressure
        else:
            if not self.meta.latitude:
                latitude = 30.0
                logger.warning("using default latitude: %s" % latitude)
            else:
                latitude = self.meta.latitude
            pressure = Oc.d2p_backup(self.data.depth, latitude)

        self.data.sal = np.zeros_like(self.data.conductivity)
        # convert from S/m to mmho/cm
        # self.data.sal[self.data_valid] = Oc.c2s(self.data.conductivity[self.data_valid] * 10.0, pressure[self.data_valid], self.data.temp[self.data_valid])
        self.data.sal = Oc.c2s(self.data.conductivity * 10.0, pressure, self.data.temp)  # FIXME -- what is the standard conductivity unit?  S/m or mmho/cm  (mS/cm)
        self.modify_proc_info(Dicts.proc_import_infos['CALC_SAL'])

    def calc_salinity(self):
        """Helper method to calculate salinity from depth, sound speed and temperature"""
        # logger.debug("calculate salinity")
        if not self.meta.latitude:
            latitude = 30.0
            logger.warning("using default latitude: %s" % latitude)
        else:
            latitude = self.meta.latitude

        for count in range(self.data.num_samples):
            self.data.sal[count] = Oc.sal(d=self.data.depth[count], speed=self.data.speed[count],
                                          t=self.data.temp[count], lat=latitude)
        self.modify_proc_info(Dicts.proc_import_infos['CALC_SAL'])

    def calc_dyn_height(self):
        """Helper method to calculate the dynamic height"""
        if not self.meta.latitude:
            latitude = 30.0
            logger.warning("using default latitude: %s" % latitude)
        else:
            latitude = self.meta.latitude

        if not self.meta.longitude:
            longitude = -70.0
            logger.warning("using default longitude: %s" % longitude)
        else:
            longitude = self.meta.longitude

        try:
            # print(self.data_valid)
            sa = Oc.sal2sa(sal=self.data.sal[self.data_valid],
                           p=self.data.pressure[self.data_valid],
                           lon=longitude, lat=latitude)
            ct = Oc.t2ct(sa=sa,
                         t=self.data.temp[self.data_valid],
                         p=self.data.pressure[self.data_valid])
            dh = Oc.geo_strf_dyn_height(sa=sa, ct=ct, p=self.data.pressure[self.data_valid], p_ref=0)

            for val in dh:
                if np.isnan(val):
                    raise RuntimeError("nan in geo_strf_dyn_height")

            return dh

        except Exception as e:
            logger.warning("issue: %s" % e)
            return None

    def calc_data_depth(self):
        """Helper method to calculate depth from pressure (in dBar)"""
        dyn_height = self.calc_dyn_height()

        if not self.meta.latitude:
            latitude = 30.0
            logger.warning("using default latitude: %s" % latitude)
        else:
            latitude = self.meta.latitude

        self.data.depth = np.zeros_like(self.data.pressure)
        self.data.depth[self.data_valid] = Oc.p2d(p=self.data.pressure[self.data_valid], lat=latitude,
                                                  dyn_height=dyn_height, debug=True)
        self.modify_proc_info(Dicts.proc_import_infos['CALC_DEP'])

    def calc_dyn_height_with_depth(self):
        """Helper method to calculate the dynamic height"""
        if not self.meta.latitude:
            latitude = 30.0
            logger.warning("using default latitude: %s" % latitude)
        else:
            latitude = self.meta.latitude

        if not self.meta.longitude:
            longitude = -70.0
            logger.warning("using default longitude: %s" % longitude)
        else:
            longitude = self.meta.longitude

        try:
            # print(self.data_valid)
            sa = Oc.sal2sa(sal=self.data.sal[self.data_valid],
                           p=self.data.depth[self.data_valid],
                           lon=longitude, lat=latitude)
            ct = Oc.t2ct(sa=sa,
                         t=self.data.temp[self.data_valid],
                         p=self.data.depth[self.data_valid])
            dh = Oc.geo_strf_dyn_height(sa=sa, ct=ct, p=self.data.depth[self.data_valid], p_ref=0)

            for val in dh:
                if np.isnan(val):
                    raise RuntimeError("nan in geo_strf_dyn_height_with_depth")

            return dh

        except Exception as e:
            logger.warning("issue: %s" % e)
            return None

    def calc_data_pressure(self):
        """Helper method to calculate pressure from depth (in m)"""
        dyn_height = self.calc_dyn_height_with_depth()

        raise RuntimeError("Not implemented")

    def calc_data_speed(self):
        """Helper method to calculate sound speed"""
        # logger.debug("calculate sound speed")
        if not self.meta.latitude:
            latitude = 30.0
            logger.warning("using default latitude: %s" % latitude)
        else:
            latitude = self.meta.latitude

        for count in range(self.data.num_samples):
            self.data.speed[count] = Oc.speed(self.data.depth[count],
                                              self.data.temp[count],
                                              self.data.sal[count],
                                              latitude)
        self.modify_proc_info(Dicts.proc_import_infos['CALC_SPD'])

    def calc_proc_speed(self):
        """Helper method to calculate processed sound speed"""
        # logger.debug("calculate sound speed")
        if not self.meta.latitude:
            latitude = 30.0
            logger.warning("using default latitude: %s" % latitude)
        else:
            latitude = self.meta.latitude

        for count in range(self.proc.num_samples):
            self.proc.speed[count] = Oc.speed(self.proc.depth[count],
                                              self.proc.temp[count],
                                              self.proc.sal[count],
                                              latitude)
        self.modify_proc_info(Dicts.proc_user_infos['RECALC_SPD'])

    def calc_attenuation(self, frequency, ph):
        """Helper method to calculation attenuation [unused]"""
        depth = np.zeros(self.proc.num_samples)
        attenuation = np.zeros(self.proc.num_samples)
        for i in range(self.proc.num_samples):
            depth[i] = self.proc.depth[i]
            attenuation[i] = Oc.a(frequency, self.proc.temp[i], self.proc.sal[i],
                                  self.proc.depth[i], ph)

        return attenuation, depth

    def calc_cumulative_attenuation(self, frequency, ph):
        """Helper method to calculation cumulative attenuation [unused]"""
        attenuation, depth = self.calc_attenuation(frequency, ph)
        cumulative_attenuation = np.zeros(len(attenuation))

        total_loss = 0
        for count in range(len(attenuation) - 1):
            layer_loss = attenuation[count] * (depth[count + 1] - depth[count]) / 1000.0
            total_loss += layer_loss
            cumulative_attenuation[count] = total_loss / (depth[count + 1] / 1000.0)

        cumulative_attenuation[-1] = cumulative_attenuation[-2]

        return cumulative_attenuation, depth

    def insert_proc_speed(self, depth, speed, src=Dicts.sources['user']):
        logger.debug("insert speed to proc data: d:%s, vs:%s" % (depth, speed))

        # we need to take care of valid samples and user-invalidated samples (to avoid to brake in case un-flagged)
        valid = self.proc.flag == Dicts.flags['valid']  # valid samples
        iv = np.indices(self.proc.flag.shape)[0][valid]  # indices of valid samples
        user_invalid = self.proc.flag == Dicts.flags['user']  # user-invalidate samples
        possible = np.logical_or(valid, user_invalid)  # possible samples
        ip = np.indices(self.proc.flag.shape)[0][possible]  # indices of possible samples

        # find depth index both in the valid and in the possible samples
        try:
            # noinspection PyTypeChecker
            v_i = np.argwhere(self.proc.depth[valid] > depth)[0][0]  # the index in the valid array
            i = iv[v_i]  # the corresponding index of the masked index in the full array
        except IndexError:  # in case that there are not
            v_i = self.proc.depth[valid].size - 1
            i = iv[v_i]
        try:
            # noinspection PyTypeChecker
            p_i = np.argwhere(self.proc.depth[possible] > depth)[0][0]  # the index in the possible array
            j = ip[p_i]
        except IndexError:  # in case that there are not
            p_i = self.proc.depth[possible].size - 1
            j = ip[p_i]

        # check if we already have this depth in the masked array
        d_exists = self.proc.depth[valid][v_i] == depth

        # manipulate profile (linear interpolation)
        if d_exists:
            # print('already present')
            self.proc.speed[i] = speed
            self.proc.source[i] = src
            self.proc.flag[i] = Dicts.flags['valid']
        else:
            # print('new depth')
            if depth < self.proc.depth[valid][0]:
                m_ids = [0, 1]
                # print('before beginning: %s' % j)

            elif depth > self.proc.depth[valid][-1]:
                j += 1
                m_ids = [-2, -1]
                # print('after end')

            else:
                if self.proc.depth[valid][v_i] < depth:
                    m_ids = [v_i, v_i + 1]
                else:
                    m_ids = [v_i - 1, v_i]
                # print('in the middle')

            di = np.array([self.proc.depth[valid][m_ids[0]], self.proc.depth[valid][m_ids[1]]])
            a = np.array([[di[0], 1.], [di[1], 1.]])

            # interpolate for pressure
            pi = np.array([self.proc.pressure[valid][m_ids[0]], self.proc.pressure[valid][m_ids[1]]])
            pm, pc = np.linalg.lstsq(a, pi)[0]
            self.proc.pressure = np.insert(self.proc.pressure, j, pm * depth + pc)
            # print(self.proc.pressure[0], self.proc.pressure.size)

            # interpolate for temp
            ti = np.array([self.proc.temp[valid][m_ids[0]], self.proc.temp[valid][m_ids[1]]])
            tm, tc = np.linalg.lstsq(a, ti)[0]
            self.proc.temp = np.insert(self.proc.temp, j, tm * depth + tc)
            # print(self.proc.temp[0], self.proc.temp.size)

            # interpolate for conductivity
            ci = np.array([self.proc.conductivity[valid][m_ids[0]], self.proc.conductivity[valid][m_ids[1]]])
            cm, cc = np.linalg.lstsq(a, ci)[0]
            self.proc.conductivity = np.insert(self.proc.conductivity, j, cm * depth + cc)
            # print(self.proc.conductivity[0], self.proc.conductivity.size)

            # interpolate for sal
            si = np.array([self.proc.sal[valid][m_ids[0]], self.proc.sal[valid][m_ids[1]]])
            sm, sc = np.linalg.lstsq(a, si)[0]
            self.proc.sal = np.insert(self.proc.sal, j, sm * depth + sc)
            # print(self.proc.sal[0], self.proc.sal.size)

            self.proc.depth = np.insert(self.proc.depth, j, depth)
            self.proc.speed = np.insert(self.proc.speed, j, speed)
            self.proc.source = np.insert(self.proc.source, j, src)
            self.proc.flag = np.insert(self.proc.flag, j, Dicts.flags['valid'])

            self.proc.num_samples += 1

    def insert_sis_speed(self, depth, speed, src=Dicts.sources['user']):
        logger.debug("insert speed to sis data: d:%s, vs:%s" % (depth, speed))

        # we need to take care of valid samples and user-invalidated samples (to avoid to brake in case un-flagged)
        valid = self.sis_thinned  # valid samples
        iv = np.indices(self.sis.flag.shape)[0][valid]  # indices of valid samples
        user_invalid = self.sis.flag == Dicts.flags['user']  # user-invalidate samples
        possible = np.logical_or(valid, user_invalid)  # possible samples
        ip = np.indices(self.sis.flag.shape)[0][possible]  # indices of possible samples

        # find depth index both in the valid and in the possible samples
        try:
            # noinspection PyTypeChecker
            v_i = np.argwhere(self.sis.depth[valid] > depth)[0][0]  # the index in the valid array
            i = iv[v_i]  # the corresponding index of the masked index in the full array
        except IndexError:  # in case that there are not
            v_i = self.sis.depth[valid].size - 1
            i = iv[v_i]
        try:
            # noinspection PyTypeChecker
            p_i = np.argwhere(self.sis.depth[possible] > depth)[0][0]  # the index in the possible array
            j = ip[p_i]
        except IndexError:  # in case that there are not
            p_i = self.sis.depth[possible].size - 1
            j = ip[p_i]

        # check if we already have this depth in the masked array
        d_exists = self.sis.depth[valid][v_i] == depth

        # manipulate profile (linear interpolation)
        if d_exists:
            # print('already present')
            self.sis.speed[i] = speed
            self.sis.source[i] = src
            self.sis.flag[i] = Dicts.flags['thin']
        else:
            # print('new depth')
            if depth < self.sis.depth[valid][0]:
                m_ids = [0, 1]
                # print('before beginning: %s' % j)

            elif depth > self.sis.depth[valid][-1]:
                j += 1
                m_ids = [-2, -1]
                # print('after end')

            else:
                if self.sis.depth[valid][v_i] < depth:
                    m_ids = [v_i, v_i + 1]
                else:
                    m_ids = [v_i - 1, v_i]
                # print('in the middle')

            di = np.array([self.sis.depth[valid][m_ids[0]], self.sis.depth[valid][m_ids[1]]])
            a = np.array([[di[0], 1.], [di[1], 1.]])

            # interpolate for pressure
            pi = np.array([self.sis.pressure[valid][m_ids[0]], self.sis.pressure[valid][m_ids[1]]])
            pm, pc = np.linalg.lstsq(a, pi)[0]
            self.sis.pressure = np.insert(self.sis.pressure, j, pm * depth + pc)
            # print(self.sis.pressure[0], self.sis.pressure.size)

            # interpolate for temp
            ti = np.array([self.sis.temp[valid][m_ids[0]], self.sis.temp[valid][m_ids[1]]])
            tm, tc = np.linalg.lstsq(a, ti)[0]
            self.sis.temp = np.insert(self.sis.temp, j, tm * depth + tc)
            # print(self.sis.temp[0], self.sis.temp.size)

            # interpolate for conductivity
            ci = np.array([self.sis.conductivity[valid][m_ids[0]], self.sis.conductivity[valid][m_ids[1]]])
            cm, cc = np.linalg.lstsq(a, ci)[0]
            self.sis.conductivity = np.insert(self.sis.conductivity, j, cm * depth + cc)
            # print(self.proc.conductivity[0], self.proc.conductivity.size)

            # interpolate for sal
            si = np.array([self.sis.sal[valid][m_ids[0]], self.sis.sal[valid][m_ids[1]]])
            sm, sc = np.linalg.lstsq(a, si)[0]
            self.sis.sal = np.insert(self.sis.sal, j, sm * depth + sc)
            # print(self.proc.sal[0], self.proc.sal.size)

            self.sis.depth = np.insert(self.sis.depth, j, depth)
            self.sis.speed = np.insert(self.sis.speed, j, speed)
            self.sis.source = np.insert(self.sis.source, j, src)
            self.sis.flag = np.insert(self.sis.flag, j, Dicts.flags['thin'])

            self.sis.num_samples += 1

    def insert_proc_temp_sal(self, depth, temp, sal):
        logger.debug("insert temp, sal to proc data: d:%s, t:%s, s:%s" % (depth, temp, sal))

        speed = Oc.speed(d=depth, t=temp, s=sal, lat=self.meta.latitude)

        # we need to take care of valid samples and user-invalidated samples (to avoid to brake in case un-flagged)
        valid = self.proc.flag == Dicts.flags['valid']  # valid samples
        iv = np.indices(self.proc.flag.shape)[0][valid]  # indices of valid samples
        user_invalid = self.proc.flag == Dicts.flags['user']  # user-invalidate samples
        possible = np.logical_or(valid, user_invalid)  # possible samples
        ip = np.indices(self.proc.flag.shape)[0][possible]  # indices of possible samples

        # find depth index both in the valid and in the possible samples
        try:
            # noinspection PyTypeChecker
            v_i = np.argwhere(self.proc.depth[valid] > depth)[0][0]  # the index in the valid array
            i = iv[v_i]  # the corresponding index of the masked index in the full array
        except IndexError:  # in case that there are not
            v_i = self.proc.depth[valid].size - 1
            i = iv[v_i]
        try:
            # noinspection PyTypeChecker
            p_i = np.argwhere(self.proc.depth[possible] > depth)[0][0]  # the index in the possible array
            j = ip[p_i]
        except IndexError:  # in case that there are not
            p_i = self.proc.depth[possible].size - 1
            j = ip[p_i]

        # check if we already have this depth in the masked array
        d_exists = self.proc.depth[valid][v_i] == depth

        # manipulate profile (linear interpolation)
        if d_exists:
            # print('already present')
            self.proc.temp[i] = temp
            self.proc.sal[i] = sal
            self.proc.speed[i] = speed
            self.proc.source[i] = Dicts.sources['user']
            self.proc.flag[i] = Dicts.flags['valid']
        else:
            # print('new depth')
            if depth < self.proc.depth[valid][0]:
                m_ids = [0, 1]
                # print('before beginning: %s' % j)

            elif depth > self.proc.depth[valid][-1]:
                j += 1
                m_ids = [-2, -1]
                # print('after end')

            else:
                if self.proc.depth[valid][v_i] < depth:
                    m_ids = [v_i, v_i + 1]
                else:
                    m_ids = [v_i - 1, v_i]
                # print('in the middle')

            di = np.array([self.proc.depth[valid][m_ids[0]], self.proc.depth[valid][m_ids[1]]])
            a = np.array([[di[0], 1.], [di[1], 1.]])

            # interpolate for pressure
            pi = np.array([self.proc.pressure[valid][m_ids[0]], self.proc.pressure[valid][m_ids[1]]])
            pm, pc = np.linalg.lstsq(a, pi)[0]
            self.proc.pressure = np.insert(self.proc.pressure, j, pm * depth + pc)
            # print(self.proc.pressure[0], self.proc.pressure.size)

            # interpolate for conductivity
            ci = np.array([self.proc.conductivity[valid][m_ids[0]], self.proc.conductivity[valid][m_ids[1]]])
            cm, cc = np.linalg.lstsq(a, ci)[0]
            self.proc.conductivity = np.insert(self.proc.conductivity, j, cm * depth + cc)
            # print(self.proc.conductivity[0], self.proc.conductivity.size)

            self.proc.depth = np.insert(self.proc.depth, j, depth)
            self.proc.speed = np.insert(self.proc.speed, j, speed)
            self.proc.temp = np.insert(self.proc.temp, j, temp)
            self.proc.sal = np.insert(self.proc.sal, j, sal)
            self.proc.source = np.insert(self.proc.source, j, Dicts.sources['user'])
            self.proc.flag = np.insert(self.proc.flag, j, Dicts.flags['valid'])

            self.proc.num_samples += 1

    def extend_profile(self, extender, ext_type):
        """ Use the extender samples to extend the profile """
        logger.debug("extension source type: %s" % Dicts.first_match(Dicts.sources, ext_type))
        extender.cur.proc.source[:] = ext_type

        # find the max valid depth in the current profile
        if self.proc.num_samples > 0:
            vi = self.proc_valid
            ivs = np.indices(self.proc.flag.shape)[0][vi]  # indices of valid samples
            max_depth = self.proc.depth[vi].max()  # this is the max of the valid samples
            # noinspection PyTypeChecker
            vi_idx = np.argwhere(self.proc.depth[vi] >= max_depth)[0][0]  # index of the max depth
            max_idx = ivs[vi_idx]  # index of the max depth in the original array
        else:
            max_depth = 0
            max_idx = 0
        # logger.debug("orig.max depth: %s[%s]" % (max_depth, max_idx))

        # find the depth values in the extender that are deeper than the current (valid) max depth
        ext_vi = extender.cur.proc_valid
        try:
            # noinspection PyTypeChecker
            ind2 = np.argwhere(extender.cur.proc.depth[ext_vi][:] > max_depth)[0][0]
            if ind2 <= 0:
                logger.info("nothing to extend with")
                return True
            # logger.debug("ext.max depth: [%s]" % ind2)
        except IndexError as e:
            logger.warning("too short to extend with: %s" % e)
            return True

        # stack the extending samples after the last valid (max depth) index
        self.proc.pressure = np.hstack([self.proc.depth[:max_idx],
                                        np.zeros_like(extender.cur.proc.depth[ext_vi][ind2:])])
        self.proc.depth = np.hstack([self.proc.depth[:max_idx],
                                     extender.cur.proc.depth[ext_vi][ind2:]])
        self.proc.speed = np.hstack([self.proc.speed[:max_idx],
                                     extender.cur.proc.speed[ext_vi][ind2:]])
        self.proc.temp = np.hstack([self.proc.temp[:max_idx],
                                    extender.cur.proc.temp[ext_vi][ind2:]])
        self.proc.conductivity = np.hstack([self.proc.sal[:max_idx],
                                            np.zeros_like(extender.cur.proc.sal[ext_vi][ind2:])])
        self.proc.sal = np.hstack([self.proc.sal[:max_idx],
                                   extender.cur.proc.sal[ext_vi][ind2:]])
        self.proc.source = np.hstack([self.proc.source[:max_idx],
                                      extender.cur.proc.source[ext_vi][ind2:]])
        self.proc.flag = np.hstack([self.proc.flag[:max_idx],
                                    extender.cur.proc.flag[ext_vi][ind2:]])
        self.proc.num_samples = self.proc.depth.size

        # update processing info
        if ext_type == Dicts.atlases['ref']:
            self.modify_proc_info(Dicts.proc_user_infos['EXT_REF'])

        elif ext_type == Dicts.atlases['RTOFS']:
            self.modify_proc_info(Dicts.proc_user_infos['EXT_RTOFS'])

        elif ext_type == Dicts.atlases['WOA09']:
            self.modify_proc_info(Dicts.proc_user_infos['EXT_WOA09'])

        elif ext_type == Dicts.atlases['WOA13']:
            self.modify_proc_info(Dicts.proc_user_infos['EXT_WOA13'])

        else:
            logger.warning("unknown atlases: %s" % ext_type)
            return False

        return True

    def modify_proc_info(self, info):

        if info not in Dicts.proc_user_infos.values():
            if info not in Dicts.proc_import_infos.values():
                raise RuntimeError("invalid processing info: %s" % info)

        # if empty, add the info
        if not self.meta.proc_info:
            self.meta.proc_info = info
            return

        # check if it is already present
        tokens = self.meta.proc_info.split(';')
        if info not in tokens:
            self.meta.proc_info += ';%s' % info

    def remove_user_proc_info(self):

        # if empty, nothing to do
        if not self.meta.proc_info:
            return

        # check if it is already present
        tokens = self.meta.proc_info.split(';')
        self.meta.proc_info = None
        for i, token in enumerate(tokens):

            if token in Dicts.proc_import_infos.values():

                if self.meta.proc_info is None:
                    self.meta.proc_info = '%s' % token

                else:
                    self.meta.proc_info += ';%s' % token

    def clone_data_to_proc(self):
        """Clone the raw data samples into proc samples

        The operation eliminates the direction-flagged samples
        """
        logger.info("cloning raw data to proc samples")

        if self.data.num_samples == 0:
            return

        vi = self.data_valid  # invalid samples (no direction-flagged)

        self.init_proc(np.sum(vi))
        self.proc.pressure[:] = self.data.pressure[vi]
        self.proc.depth[:] = self.data.depth[vi]
        self.proc.speed[:] = self.data.speed[vi]
        self.proc.temp[:] = self.data.temp[vi]
        self.proc.conductivity[:] = self.data.conductivity[vi]
        self.proc.sal[:] = self.data.sal[vi]
        self.proc.source[:] = self.data.source[vi]
        self.proc.flag[:] = self.data.flag[vi]

        self.update_proc_time()

    def clone_proc_to_sis(self):
        """Clone the processed data samples into sis samples"""
        logger.info("cloning proc data to sis samples")

        if self.proc.num_samples == 0:
            return

        self.init_sis(self.proc.depth.size)
        self.sis.pressure[:] = self.proc.pressure
        self.sis.depth[:] = self.proc.depth
        self.sis.speed[:] = self.proc.speed
        self.sis.temp[:] = self.proc.temp
        self.sis.conductivity[:] = self.proc.conductivity
        self.sis.sal[:] = self.proc.sal
        self.sis.source[:] = self.proc.source
        self.sis.flag[:] = self.proc.flag

    def update_proc_time(self):
        self.meta.update_proc_time()

    def replace_proc_sal(self, source):  # unused
        try:
            self.proc.sal = np.interp(self.proc.depth[:], source.cur.proc.depth[:], source.cur.proc.sal[:])
        except Exception as e:
            logger.warning("in replace salinity, %s" % e)
            return False
        return True

    def replace_proc_temp_sal(self, source):  # unused
        try:
            self.proc.temp = np.interp(self.proc.depth[:], source.cur.proc.depth[:], source.cur.proc.temp[:])
            self.proc.sal = np.interp(self.proc.depth[:], source.cur.proc.depth[:], source.cur.proc.sal[:])
        except Exception as e:
            logger.warning("in replace temp/sal, %s" % e)
            return False
        return True

    # - thinning

    def thin(self, tolerance):
        """Thin the sis data"""
        logger.info("thinning the sis samples")

        # if the profile is too short, we just pass it back
        if self.sis.depth[self.sis_valid].size < 100:
            self.sis.flag[self.sis_valid] = Dicts.flags['thin']
            logger.debug("skipping thinning for short profile (%d samples)" % self.sis.depth[self.sis_valid].size)
            return True

        # - 1000 points for: EM2040, EM710, EM302 and EM122;
        # - 570 points for: EM3000, EM3002, EM1002, EM300, EM120
        # TODO: the resulting profile must be less than 30kB
        flagged = self.sis.flag[self.sis_valid][:]
        idx_start = 0
        idx_end = self.sis.depth[self.sis_valid].size - 1
        # logger.debug('first: %s, last: %s[%s]'
        #              % (self.sis.depth[self.sis_valid][idx_start],
        #                 self.sis.depth[self.sis_valid][idx_end],
        #                 self.sis.flag[self.sis_valid][idx_end]))
        self.douglas_peucker_1d(idx_start, idx_end, tolerance=tolerance, data=flagged)
        self.sis.flag[self.sis_valid] = flagged[:]

        # logger.info("thinned: %s" % self.sis.flag[self.sis_thinned].size)
        return True

    def douglas_peucker_1d(self, start, end, tolerance, data):
        """ Recursive implementation """
        # logger.debug("dp: %s, %s" % (start, end))

        # We always keep end points
        data[start] = Dicts.flags['thin']
        data[end] = Dicts.flags['thin']

        slope = (self.sis.speed[self.sis_valid][end] - self.sis.speed[self.sis_valid][start]) / \
                (self.sis.depth[self.sis_valid][end] - self.sis.depth[self.sis_valid][start])

        max_dist = 0
        max_ind = 0
        for ind in range(start + 1, end):
            dist = abs(self.sis.speed[self.sis_valid][start] +
                       slope * (self.sis.depth[self.sis_valid][ind] - self.sis.depth[self.sis_valid][start]) -
                       self.sis.speed[self.sis_valid][ind])

            if dist > max_dist:
                max_dist = dist
                max_ind = ind

        if max_dist <= tolerance:
            return

        else:
            data[max_ind] = Dicts.flags['thin']
            # print(max_ind, max_dist, data[max_ind])
            self.douglas_peucker_1d(start, max_ind, tolerance, data=data)
            self.douglas_peucker_1d(max_ind, end, tolerance, data=data)
            return

    # - debugging

    def data_debug_plot(self, more=False):
        """Create a debug plot with the data, optionally with the extra data if available"""
        if self.data.depth is None:
            return
        else:
            self._plot(samples=self.data, more=more, kind='data')

    def proc_debug_plot(self, more=False):
        """Create a debug plot with the processed data, optionally with the extra data if available"""
        if self.proc.depth is None:
            return
        else:
            self._plot(samples=self.proc, more=more, kind='proc')

    def sis_debug_plot(self, more=False):
        """Create a debug plot with the sis-targeted data, optionally with the extra data if available"""
        if self.sis.depth is None:
            return
        else:
            self._plot(samples=self.sis, more=more, kind='sis')

    def _plot(self, samples, more, kind):
        import matplotlib.pyplot as plt
        plt.figure("[%s] %s" % (self.meta.original_path, kind), dpi=120)

        if samples.speed is not None:
            plt.subplot(231)  # speed
            plt.plot(samples.speed, samples.depth)
            plt.gca().invert_yaxis()
            plt.grid(True)
            plt.title('speed')

        if samples.temp is not None:
            plt.subplot(232)  # temp
            plt.plot(samples.temp, samples.depth)
            plt.gca().invert_yaxis()
            plt.grid(True)
            plt.title('temp')

        if samples.sal is not None:
            plt.subplot(233)  # sal
            plt.plot(samples.sal, samples.depth)
            plt.gca().invert_yaxis()
            plt.grid(True)
            plt.title('sal')

        if samples.flag is not None:
            plt.subplot(234)  # source
            plt.plot(samples.source, samples.depth)
            plt.gca().invert_yaxis()
            plt.grid(True)
            plt.title('source')

        if samples.flag is not None:
            plt.subplot(235)  # flag
            plt.plot(samples.flag, samples.depth)
            plt.gca().invert_yaxis()
            plt.grid(True)
            plt.title('flag')

        plt.subplot(236)  # meta
        fs = 8  # font size
        plt.title('meta[%s]' % kind)
        plt.axis('off')
        plt.text(0.1, 0.25, self.meta.debug_info(), fontsize=fs)
        plt.show(block=False)

        if more:
            self.more.debug_plot()

    def interpolate_proc_speed_at_depth(self, depth, points=3):
        """ Return speed difference at the passed depth"""

        # identify start/end of profile data to be used for interpolation
        idx = np.searchsorted(self.proc.depth[self.proc_dqa_valid], depth)
        start = (idx - points) if (idx - points >= 0) else 0
        end = idx + points

        # calculate coefficients and interpolated speed
        coefficients = np.polyfit(self.proc.depth[self.proc_dqa_valid][start:end],
                                  self.proc.speed[self.proc_dqa_valid][start:end], 2)
        cast_speed = np.poly1d(coefficients)(depth)

        return cast_speed

    def compute_ray_paths(self, draft, thetas_deg, travel_times=None, res=.005, b_project=False):
        """Returns a RayPath object for each launch angle."""
        if not draft or draft == 'Unknown':
            draft = 0.0
        else:
            draft = float(draft)

        depths = self.proc.depth[self.proc_dqa_valid] - draft
        speeds = self.proc.speed[self.proc_dqa_valid]

        ray_paths = []
        for launch in thetas_deg:

            params = RayTracing.get_svp_layer_parameters(np.deg2rad(launch), depths, speeds)
            if travel_times is None:
                tt = np.arange(res, params[-2][-1], res)  # make travel_times to reach end of profile
            else:
                tt = np.array(travel_times)

            rays = RayTracing.ray_trace(tt, depths, speeds, params, b_project=b_project)
            rays[:, 0] += draft

            ray_paths.append(RayPath(np.vstack((tt, rays.transpose())).transpose()))

        return ray_paths

    def compare_profile(self, profile, angle):

        dep_max = min(self.proc.depth[self.proc_dqa_valid].max(), profile.proc.depth[profile.proc_dqa_valid].max())
        if dep_max <= 400:
            tt_inc = 0.002  # Travel time increment in seconds.
        elif dep_max <= 800:
            tt_inc = 0.005
        else:
            tt_inc = 0.01

        draft1 = 0.0  # TODO
        draft2 = 0.0  # TODO
        draft = max(draft1, draft2)

        # Generate the travel time table for the two profiles.
        ray1 = self.compute_ray_paths(draft, [angle], res=tt_inc)[0]
        ray2 = profile.compute_ray_paths(draft, [angle], res=tt_inc)[0]
        
        nr_points = min(len(ray1.data), len(ray2.data))
        if nr_points == 0:
            raise RuntimeError("One of the two profiles is too shallow!")

        depth1 = ray1.data[:nr_points, 1]
        depth2 = ray2.data[:nr_points, 1]
        delta_depth = depth2 - depth1
        larger_depths = np.maximum(depth1, depth2)
        pct_diff = np.absolute(delta_depth / larger_depths) * 100.0
        # noinspection PyUnresolvedReferences
        max_diff_index = pct_diff.argmax()
        # noinspection PyUnresolvedReferences
        max_diff = pct_diff[max_diff_index]
        max_diff_depth = larger_depths[max_diff_index]

        # create output message

        p1 = "<pre style='margin:1px;'>"
        p2 = "</pre>"

        self_path = self.meta.original_path
        self_path = self_path if os.path.exists(self_path) else os.path.basename(self_path)
        profile_path = profile.meta.original_path
        profile_path = profile_path if os.path.exists(profile_path) else os.path.basename(profile_path)

        msg = "%s<b>SUMMARY OF RESULTS - COMPARE 2 CASTS</b>%s<br>" % (p1, p2)

        msg += "%s<b>Sound Speed library</b>:                 %s%s" % (p1, soundspeed_version, p2)
        msg += "%s<b>Reference profile</b>:                   %s%s" % (p1, self_path, p2)
        msg += "%s<b>Comparison profile</b>:                  %s%s" % (p1, profile_path, p2)
        msg += "%s<b>Reference instrument</b>:                sensor-%s, probe-%s%s%s" \
               % (p1, self.meta.sensor, self.meta.probe, ", sn-%s" % self.meta.sn if self.meta.sn else "", p2)
        msg += "%s<b>Comparison instrument</b>:               sensor-%s, probe-%s%s%s<br>" \
               % (p1, profile.meta.sensor, profile.meta.probe, ", sn-%s" % profile.meta.sn if profile.meta.sn else "",
                  p2)

        msg += "%s<b>Draft</b>:                               %.2f m%s" % (p1, draft, p2)
        msg += "%s<b>Maximum Common Depth</b>:                %.2f m%s" % (p1, dep_max, p2)
        msg += "%s<b>Maximum Depth Percentage Difference</b>: %.2f%%%s" % (p1, max_diff, p2)
        msg += "%s<b>Maximum Percentage Difference at</b>:    %.2f m%s<br>" % (p1, max_diff_depth, p2)

        msg += "%s<b>Max percentage diff. line and last line of travel time table</b>:%s" % (p1, p2)

        msg += "%sTravel time, Avg Depth, Depth Diff, Pct Depth Diff, Avg Crosstrack, Crosstrack Diff, " \
               "Pct Crosstrack Diff%s" % (p1, p2)
        for ni in (max_diff_index, nr_points - 1):
            msg += "%s%9.2f s,%8.2f m,%9.2f m,%14.2f%%,%13.2f m,%14.2f m,%19.2f%%%s" \
                   % (
                       p1,
                       ray1.data[ni, 0],  # travel time
                       np.average([ray1.data[ni, 1], ray2.data[ni, 1]]),  # avg. depth
                       np.absolute(delta_depth[ni]),  # depth diff.
                       pct_diff[ni],  # pct. depth diff.
                       np.average([ray1.data[ni, 2], ray2.data[ni, 2]]),  # avg. cross-track
                       np.absolute(ray1.data[ni, 2] - ray2.data[ni, 2]),  # cross-track diff.
                       100.0 * np.absolute(ray1.data[ni, 2] - ray2.data[ni, 2]) /
                       max(ray1.data[ni, 2], ray2.data[ni, 2]),  # pct. cross-track diff.
                       p2
                   )

        msg += '<br>%s%s%s<br>' % (p1, time.ctime(), p2)

        if max_diff > 0.25:
            msg += "%s<b>RESULTS INDICATE PROBLEM.</b>%s" % (p1, p2)
            msg += "%sThe absolute value of percent depth difference exceeds the recommended amount (.25).%s" % (p1, p2)
            msg += "%sIf test was conducted to compare 2 casts for possible grouping into one representative%s" \
                   % (p1, p2)
            msg += "%scast, then the 2 casts should NOT be grouped.%s" % (p1, p2)
            msg += "%sIf test was run as part of a Data Quality Assurance for 2 simultaneous casts, then one%s" \
                   % (p1, p2)
            msg += "%sor both of the instruments used is functioning improperly. Investigate further by%s" % (p1, p2)
            msg += "%sperforming simultaneous casts of each of the instruments with a third instrument.%s" % (p1, p2)
            msg += "%sThen rerun this procedure with the 2 new pairs of casts to determine which one of%s" % (p1, p2)
            msg += "%sthe instruments is not functioning properly.%s" % (p1, p2)
            msg += "%sIf the test was run to compare an XBT cast with the last CTD cast, then it is time%s" % (p1, p2)
            msg += "%sto take a new CTD cast.%s<br>" % (p1, p2)

            msg += "%s<b>RESULTS</b>: PERCENT DEPTH DIFFERENCE TOO LARGE%s" % (p1, p2)

        else:
            msg += "%s<b>RESULTS OK.</b>%s" % (p1, p2)
            msg += "%sPercent depth difference is within recommended bounds.%s<br>" % (p1, p2)

            msg += "%s<b>RESULTS</b>: PERCENT DEPTH DIFFERENCE OK%s" % (p1, p2)

        return msg
