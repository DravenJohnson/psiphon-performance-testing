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

# To-do
1. Change `curl` to other library to support multiple platform
2. Add more protocol supports
3. Automatically increase the POOL_SIZE based on the test result
4. Maybe: intergrated into psinet?
