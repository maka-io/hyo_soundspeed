import datetime
import logging
import re
import time

import numpy

logger = logging.getLogger(__name__)

from hydroffice.soundspeed.formats.readers.abstract import AbstractTextReader
from hydroffice.soundspeed.profile.dicts import Dicts
from hydroffice.soundspeed.base.callbacks.cli_callbacks import CliCallbacks

from hydroffice.soundspeed.temp.regex_helpers import Profile, getMetaFromCoord, robust_re_number, \
    parseNumbers
from hydroffice.soundspeed.temp import coordinates

# Note that Hex header is copied into the CNV header verbatim so these can be used in either.
SEACAT_SBE19_HEX_YEAR = r'SEACAT\sPROFILER.*?(?P<day>\d+)/(?P<month>\d+)/(?P<year>\d+)'
SEACAT_SBE19_STATUS_DATETIME = r'SEACAT\sPROFILER.*?(?P<month>\d+)/(?P<day>\d+)/(?P<year>\d+)\s*(?P<hour>\d+)[\s:]*(?P<minute>\d+)[\s:]*(?P<second>\d*)'
SEACAT_SBE19_HEX_MONTHDAY = r'cast.*?(?P<month>\d+)/(?P<day>\d+)'
SEACAT_SBE19_HEX_TIME = r'cast.*?(?P<hour>\d+):(?P<minute>\d+):(?P<second>\d+)'
SEACAT_SBE19_HEX_YEARRE = re.compile(SEACAT_SBE19_HEX_YEAR)
SEACAT_SBE19_HEX_MONTHDAYRE = re.compile(SEACAT_SBE19_HEX_MONTHDAY)
SEACAT_SBE19_HEX_TIMERE = re.compile(SEACAT_SBE19_HEX_TIME)

SEACAT_SBE19PLUS_STATUS_DATETIME = r'SeacatPlus\sV.*?(?P<full>(?P<day>\d+)\s+(?P<month>\w{3})\s+(?P<year>\d{4})\s*(?P<hour>\d+)[\s:]*(?P<minute>\d+)[\s:]*(?P<second>\d*))'
SEACAT_SBE19PLUSV2_STATUS_DATETIME = r'SBE\s19plus\sV.*?(?P<full>(?P<day>\d+)\s+(?P<month>\w{3})\s+(?P<year>\d{4})\s*(?P<hour>\d+)[\s:]*(?P<minute>\d+)[\s:]*(?P<second>\d*))'
SEACAT_CNV_START_TIME = r'start_time\s*=\s*(?P<full>(?P<month>\w{3})\s+(?P<day>\d+)\s+(?P<year>\d{4})\s*(?P<hour>\d+)[\s:]*(?P<minute>\d+)[\s:]*(?P<second>\d*))'
SEACAT_CNV_START_TIMERE = re.compile(SEACAT_CNV_START_TIME)
SEACAT_SBE19PLUS_HEX_DATE_TXT = r'cast.*?(?P<full>(?P<day>\d+)\s+(?P<month>\w{3})\s+(?P<year>\d{4}))'
SEACAT_SBE19PLUS_HEX_DATE_TXT_FORMAT = "%d %b %Y"
# >>> time.strptime("30 nov 00", SEACAT_SBE19PLUS_HEX_DATE_TXT_FORMAT)
# (2000, 11, 30, 0, 0, 0, 3, 335, -1)
SEACAT_SBE19PLUS_HEX_DATE_TXTRE = re.compile(SEACAT_SBE19PLUS_HEX_DATE_TXT)

SEACAT_SBE19PLUS_HEX_DATE_MDY = r'cast.*?(?P<full>(?P<month>\d{2})\s+(?P<day>\d{2})\s+(?P<year>\d{4}))'
SEACAT_SBE19PLUS_HEX_DATE_MDY_FORMAT = "%m %d %Y"
SEACAT_SBE19PLUS_HEX_DATE_MDYRE = re.compile(SEACAT_SBE19PLUS_HEX_DATE_MDY)
# both use same time format
SEACAT_SBE19PLUS_HEX_TIME = SEACAT_SBE19_HEX_TIME
SEACAT_SBE19PLUS_HEX_TIMERE = re.compile(SEACAT_SBE19PLUS_HEX_TIME)

