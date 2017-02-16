#!/usr/bin/env python3

import logging
from argparse import ArgumentParser
from asyncio import Event, get_event_loop, gather
from time import time as now
from sllurp.llrp import LLRPEngine
from sllurp.llrp_proto import (Modulation_Name2Type, DEFAULT_MODULATION,
                               Modulation_DefaultTari)

startTime = None
endTime = None

numTags = 0
logger = logging.getLogger('sllurp')

args = None


class LLRPClient(object):
    """
    """

    def __init__(self):
        self._shutdown_event = Event()
        self._hosts = []
        self._port = LLRPEngine.PORT
        self._tags = {}
        self._start_time = 0.0
        self._tag_count = 0

    def finalize(self, loop):
        # stop runtime measurement to determine rates
        run_time = (now() - self._start_time)
        logger.info('%d tags seen (%.1f tags/second), distinct: %d',
                    self._tag_count, self._tag_count/run_time,
                    len(self._tags))
        for epc in sorted(self._tags):
            tag = self._tags[epc]
            print('%24s: %d dBm' % (epc, tag['PeakRSSI'][0]))
        self._shutdown_event.set()

    def _report_tag_cb(self, llrpmsg):
        """Function to run each time the reader reports seeing tags."""
        tags = llrpmsg.msgdict['RO_ACCESS_REPORT']['TagReportData']
        if len(tags):
            # logger.info('saw tag(s): %s', pprint.pformat(tags))
            for tag in tags:
                self._tag_count += tag['TagSeenCount'][0]
                try:
                    epc = tag['EPC-96']
                    self._tags[epc] = tag
                except KeyError:
                    pass

    def initialize(self, args):
        self._hosts = args.host
        self._port = args.port
        self._engine = LLRPEngine(onFinish=self.finalize,
                                  duration=args.time,
                                  report_every_n_tags=args.every_n,
                                  antennas=args.antennas,
                                  tx_power=args.tx_power,
                                  modulation=args.modulation,
                                  tari=args.tari,
                                  session=args.session,
                                  tag_population=args.population,
                                  start_inventory=True,
                                  disconnect_when_done=(args.time > 0),
                                  reconnect=args.reconnect,
                                  tag_content_selector={
                                      'EnableROSpecID': False,
                                      'EnableSpecIndex': False,
                                      'EnableInventoryParameterSpecID': False,
                                      'EnableAntennaID': True,
                                      'EnableChannelIndex': False,
                                      'EnablePeakRRSI': True,
                                      'EnableFirstSeenTimestamp': False,
                                      'EnableLastSeenTimestamp': True,
                                      'EnableTagSeenCount': True,
                                      'EnableAccessSpecID': False
                                  })
        self._engine.addTagReportCallback(self._report_tag_cb)

    def run(self):
        loop = get_event_loop()
        coroutines = [self._shutdown_event.wait()]
        for host in self._hosts:
            coroutines.append(self._engine.new_reader(host, self._port,
                                                      timeout=3))
        tasks = gather(*coroutines)
        try:
            self._start_time = now()
            loop.run_until_complete(tasks)
        except KeyboardInterrupt as e:
            tasks.cancel()
            self._engine.politeShutdown()
            loop.run_forever()
            tasks.exception()
        finally:
            loop.close()


def main():
    debug = False
    try:
        parser = ArgumentParser(description='Simple RFID Inventory')
        parser.add_argument('host', help='RFID reader hostname',
                            nargs='+')
        parser.add_argument('-p', '--port', default=LLRPEngine.PORT, type=int,
                            help='port (default {})'.format(LLRPEngine.PORT))
        parser.add_argument('-t', '--time', type=float, default='0.0',
                            help='seconds to inventory (default forever)')
        parser.add_argument('-d', '--debug', action='store_true',
                            help='show debugging output')
        parser.add_argument('-n', '--report-every-n-tags', default=1, type=int,
                            dest='every_n', metavar='N',
                            help='issue a TagReport every N tags')
        parser.add_argument('-a', '--antennas', default=[1],
                            type=int, action='append',
                            help='antenna to use, may be repeated')
        parser.add_argument('-X', '--tx-power', default=0, type=int,
                            dest='tx_power',
                            help='transmit power (default 0=max power)')
        mods = sorted(Modulation_Name2Type.keys())
        parser.add_argument('-M', '--modulation', default=DEFAULT_MODULATION,
                            choices=mods,
                            help='modulation (default={})'.format(
                                DEFAULT_MODULATION))
        parser.add_argument('-T', '--tari', default=0, type=int,
                            help='Tari value (default 0=auto)')
        parser.add_argument('-s', '--session', default=2, type=int,
                            help='Gen2 session (default 2)')
        parser.add_argument('-P', '--tag-population', default=4, type=int,
                            dest='population',
                            help="Tag Population value (default 4)")
        parser.add_argument('-l', '--logfile')
        parser.add_argument('-r', '--reconnect', action='store_true',
                            default=False,
                            help='reconnect on connection failure or loss')
        args = parser.parse_args()

        logLevel = (args.debug and logging.DEBUG or logging.INFO)
        logFormat = '%(levelname)s: %(message)s'
        formatter = logging.Formatter(logFormat)
        stderr = logging.StreamHandler()
        stderr.setFormatter(formatter)

        root = logging.getLogger()
        root.setLevel(logLevel)
        root.handlers = [stderr]

        if args.logfile:
            fHandler = logging.FileHandler(args.logfile)
            fHandler.setFormatter(formatter)
            root.addHandler(fHandler)

        logger.log(logLevel, 'log level: %s', logging.getLevelName(logLevel))

        # special case default Tari values
        if args.modulation in Modulation_DefaultTari:
            t_suggested = Modulation_DefaultTari[args.modulation]
            if args.tari:
                logger.warn('recommended Tari for %s is %d', args.modulation,
                            t_suggested)
            else:
                args.tari = t_suggested
                logger.info('selected recommended Tari of %d for %s',
                            args.tari, args.modulation)

        client = LLRPClient()
        client.initialize(args)
        client.run()

    except Exception as e:
        print('\nError: %s' % e, file=stderr)
        if debug:
            import traceback
            print(traceback.format_exc(chain=False), file=stderr)
        exit(1)


if __name__ == '__main__':
    main()
