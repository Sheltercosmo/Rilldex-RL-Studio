"""Loopback startup must not depend on reverse DNS or network availability."""
from http.server import BaseHTTPRequestHandler
import unittest
from unittest.mock import patch

from tracker.server import LocalServer


class ServerBindingTests(unittest.TestCase):
    def test_loopback_bind_does_not_resolve_hostname(self):
        with patch('socket.getfqdn',side_effect=AssertionError('Reverse DNS unavailable')):
            with LocalServer(('127.0.0.1',0),BaseHTTPRequestHandler) as server:
                self.assertEqual(server.server_name,'127.0.0.1')
                self.assertGreater(server.server_port,0)


if __name__=='__main__':unittest.main()
