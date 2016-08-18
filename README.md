# psiphon-performance-testing

This is a testing script for the new psiphon tunnel core server.

# Intro

1. This script generates a tunnel core config file and uses it to start tunnel core client.
2. Once tunnel core client starts, the script runs a `curl` in multiple subprocesses to parallaly download a large file.
3. It reports how long it spends to download the files.

# Client Binary
This client on the repo is **only** for testing purposes and **ONLY** support `OS X 64 bit` and `Linux 64bit`. Please **DO NOT** use this in production.

# How to
1. Edit `L16: POOL_SIZE` in `tunnel_server_test.py` to change it to the pool number you choose.
2. Get the server entry from psinet.
3. run:
  ```bash
  python tunnel_server_test.py -s 'ServerEntry'
  ```
   - Run on default `SSH` protocol

  ***OR***

  ```bash
  python tunnel_server_test.py -s 'ServerEntry' -p 'Protocol'
  ```
   - To run with other test protocols
   - Supported protocols: OSSH, SSH, UNFRONTED-MEEK-OSSH

   ***OR/AND***

   **Available flag:**
   ```python
    python tunnel_server_test.py \
      -a                # (Optional) Disabled API, use this flag to enabled 'Disabled API'. Default FLASE
      -c                # (Optional) Use curl download instead of urllib2 download. Default FALSE
      -d 100            # (Optional) Change download file size to 100. Default 10MB
      -n                # (Optional) Do not attempt to download a file through the proxy. Default FALSE
      -p 'Protocol'     # (Optional) Use different protocol to connection, can use UNFRONTED-MEEK-OSSH, SSH, or OSSH. Default SSH
      -s 'ServerEntry'  # (Required) Encoded Server Entry
      -t 100            # (Optional) The number of tunnels. Default 10
      -v                # (Optional) Turn one verbose mode, print all tunnel-core output. Default FALSE

   ```


# To-do
1. ~~Change `curl` to other library to support multiple platform~~ - urllib2 supported
2. Add more protocol supports
3. Automatically increase the POOL_SIZE based on the test result
4. Maybe: intergrated into psinet?

# Notes and Issues

* If no protocol `-p` is specified, then SSH is attempted.  If SSH is not an
enabled capability on the server then a cryptic error is emitted:
  ```
Traceback (most recent call last):
  File "./tunnel_server_test.py", line 236, in <module>
    no_download = options.no_download
  File "./tunnel_server_test.py", line 158, in test_tunnel_core_server
    raise e
__main__.TunnelCoreEOF: EOF received from tunnel-core subprocess
  ```

* Use `-v` to see what tunnel-core log lines.

* Disable API requests (`-a`) if receiving the message:
  ```
  {"data":{"directTCPDialAddress":"45.33.37.171:593","ipAddress":"45.33.37.171","protocol":"OSSH","region":"US"},"noticeType":"ConnectingServer","showUser":false,"timestamp":"2016-08-08T16:22:37Z"}
  {"data":{"message":"starting server context for 45.33.37.171"},"noticeType":"Info","showUser":false,"timestamp":"2016-08-08T16:22:38Z"}
  {"data":{"message":"failed to connect to 45.33.37.171: psiphon.EstablishTunnel#149: error starting server context for 45.33.37.171: psiphon.NewServerContext#104: psiphon.(*ServerContext).doHandshakeRequest#127: psiphon.(*ServerContext).doGetRequest#567: Get 
http://45.33.37.171:8257/handshake?client_sess...45.33.37.171:8257: getsockopt: connection refused)"},"noticeType":"Info","showUser":false,"timestamp":"2016-08-08T16:22:38Z"}
  ```
