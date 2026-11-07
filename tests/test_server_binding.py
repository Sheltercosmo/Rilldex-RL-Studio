"""Loopback startup must not depend on reverse DNS or network availability."""
from http.server import BaseHTTPRequestHandler
import socket
import unittest
from unittest.mock import patch

from tracker.server import LocalServer


class ServerBindingTests(unittest.TestCase):
    def test_closed_capture_port_can_reopen_after_serving_a_connection(self):
        with LocalServer(('127.0.0.1', 0), BaseHTTPRequestHandler) as server:
            address = server.server_address
            with socket.create_connection(address) as client:
                peer, _ = server.get_request()
                # Server closes first, leaving its TCP endpoint in TIME_WAIT.
                peer.shutdown(socket.SHUT_WR)
                peer.close()
                self.assertEqual(client.recv(1), b'')
        with LocalServer(address, BaseHTTPRequestHandler) as reopened:
            self.assertEqual(reopened.server_address, address)

    def test_live_capture_port_cannot_be_shared(self):
        with LocalServer(('127.0.0.1', 0), BaseHTTPRequestHandler) as server:
            with self.assertRaises(OSError):
                LocalServer(server.server_address, BaseHTTPRequestHandler)

    def test_loopback_bind_does_not_resolve_hostname(self):
        with patch('socket.getfqdn',side_effect=AssertionError('Reverse DNS unavailable')):
            with LocalServer(('127.0.0.1',0),BaseHTTPRequestHandler) as server:
                self.assertEqual(server.server_name,'127.0.0.1')
                self.assertGreater(server.server_port,0)


if __name__=='__main__':unittest.main()
