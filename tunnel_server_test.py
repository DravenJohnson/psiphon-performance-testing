#!/usr/bin/env python

import json
import optparse
import os
import resource
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import urllib2
import Queue

from sys import platform as _platform

SOURCE_ROOT = os.path.join(os.path.abspath("."), "Library")
SOCKS_PROXY_PORT = 1080

# Check OS for different tunnel-core client
if _platform == "linux" or _platform == "linux2":
    TUNNEL_CORE = os.path.join(SOURCE_ROOT, "linux", "psiphon-tunnel-core-x86_64")
elif _platform == "darwin":
    TUNNEL_CORE = os.path.join(SOURCE_ROOT, "darwin", "psiphon-tunnel-core-x86_64")

def _set_max_fds():
    low_limit, high_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    if os.geteuid() == 0:
        print("Script was run with root privileges, raising FD limit")
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (65535*4, 65535*4))
        except ValueError as e:
            print("Cannot raise the file descriptor limit for a subprocess this high: %d" % (65536*4))
            raise e
            sys.exit(1)
    else:
        print("Script was run without root privileges, not modifying FD limits")

# Increse the Pool size until it stop
def _setup_config(encoded_server_entry = None, tunnel_protocol = "SSH", api_disabled = False, tunnels = 1, verbose = False):
    config = {
        "ClientVersion": "0",
        "ConnectionWorkerPoolSize" : tunnels / 10,
        "DisableApi": api_disabled,
        "DisableRemoteServerListFetcher": True,
        "EmitDiagnosticNotices": verbose,
        "LocalSocksProxyPort" : SOCKS_PROXY_PORT,
        "PropagationChannelId" : "0", # Propagation Channel ID = "Testing",
        "SponsorId" : "0",
        "TargetServerEntry": encoded_server_entry,
        "TunnelPoolSize" : tunnels,
        "TunnelProtocol": tunnel_protocol
    }

    print(json.dumps(config))
    return json.dumps(config)

def _block_and_establish_tunnels(config = None, tunnels = 1, verbose = False):
    if not config:
        print("Tunnel Core Config file is missing")
        return

    print("Waiting for all tunnels to be established...")
    global TUNNEL_CORE_PROCESS
    TUNNEL_CORE_PROCESS = subprocess.Popen([TUNNEL_CORE, "--config", "%s" % (config)], stderr=subprocess.PIPE, close_fds=True, preexec_fn=_set_max_fds)

    # Breaking this loop means 'tunnels' number of tunnels were established
    verbose_warning = False
    while True:
        line = TUNNEL_CORE_PROCESS.stderr.readline()
        if not line:
            raise Exception("EOF received from tunnel-core subprocess")

        if verbose:
            if not verbose_warning:
                print("")
                print("Verbose flag was enabled. Printing tunnel-core output")
                verbose_warning = True
            sys.stdout.write("  %s" % line)

        line = json.loads(line)

        if line["noticeType"] == "SocksProxyPortInUse":
            raise Exception("Defined SOCKS proxy port (%d) is already in use, cannot continue" % SOCKS_PROXY_PORT)

        if line["data"].get("count") != None:
            if line["noticeType"] == "Tunnels" and line["data"]["count"] == tunnels:
                break

def _big_file_curl(curl_cmd):
    return subprocess.Popen(shlex.split(curl_cmd))

def _download_via_curl(socks_proxy_port, download_url, parallel_downloads):
    curl_cmd = 'curl --silent --socks5 localhost:%d -o /dev/null "%s"' % (socks_proxy_port, download_url)
    processes = []

    curl_start = time.time()
    print("Starting the download...")
    while len(processes) <= parallel_downloads:
        processes.append(_big_file_curl(curl_cmd))

    print("Downloading files...")
    while len(processes) > 0:
        for p in processes:
            p.wait()
            if p.returncode == 0:
                processes.remove(p)

    print("Downloads finished in %.2f seconds" % (round(time.time() - curl_start, 2)))


class ThreadProxiedUrl(threading.Thread):
    def __init__(self, queue, proxy_port):
	threading.Thread.__init__(self)
	self.queue = queue
	self.proxy_port = proxy_port

    def run(self):
	proxy = urllib2.ProxyHandler({'socks': '127.0.0.1:%d' % (self.proxy_port)})
	opener = urllib2.build_opener(proxy)
	urllib2.install_opener(opener)

	while True:
            try:
                #grabs host from queue
                host = self.queue.get()

                urllib2.urlopen(host).read()

                #signals to queue job is done
                self.queue.task_done()
            except Exception as e:
                print("Threaded urllib urlopen request threw an exception")
                raise e

