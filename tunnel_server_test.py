#!/usr/bin/env python

import Queue
import binascii
import datetime
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

from sys import platform as _platform

SOURCE_ROOT = os.path.join(os.path.abspath("."), "Library")
SOCKS_PROXY_PORT = 1080

class TunnelCoreEOF(Exception): pass
class SocksPortInUse(Exception): pass
class ServerEntryRequired(Exception): pass

class ThreadProxiedUrl(threading.Thread):
  def __init__(self, queue, proxy_port):
    threading.Thread.__init__(self)
    self.queue = queue
    urllib2.install_opener(urllib2.build_opener(urllib2.ProxyHandler({'socks': '127.0.0.1:%d' % (proxy_port)})))

  def run(self):
    while True:
      try:
        download_url = self.queue.get()
        urllib2.urlopen(download_url).read()

        self.queue.task_done()
      except Exception as e:
        print("Threaded urllib urlopen request threw an exception")
        raise e

# Check OS for different tunnel-core client
if _platform == "linux" or _platform == "linux2":
  TUNNEL_CORE = os.path.join(SOURCE_ROOT, "linux", "psiphon-tunnel-core-x86_64")
elif _platform == "darwin":
  TUNNEL_CORE = os.path.join(SOURCE_ROOT, "darwin", "psiphon-tunnel-core-x86_64")

def _set_max_fds():
  low_limit, high_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
  if os.geteuid() == 0:
    print("[%s] Script was run with root privileges, raising FD limit" % (datetime.datetime.now().isoformat()))
    try:
      resource.setrlimit(resource.RLIMIT_NOFILE, (65535*4, 65535*4))
    except ValueError as e:
      print("[%s] Cannot raise the file descriptor limit for a subprocess this high: %d" % (datetime.datetime.now().isoformat(), 65536*4))
      raise e
  else:
    print("[%s] Script was run without root privileges, not modifying FD limits" % (datetime.datetime.now().isoformat()))

