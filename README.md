CircuitPython-Library supporting the iperf Protocol
===================================================

This is a port of Damian George's version downloaded from
<https://pypi.org/project/uiperf3/>.

See `examples/`-directory for a server and client program.

When running as server, start iperf3 on a PC/laptop with:

    iperf3 -l 4K -c 192.xxx.x.xxx     # PC is sender
    iperf3 -R -l 4K -c 192.xxx.x.xxx  # CP-device is sender

When running as a client, start iperf3 on a PC/laptop with:

    iperf3 -s

Be sure to update the IP/hostname of the server in `examples/client.py`.
