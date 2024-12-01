# -----------------------------------------------------------------------------
# CircuitPython iperf3-library.
#
# Original code from Damien P. George.
#
# Adapted to CircuitPython with minor modifications by Bernhard Bablok
#
# See examples/server.py and examples/client.py for usage.
#
# Website: https://github.com/bablokb/circuitpython-iperf
#
# -----------------------------------------------------------------------------

# configuration - don't change it here, use params.py instead

wait_for_console = True
debug            = False
hostname         = "192.168.4.1"  # hostname | ipaddress-string
udp              = False          # iperf -u|--udp: use UDP transfers
reverse          = False          # iperf -R|--reverse: host is sending
length           = 4096           # iperf -l|--length: length of buffer
try:
  from params import *
except:
  pass

import board
import supervisor
import wifi
import time
import iperf

# Get wifi details and more from a secrets.py file
try:
  from secrets import secrets
except ImportError:
  print("WiFi secrets are kept in secrets.py, please add them there!")
  raise

# --- connect to AP   --------------------------------------------------------

def connect():
  """ connect to AP with given ssid """

  print(f"connecting to AP {secrets['ssid']} ...")
  if 'timeout' in secrets:
    timeout = secrets['timeout']
  else:
    timeout = 5
  if 'retries' in secrets:
    retries = secrets['retries']
  else:
    retries = 3

  state = wifi.radio.connected
  print(f"  connected: {state}")
  if not state:
    for i in range(retries):
      try:
        wifi.radio.connect(secrets['ssid'],
                           secrets['password'],
                           timeout = timeout
                           )
        break
      except ConnectionError as ex:
        print(f"{ex}")
        if i == retries-1:
          raise
    print(f"  connected: {wifi.radio.connected}")

# --- main   ------------------------------------------------------------------

# wait for console to catch all messages
if wait_for_console:
  while not supervisor.runtime.serial_connected:
    time.sleep(0.1)
  print(f"running on board {board.board_id}")

connect()
while True:
  iperf.client(hostname,debug=debug,
               udp=udp,reverse=reverse,length=length)
  time.sleep(3)
