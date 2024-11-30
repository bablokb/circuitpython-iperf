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

WAIT_FOR_CONSOLE = True
DEBUG            = False
OPT_HOST         = "192.168.4.1"  # hostname | ipaddress-string
OPT_UDP          = False          # iperf -u|--udp: use UDP transfers
OPT_REVERSE      = False          # iperf -R|--reverse: host is sending
OPT_LENGTH       = 4096           # iperf -l|--length: length of buffer

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
if WAIT_FOR_CONSOLE:
  while not supervisor.runtime.serial_connected:
    time.sleep(0.1)
  print(f"running on board {board.board_id}")

connect()
while True:
  iperf.client(OPT_HOST,debug=DEBUG,
               udp=OPT_UDP,reverse=OPT_REVERSE,length=OPT_LENGTH)
  time.sleep(3)