def _setup_config(encoded_server_entry = None, tunnel_protocol = "SSH", api_disabled = False, tunnels = 1, verbose = False):
  config = {
    "ClientPlatform": "performance_testing",
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

  return json.dumps(config)

def _block_and_establish_tunnels(config = None, tunnels = 1, verbose = False):
  if not config:
    print("Tunnel Core Config file is missing")
    return

  global TUNNEL_CORE_PROCESS
  TUNNEL_CORE_PROCESS = subprocess.Popen([TUNNEL_CORE, "--config", "%s" % (config)], stderr=subprocess.PIPE, close_fds=True, preexec_fn=_set_max_fds)

  # Breaking this loop means 'tunnels' number of tunnels were established
  verbose_warning = False
  while True:
    line = TUNNEL_CORE_PROCESS.stderr.readline()
    if not line:
      raise TunnelCoreEOF("EOF received from tunnel-core subprocess")

    if verbose:
      if not verbose_warning:
        print("")
        print("Verbose flag was enabled. Printing tunnel-core output")
        verbose_warning = True
      sys.stdout.write("  %s" % line)

    line = json.loads(line)
    if line["noticeType"] == "SocksProxyPortInUse":
      raise SocksPortInUse("Defined SOCKS proxy port (%d) is already in use, cannot continue" % SOCKS_PROXY_PORT)

    if line["data"].get("count") != None:
      if line["noticeType"] == "Tunnels" and line["data"]["count"] == tunnels:
        break

def _download_via_curl(socks_proxy_port, download_url, parallel_downloads):
  processes = []

  curl_start = time.time()
  while len(processes) <= parallel_downloads:
    processes.append(subprocess.Popen(shlex.split('curl --silent --socks5 localhost:%d -o /dev/null "%s"' % (socks_proxy_port, download_url))))

  while len(processes) > 0:
    for p in processes:
      p.wait()
      if p.returncode == 0:
        processes.remove(p)

  return time.time() - curl_start

def _download_via_urllib(socks_proxy_port, download_url, parallel_downloads):
  queue = Queue.Queue()
  urllib_start = time.time()

  #spawn a pool of threads, and pass them queue instance
  for i in range(parallel_downloads):
    t = ThreadProxiedUrl(queue, socks_proxy_port)
    t.daemon = True
    t.setDaemon(True)
    t.start()

  for host in [download_url] * parallel_downloads:
    queue.put(host)

  queue.join()

  return time.time() - urllib_start

def test_tunnel_core_server(server_entry, protocol = "SSH", download_file_size = 10, api_disabled = False, tunnels = 1, curl_download = False, verbose = False, no_download = False):
  print("[%s] Performance test started" % (datetime.datetime.now().isoformat()))
  tmp = tempfile.NamedTemporaryFile(delete=True)
  try:
    print("[%s] Generating tunnel-core configuration file" % (datetime.datetime.now().isoformat()))
    tmp.write(_setup_config(server_entry, protocol, api_disabled, tunnels, verbose))
    tmp.flush()

    tunnel_start = time.time()
    try:
      print("[%s] Attempting to establish %d tunnels" % (datetime.datetime.now().isoformat(), tunnels))
      _block_and_establish_tunnels(tmp.name, tunnels, verbose)
      time_to_all_tunnels = round(time.time() - tunnel_start, 2)
      print("[%s] All (%d) tunnels established in %.2f seconds" % (datetime.datetime.now().isoformat(), tunnels, time_to_all_tunnels))
    except Exception as e:
      raise e
  finally:
    tmp.close()  # deletes the file

  # Download the dummy file in parallel tunnels + 1. 1 is added as a safety factor
  # to increase the likliehood that each tunnel is used in parallel simultaneously
  if not no_download:
    print(
      "[%s] Beginning speed test via '%s', downloading %d %dMB files" % (
        datetime.datetime.now().isoformat(),
        ("curl" if curl_download else "urllib"),
        (tunnels + 1),
        download_file_size
      )
    )
    if curl_download:
      download_duration = _download_via_curl(SOCKS_PROXY_PORT, "http://speedtest.wdc01.softlayer.com/downloads/test%d.zip" % download_file_size, tunnels + 1)
    else:
      download_duration = _download_via_urllib(SOCKS_PROXY_PORT, "http://speedtest.wdc01.softlayer.com/downloads/test%d.zip" % download_file_size, tunnels + 1)

    average_download_time = round((float(download_duration)/tunnels + 1), 2)
    average_download_speed = round((float(download_file_size * 8)/average_download_time), 2)
    print(
      "[%s] %d downloads finished in %.2f seconds. Averaged %.2fs/file @ %.2fmbps" % (
        datetime.datetime.now().isoformat(),
        (tunnels + 1),
        round(download_duration, 2),
        average_download_time,
        average_download_speed
      )
    )

  return {
    "timestamp": datetime.datetime.utcnow().isoformat(),
    "server_ip": binascii.unhexlify(server_entry).split()[0],
    "api_disabled": api_disabled,
    "protocol": protocol,
    "tunnels": tunnels,
    "time_to_all_tunnels_s": time_to_all_tunnels,
    "avg_time_to_tunnel": round((float(time_to_all_tunnels) / tunnels), 2),
    "download_file_size_mb": download_file_size,
    "avg_download_time_s": average_download_time,
    "avg_download_rate_mbps": average_download_speed
  }

if __name__ == "__main__":
  try:
    parser = optparse.OptionParser("usage: %prog [options]")

    parser.add_option("-a", "--api-disabled", dest="api_disabled", default=False, action="store_true", help="Disable client requests to the web API")
    parser.add_option("-c", "--curl-download", dest="curl_download", default=False, action="store_true", help="Download using a shell out to curl (uses urllib2 if not)")
    parser.add_option("-d", "--download-size", dest="download_size", default="10", action="store", type="choice", choices=("10", "100"), help="Choose the size of the dummy file to download as a speed test")
    parser.add_option("-n", "--no-download", dest="no_download", default=False, action="store_true", help="Do not attempt to download a file through the proxy")
    parser.add_option("-o", "--output", dest="output", action="store", type="string", help="Name of the file to store the output in")
    parser.add_option("-p", "--protocol", dest="protocol", default="SSH", action="store", type="choice", choices=("SSH", "UNFRONTED-MEEK-OSSH", "OSSH"), help="specify once for each of: UNFRONTED-MEEK-OSSH, OSSH, SSH")
    parser.add_option("-s", "--server-entry", dest="server_entry", action="store", type="string", help="Please Enter the Encoded Server Entry.")
    parser.add_option("-t", "--tunnels", dest="tunnels", default=10, action="store", type="int", help="The number of tunnels to create simultaneously")
    parser.add_option("-v", "--verbose", dest="verbose", default=False, action="store_true", help="Print all tunnel-core output to stdout")
    (options, _) = parser.parse_args()

    if not options.server_entry:
      raise ServerEntryRequired("An encoded server entry is required to run this test")

    if not options.output:
      options.output = "tunnel-core-performance-test-results.json"

    print("[%s] Test results will be written to '%s'" % (datetime.datetime.now().isoformat(), options.output))

    with open(options.output, "a") as output:
      json.dump(test_tunnel_core_server(
        server_entry = options.server_entry,
        protocol = options.protocol,
        download_file_size = int(options.download_size),
        api_disabled = options.api_disabled,
        tunnels = options.tunnels,
        curl_download = options.curl_download,
        verbose = options.verbose,
        no_download = options.no_download
      ), output, sort_keys=True)

      output.write("\n")

    print("[%s] Performance test ended" % (datetime.datetime.now().isoformat()))

  except (KeyboardInterrupt, SystemExit):
    print("")
    print("Recieved ^C or system signal, exiting.")

    try:
      TUNNEL_CORE_PROCESS.kill()
    except NameError:
      pass

    sys.exit(1)
  except ServerEntryRequired as e:
    print(e.message)
  finally:
    try:
      TUNNEL_CORE_PROCESS.kill()
    except NameError:
      pass