def _download_via_urllib(socks_proxy_port, download_url, parallel_downloads):
    queue = Queue.Queue()
    urllib_start = time.time()

    #spawn a pool of threads, and pass them queue instance
    for i in range(parallel_downloads):
	t = ThreadProxiedUrl(queue, socks_proxy_port)
	t.setDaemon(True)
	t.start()

    #populate queue with data
    for host in [download_url] * parallel_downloads:
	queue.put(host)

    #wait on the queue until everything has been processed
    queue.join()

    print("Downloads finished in %.2f seconds" % (round(time.time() - urllib_start, 2)))

def test_tunnel_core_server(server_entry, protocol = "SSH", download_file_size = 1, api_disabled = False, tunnels = 1, curl_download = False, verbose = False, no_download = False):
    tmp = tempfile.NamedTemporaryFile(delete=True)
    try:
        tmp.write(_setup_config(server_entry, protocol, api_disabled, tunnels, verbose))
        tmp.flush()

        tunnel_start = time.time()
        try:
            _block_and_establish_tunnels(tmp.name, tunnels, verbose)
            print("All tunnels (%d) established in %.2f seconds" % (tunnels, round(time.time() - tunnel_start, 2)))
        except Exception as e:
            raise e
    finally:
        tmp.close()  # deletes the file

    # Download the dummy file in parallel tunnels + 1. 1 is added as a safety factor
    # to increase the likliehood that each tunnel is used in parallel simultaneously
    if not no_download:
        if curl_download:
            _download_via_curl(SOCKS_PROXY_PORT, "http://speedtest.wdc01.softlayer.com/downloads/test%d.zip" % download_file_size, tunnels + 1)
        else:
            _download_via_urllib(SOCKS_PROXY_PORT, "http://speedtest.wdc01.softlayer.com/downloads/test%d.zip" % download_file_size, tunnels + 1)

if __name__ == "__main__":
    try:
        parser = optparse.OptionParser("usage: %prog [options]")

        parser.add_option("-a", "--api-disabled", dest="api_disabled", default=False, action="store_true",
                        help="Disable client requests to the web API")
        parser.add_option("-c", "--curl-download", dest="curl_download", default=False, action="store_true",
                        help="Download using a shell out to curl (uses urllib if not)")
        parser.add_option("-d", "--download-size", dest="download_size", default="10", action="store", type="choice",
                        choices=("10", "100"),
                        help="Choose the size of the dummy file to download as a speed test")
        parser.add_option("-n", "--no-download", dest="no_download", default=False, action="store_true",
                        help="Do not attempt to download a file through the proxy")
        parser.add_option("-p", "--protocol", dest="protocol", default="SSH", action="store", type="choice",
                        choices=("SSH", "UNFRONTED-MEEK-OSSH", "OSSH"),
                        help="specify once for each of: UNFRONTED-MEEK-OSSH, OSSH, SSH")
        parser.add_option("-s", "--server-entry", dest="server_entry", action="store", type="string",
                        help="Please Enter the Encoded Server Entry.")
        parser.add_option("-t", "--tunnels", dest="tunnels", default=10, action="store", type="int",
                        help="The number of tunnels to create simultaneously")
        parser.add_option("-v", "--verbose", dest="verbose", default=False, action="store_true",
                        help="Print all tunnel-core output to stdout")
        (options, _) = parser.parse_args()


        if not options.server_entry:
            raise Exception("An encoded server entry is required to run this test")

        test_tunnel_core_server(
            server_entry = options.server_entry,
            protocol = options.protocol,
            download_file_size = int(options.download_size),
            api_disabled = options.api_disabled,
            tunnels = options.tunnels,
            curl_download = options.curl_download,
            verbose = options.verbose,
            no_download = options.no_download
        )
    except (KeyboardInterrupt, SystemExit):
        print("")
        print("Recieved ^C or system signal, exiting.")

        TUNNEL_CORE_PROCESS.kill()

        sys.exit(1)
    except Exception as e:
        TUNNEL_CORE_PROCESS.kill()
        raise e
    finally:
        TUNNEL_CORE_PROCESS.kill()
