import os
import json
import time
import shlex
import optparse
import subprocess
import multiprocessing


SOURCE_ROOT = os.path.join(os.path.abspath('.'), 'Library')
TUNNEL_CORE = os.path.join(SOURCE_ROOT, 'psiphon-tunnel-core')
CONFIG_FILE_NAME = os.path.join(SOURCE_ROOT, 'tunnel-core-config.config')
LOG_FILE_NAME = os.path.join(SOURCE_ROOT, 'tunnel-core-log.txt')

BIG_FILE_URL = "http://speedtest.wdc01.softlayer.com/downloads/test100.zip"
POOL_SIZE = 10

# Increse the Pool size until it stop
def _setup_config_file(encoded_server_entry, tunnel_protocol = "SSH"):
    config = {
        "TargetServerEntry": encoded_server_entry, # Single Test Server Parameter
        "TunnelProtocol": tunnel_protocol,
        "PropagationChannelId" : "0", # Propagation Channel ID = "Testing"
        "SponsorId" : "0",
        "LocalSocksProxyPort" : 1080,
        "TunnelPoolSize" : POOL_SIZE,
        "ConnectionWorkerPoolSize" : POOL_SIZE,
        "DisableRemoteServerListFetcher": True,
        "LogFilename": LOG_FILE_NAME,
    }

    with open(CONFIG_FILE_NAME, 'w+') as config_file:
        json.dump(config, config_file)

def _make_connection_to_server():

    if os.path.isfile(LOG_FILE_NAME):
        os.remove(LOG_FILE_NAME)

    cmd = '"%s" --config "%s"' % (TUNNEL_CORE, CONFIG_FILE_NAME)

    proc = subprocess.Popen(shlex.split(cmd))

    time.sleep(1)

    if os.path.isfile(LOG_FILE_NAME):
        print 'Tunnel Core is connecting...'
        not_connected = True
        while not_connected:
            time.sleep(1)
            with open(LOG_FILE_NAME, 'r') as log_file:
                for line in log_file:
                    line = json.loads(line)
                    if line['data'].get('count') != None:
                        if line['data']['count'] == POOL_SIZE and line['noticeType'] == 'Tunnels':
                            return proc
    else:
        print 'Tunnel Core Config file is missing'


def _big_file_curl(curl_cmd):

    proc = subprocess.Popen(shlex.split(curl_cmd))

    return proc

def test_tunnel_core_server(server_entry, protocol = "SSH"):
    # Setup config file
    _setup_config_file(server_entry, protocol)

    tunnel_start = time.time()
    # Make tunnel core connection to test server
    # AND
    # Wait for tunnel connection established
    conn = _make_connection_to_server()

    tunnel_established = time.time() - start_time
    print 'Fully established took %s seconds' % (round(tunnel_established, 2))

    # Do the file download
    # curl_cmd = 'curl --socks5 localhost:1080 -o /dev/null http://speedtest.wdc01.softlayer.com/downloads/test100.zip'
    curl_cmd = 'curl --silent --socks5 localhost:1080 -o /dev/null "%s"' % (BIG_FILE_URL)
    processes = []

    curl_start = time.time()
    print 'Starting the Crul processes...'
    while len(processes) < POOL_SIZE:
        processes.append(_big_file_curl(curl_cmd))

    print 'Downloading files...'
    while len(processes) > 0:
        for p in processes:
            p.wait()
            if p.returncode == 0:
                processes.remove(p)

    curl_finished = time.time() - start_time
    print 'Job finished, took %s seconds' % (round(curl_finished, 2))

    conn.kill()
    os.remove(CONFIG_FILE_NAME)

if __name__ == "__main__":
    parser = optparse.OptionParser('usage: %prog [options]')

    parser.add_option("-s", "--server-entry", dest="serverentry", action="store", type="string",
                      help="Please Enter the Encoded Server Entry.")
    parser.add_option("-p", "--protocol", dest="protocol", action="store",
                      choices=('SSH', 'UNFRONTED-MEEK-OSSH', 'OSSH'),
                      help="specify once for each of: UNFRONTED-MEEK-OSSH, OSSH, SSH")
    (options, _) = parser.parse_args()

    if not options.protocol:
        test_tunnel_core_server(options.serverentry)
    else:
        test_tunnel_core_server(options.serverentry, options.protocol)