# * System UpLoad Time = Sep 08 2008 14:18:19
SEACAT_SBE911_HEX_DATETIME = r'System\s*UpLoad\s*Time\s*=\s*(?P<full>(?P<mon>\w*)\s*(?P<day>\d+)\s*(?P<yr>\d+)\s*(?P<hour>\d+)[\s:]*(?P<minute>\d+)[\s:]*(?P<second>\d*))'
SEACAT_SBE911_HEX_DATETIMERE = re.compile(SEACAT_SBE911_HEX_DATETIME)
SEACAT_HEX_LAT = r'Latitude\s*[:=]\s*(?P<lat>.*)'
SEACAT_HEX_LON = r'Longitude\s*[:=]\s*(?P<lon>.*)'
SEACAT_HEX_LATRE = re.compile(SEACAT_HEX_LAT)
SEACAT_HEX_LONRE = re.compile(SEACAT_HEX_LON)


SeacatHex_SBE19_NCASTS = r'(\s+ncasts[\s=]+)(?P<NumCasts>\d+)'
SeacatHex_SBE19_NCASTSRE = re.compile(SeacatHex_SBE19_NCASTS, re.IGNORECASE)
SeacatHex_SBE19PLUS_NCASTS = r'''samples  #start of line has samples
                                 .*?         #everything on the same line up to the casts =
                                 casts[\s=]+ #"casts = " including whitespace
                                 (?P<NumCasts>\d+) #the number of casts
                              '''
SeacatHex_SBE19PLUS_NCASTSRE = re.compile(SeacatHex_SBE19PLUS_NCASTS, re.VERBOSE | re.IGNORECASE)

SeacatHex_SBE19PLUS_TYPE = r'SBE\s*19\s*PLUS'  # picks up SBE19Plus and V2
SeacatHex_SBE19_TYPE = r'SBE\s*19'
SeacatHex_SBE911_TYPE = r'SBE\s*9\s*'
SeacatHex_SBE49_TYPE = r'SBE\s*49\s*'

SeacatHex_SBE19PLUS_TYPERE = re.compile(SeacatHex_SBE19PLUS_TYPE, re.IGNORECASE)
SeacatHex_SBE19_TYPERE = re.compile(SeacatHex_SBE19_TYPE, re.IGNORECASE)
SeacatHex_SBE911_TYPERE = re.compile(SeacatHex_SBE911_TYPE, re.IGNORECASE)
SeacatHex_SBE49_TYPERE = re.compile(SeacatHex_SBE49_TYPE, re.IGNORECASE)
SeacatHex_SN = r'Temperature\s*SN\s*=\s*(?P<SN>\d+)'
SeacatHex_SNRE = re.compile(SeacatHex_SN, re.IGNORECASE)

SeacatCNV_NVALUES = r'nvalues\s*=\s*(?P<nvalues>\d*)'
SeacatCNV_NVALUESRE = re.compile(SeacatCNV_NVALUES, re.IGNORECASE)
SeacatCNV_SPAN_N = r'span\s*%d\s*=\s*(?P<min>%s)\s*,\s*(?P<max>%s)'
SeacatCNV_SPAN_list, SeacatCNV_SPAN_listRE = [], []
for n in range(7):
    SeacatCNV_SPAN_list.append(SeacatCNV_SPAN_N % (n, robust_re_number, robust_re_number))
    SeacatCNV_SPAN_listRE.append(re.compile(SeacatCNV_SPAN_list[n], re.IGNORECASE))
SeacatCNV_INTERVAL = r'interval\s=\s(?P<units>\w*):\s*(?P<interval>[\d.]*)'
SeacatCNV_INTERVALRE = re.compile(SeacatCNV_INTERVAL, re.IGNORECASE)
# SeacatCNV_DATA =r'\s+(?P<pressure>[e\+\-\d.]+)\s+(?P<conductivity>[e\+\-\d.]+)\s+(?P<temperature>[e\+\-\d.]+)\s+(?P<salinity>[e\+\-\d.]+)\s+(?P<density>[e\+\-\d.]+)\s+(?P<velocity>[e\+\-\d.]+)\s+(?P<voltage>[e\+\-\d.]+)'
# SeacatCNV_DATA_types = [('P', scipy.float32), ('C', scipy.float32), ('T', scipy.float32), ('S', scipy.float32), ('D', scipy.float32), ('SV', scipy.float32), ('V', scipy.float32)]
# scipy.fromregex(fname, SeacatCNV_DATA+r'\s*\n',  SeacatCNV_DATA_types)


