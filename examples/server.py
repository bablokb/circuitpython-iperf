# -----------------------------------------------------------------------------
# CircuitPython iperf3-library.
#
# Original code from Damien P. George.
#
# Adapted to CircuitPython with minor modifications by Bernhard Bablok
#
# Example for an iperf-server. Copy to main.py on your device
#
# Website: https://github.com/bablokb/circuitpython-iperf
#
# -----------------------------------------------------------------------------

WAIT_FOR_CONSOLE = True
RUN_AP           = False
DEBUG            = False

import board
import supervisor
import wifi
import gc
import iperf

# Get wifi details and more from a secrets.py file
try:
  from secrets import secrets
except ImportError:
  print("WiFi secrets are kept in secrets.py, please add them there!")
  raise

# --- run AP   -------------------------------------------------------------

def start_ap():
  """ start AP-mode """

  print("stopping station")
  wifi.radio.stop_station()
  print(f"starting AP with ssid {secrets['ap_ssid']}")
  wifi.radio.start_ap(ssid=secrets["ap_ssid"],
                      password=secrets["ap_password"],
                      authmode=[wifi.AuthMode.PSK,wifi.AuthMode.WPA2])

# --- connect to AP   --------------------------------------------------------

def connect():
  """ connect to AP with given ssid """

  print("starting station")
  wifi.radio.start_station()
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
        print(f"  {ex}")
        if i == retries-1:
          raise
    print(f"  connected: {wifi.radio.connected}")

# --- main   ------------------------------------------------------------------

# wait for console to catch all messages
if WAIT_FOR_CONSOLE:
  while not supervisor.runtime.serial_connected:
    time.sleep(0.1)
  print(f"running on board {board.board_id}")

if RUN_AP:
  start_ap()
  print(f"starting server on {wifi.radio.ipv4_address_ap}")
else:
  connect()
  print(f"starting server on {wifi.radio.ipv4_address}")

while True:
  gc.collect()
  try:
    iperf.server(debug=DEBUG)
  except BrokenPipeError:
    pass
