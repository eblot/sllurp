import argparse
import asyncio
import logging
import pprint
import time
# from twisted.internet import reactor, defer

import sllurp.llrp as llrp
from sllurp.llrp_proto import (Modulation_Name2Type, DEFAULT_MODULATION,
                               Modulation_DefaultTari)

startTime = None
endTime = None

numTags = 0
logger = logging.getLogger('sllurp')

args = None


shutdown_event = asyncio.Event()


def startTimeMeasurement():
    global startTime
    startTime = time.time()


def stopTimeMeasurement():
    global endTime
    endTime = time.time()


def finish(loop):
    global startTime
    global endTime
    global shutdown_event

    # stop runtime measurement to determine rates
    stopTimeMeasurement()
    runTime = (endTime - startTime) if (endTime > startTime) else 0

    logger.info('total # of tags seen: %d (%d tags/second)', numTags,
                numTags/runTime)
    shutdown_event.set()


def politeShutdown(factory):
    return factory.politeShutdown()


def tagReportCallback(llrpMsg):
    """Function to run each time the reader reports seeing tags."""
    global numTags
    tags = llrpMsg.msgdict['RO_ACCESS_REPORT']['TagReportData']
    if len(tags):
        logger.info('saw tag(s): %s', pprint.pformat(tags))
    else:
        logger.info('no tags seen')
        return
    for tag in tags:
        numTags += tag['TagSeenCount'][0]


def parse_args():
    global args
    parser = argparse.ArgumentParser(description='Simple RFID Inventory')
    parser.add_argument('host', help='hostname or IP address of RFID reader',
                        nargs='+')
    parser.add_argument('-p', '--port', default=llrp.LLRP_PORT, type=int,
                        help='port (default {})'.format(llrp.LLRP_PORT))
    parser.add_argument('-t', '--time', type=float, default='0.0',
                        help='seconds to inventory (default forever)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='show debugging output')
    parser.add_argument('-n', '--report-every-n-tags', default=1, type=int,
                        dest='every_n', metavar='N',
                        help='issue a TagReport every N tags')
    parser.add_argument('-a', '--antennas', default='1',
                        help='comma-separated list of antennas to use (0=all;'
                        ' default 1)')
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


def init_logging():
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


def main():
    parse_args()
    init_logging()

    # special case default Tari values
    if args.modulation in Modulation_DefaultTari:
        t_suggested = Modulation_DefaultTari[args.modulation]
        if args.tari:
            logger.warn('recommended Tari for %s is %d', args.modulation,
                        t_suggested)
        else:
            args.tari = t_suggested
            logger.info('selected recommended Tari of %d for %s', args.tari,
                        args.modulation)

    enabled_antennas = list(map(lambda x:
                                int(x.strip()), args.antennas.split(',')))

    loop = asyncio.get_event_loop()

    eng = llrp.LLRPClientEngine(onFinish=finish,
                                duration=args.time,
                                report_every_n_tags=args.every_n,
                                antennas=enabled_antennas,
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

    # tagReportCallback will be called every time the reader sends a TagReport
    # message (i.e., when it has "seen" tags).
    eng.addTagReportCallback(tagReportCallback)

    coroutines = []
    coroutines.append(shutdown_event.wait())

    for host in args.host:
        coroutines.append(eng.new_reader(host, args.port, timeout=3))

    # start runtime measurement to determine rates
    startTimeMeasurement()

    tasks = asyncio.gather(*coroutines)

    try:
        loop.run_until_complete(tasks)
    except KeyboardInterrupt as e:
        tasks.cancel()
        eng.politeShutdown()
        loop.run_forever()
        tasks.exception()
    finally:
        loop.close()


if __name__ == '__main__':
    main()