class Seabird(AbstractTextReader):
    """Seabird reader -> CTD style

    Info: http://www.seabird.com/
    """

    def __init__(self):
        super(Seabird, self).__init__()
        self.desc = "Seabird"
        self._ext.add('cnv')

    def read(self, data_path, settings, callbacks=CliCallbacks(), progress=None):
        logger.debug('*** %s ***: start' % self.driver)

        self.s = settings
        self.cb = callbacks

        self.init_data()  # create a new empty profile list

        self._read(data_path=data_path)
        self._parse_header()
        self._parse_body()

        # initialize probe/sensor type
        self.ssp.cur.meta.sensor_type = Dicts.sensor_types['CTD']
        self.ssp.cur.meta.probe_type = Dicts.probe_types['SBE']

        self.fix()
        self.finalize()

        logger.debug('*** %s ***: done' % self.driver)
        return True

    def _parse_header(self):
        s = "\n".join(self.lines)
        header, _data = s.split('*END*')
        meta = {}
        if SeacatHex_SBE19PLUS_TYPERE.search(header):
            seacat_type = 'SBE19PLUS'
        elif SeacatHex_SBE19_TYPERE.search(header):
            seacat_type = 'SBE19'
        elif SeacatHex_SBE911_TYPERE.search(header):
            seacat_type = 'SBE911'
        elif SeacatHex_SBE49_TYPERE.search(header):
            seacat_type = 'SBE49'
        else:
            seacat_type = ''
        if seacat_type:
            # Parsing lines like--  # name 0 = prDM: Pressure, Digiquartz [db]
            expr = r'''\#\s*name\s*       #lead pound sign, name
                        (?P<num>\d+)      #column number
                        \s*=\s*(?P<rawname>[^:]*):\s*  #spaces, equals and stuff up to the colon
                        (?P<col>\w*)      #the column name (Pressure, Conductivity, Temperature, Salinity, Density, Sound Velocity (we only get Sound as we don't allow spaces currently)
                        (?P<units>.*)     #The rest of the data -- units are embedded here if we want them later
                        '''
            matches = re.findall(expr, s, re.VERBOSE)
            for i, col in enumerate(matches):
                if int(col[0]) != i:
                    raise Exception('Not all column names read correctly, can not parse file')
            for tag, metaname in (("CRUISE:", 'Project'), ("STATION:", 'Survey')):
                m = re.search(tag + "(.*)", header, re.IGNORECASE)
                if m:
                    meta[metaname] = m.group(1).strip()

            meta['columns'] = matches
            try:
                if seacat_type == "SBE19PLUS":
                    m = SEACAT_SBE19PLUS_HEX_DATE_TXTRE.search(header)
                    if m:
                        yr, mon, day = time.strptime(m.group('full'), SEACAT_SBE19PLUS_HEX_DATE_TXT_FORMAT)[:3]
                    else:
                        m = SEACAT_SBE19PLUS_HEX_DATE_MDYRE.search(header)
                        yr = int(m.group('year'))
                        mon = int(m.group('month'))
                        day = int(m.group('day'))
                    m = SEACAT_SBE19PLUS_HEX_TIMERE.search(header)
                    hour, minute = int(m.group('hour')), int(m.group('minute'))
                elif seacat_type == "SBE19":
                    try:  # For the SBE19s the start_time is not always cast time but can be the download time for some firmware revisions.
                        yr = int(SEACAT_SBE19_HEX_YEARRE.search(header).group('year'))
                        if yr < 80:
                            yr += 2000
                        if yr < 100:
                            yr += 1900
                        m1 = SEACAT_SBE19_HEX_MONTHDAYRE.search(header)
                        m2 = SEACAT_SBE19_HEX_TIMERE.search(header)
                    except:
                        m1 = m2 = None  # look for the start_time instead, the year must have failed.
                    if m1 and m2:
                        mon, day = int(m1.group('month')), int(m1.group('day'))
                        hour, minute = int(m2.group('hour')), int(m2.group('minute'))
                    else:
                        dt_match = SEACAT_CNV_START_TIMERE.search(header)
                        dt = datetime.datetime(1, 1, 1).strptime(dt_match.group('full'), '%b %d %Y %H:%M:%S')
                        yr, mon, day = dt.year, dt.month, dt.day
                        hour, minute = dt.hour, dt.minute
                elif seacat_type in ('SBE911', 'SBE49'):
                    # * System UpLoad Time = Sep 08 2008 14:18:19
                    m = SEACAT_SBE911_HEX_DATETIMERE.search(header)
                    dt = datetime.datetime(1, 1, 1).strptime(m.group('full'), '%b %d %Y %H:%M:%S')
                    yr, mon, day = dt.year, dt.month, dt.day
                    hour, minute = dt.hour, dt.minute
            except:  # bail out and look for the "start time" message that the Seabird Data processing program makes in the CNV file -- This is the download time from the SBE instrument
                dt_match = SEACAT_CNV_START_TIMERE.search(header)
                if dt_match:
                    dt = datetime.datetime(1, 1, 1).strptime(dt_match.group('full'), '%b %d %Y %H:%M:%S')
                    yr, mon, day = dt.year, dt.month, dt.day
                    hour, minute = dt.hour, dt.minute

            meta['timestamp'] = datetime.datetime(yr, mon, day, hour, minute)
            meta['Time'] = "%02d:%02d" % (hour, minute)
            meta['Year'] = '%4d' % yr
            meta['Day'] = '%03d' % meta['timestamp'].timetuple().tm_yday
            lat_m = SEACAT_HEX_LATRE.search(header)
            if lat_m:
                lon_m = SEACAT_HEX_LONRE.search(header)
                if lon_m:
                    coord = coordinates.Coordinate(lat_m.group('lat'), lon_m.group('lon'))
                    if coord:
                        meta.update(getMetaFromCoord(coord))  # blank Latitude/Longitude will return a None coord
            m = SeacatHex_SNRE.search(header)
            if m:
                meta['SerialNum'] = m.group('SN')
                meta['Instrument'] = seacat_type + ' (SN:' + m.group('SN') + ')'
            meta['samplerate'] = SeacatCNV_INTERVALRE.search(header).group('interval')
            meta['ImportFormat'] = 'CNV'
            meta['filename'] = self.fid._path
            self.rawmeta = meta

    def _parse_body(self):
        meta = self.rawmeta
        col_types = []
        col_names = []
        for col in meta['columns']:  # get a list of the columns in the CNV file
            col_name = col[2].lower().replace('sound', 'soundspeed')
            try:
                if col_name[0].isdigit():
                    col_name = "N_" + col_name
            except IndexError:
                col_name = col[1]
            col_names.append(col_name)
        for col in meta['columns']:  # check for and change any duplicates
            col_name = col[2].lower().replace('sound', 'soundspeed')
            try:
                if col_name[0].isdigit():
                    col_name = "N_" + col_name
            except IndexError:
                col_name = col[1]
            # see if there are duplicate names.  First try getting a second word from the column description and then add underscores if there is still duplication
            names_so_far = [coltype[0] for coltype in col_types]
            if col_name in names_so_far:
                col_name = col_name + "_" + re.search("\w+", col[3]).group().lower()  # col[3].lower().replace(",", "").replace(" ", "_").replace("[", "").replace("]", "")
            while col_name in names_so_far:
                col_name = col_name + "_"
            col_types.append((col_name, numpy.float32))

        d = parseNumbers(self.lines, col_types,
                         r"\s+", pre=r'^\s*', post=r'\s*$')
        p = Profile(d, ymetric="depth", attribute="soundspeed", metadata=meta)
        self.ssp.append_profile(p.ConvertToSoundSpeedProfile())
