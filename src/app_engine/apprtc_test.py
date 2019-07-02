# Copyright 2014 Google Inc. All Rights Reserved.

import json
import time
import unittest

import webtest

import apprtc
import constants
from test_util import CapturingFunction
from test_util import ReplaceFunction

from google.appengine.api import memcache
from google.appengine.ext import testbed


class MockRequest(object):
  def get(self, key):
    return None


class AppRtcUnitTest(unittest.TestCase):

  def setUp(self):
    # First, create an instance of the Testbed class.
    self.testbed = testbed.Testbed()

    # Then activate the testbed, which prepares the service stubs for use.
    self.testbed.activate()

  def tearDown(self):
    self.testbed.deactivate()

class AppRtcPageHandlerTest(unittest.TestCase):

  def setUp(self):
    constants.UNDER_UNIT_TEST = True

    # First, create an instance of the Testbed class.
    self.testbed = testbed.Testbed()

    # Then activate the testbed, which prepares the service stubs for use.
    self.testbed.activate()

    # Next, declare which service stubs you want to use.
    self.testbed.init_memcache_stub()

    self.test_app = webtest.TestApp(apprtc.app)

    # Fake out event reporting.
    self.time_now = time.time()

  def tearDown(self):
    self.testbed.deactivate()

  def makeGetRequest(self, path):
    # PhantomJS uses WebKit, so Safari is closest to the thruth.
    return self.test_app.get(path, headers={'User-Agent': 'Safari'})

  def makePostRequest(self, path, body=''):
    return self.test_app.post(path, body, headers={'User-Agent': 'Safari'})

  def verifyConn(self, resp, offerer, answerer, seq):
    for conn in resp['params']['conns']:
      if conn['offerer'] == offerer and conn['answerer'] == answerer:
        self.assertEqual(conn['seq'], seq)
        return
    self.assertTrue(False)

  def testJoinAndLeave(self):
    # join
    r = self.makePostRequest('/call', 'uid=u2&rid=1234&call_type=join')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(0, len(resp['params']['conns']))
    
    r = self.makePostRequest('/call', 'uid=u1&rid=1234&call_type=join')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(1, len(resp['params']['conns']))
    self.verifyConn(resp, 'u1', 'u2', 1)

    r = self.makePostRequest('/call', 'uid=u3&rid=1234&call_type=join')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(3, len(resp['params']['conns']))
    self.verifyConn(resp, 'u1', 'u2', 1)
    self.verifyConn(resp, 'u3', 'u1', 2)
    self.verifyConn(resp, 'u3', 'u2', 3)

    # u2 has pc err
    r = self.makePostRequest('/call', 'uid=u1&rid=1234&call_type=refresh&pc_err=u2')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(3, len(resp['params']['conns']))
    self.verifyConn(resp, 'u1', 'u2', 4)
    self.verifyConn(resp, 'u3', 'u1', 2)
    self.verifyConn(resp, 'u3', 'u2', 3)

    r = self.makePostRequest('/call', 'uid=u2&rid=1234&call_type=refresh&pc_err=u1&pc_err=u3')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(3, len(resp['params']['conns']))
    self.verifyConn(resp, 'u1', 'u2', 4)
    self.verifyConn(resp, 'u3', 'u1', 2)
    self.verifyConn(resp, 'u3', 'u2', 5)

    r = self.makePostRequest('/call', 'uid=u3&rid=1234&call_type=refresh&pc_err=u2')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(3, len(resp['params']['conns']))
    self.verifyConn(resp, 'u1', 'u2', 4)
    self.verifyConn(resp, 'u3', 'u1', 2)
    self.verifyConn(resp, 'u3', 'u2', 5)

    # refresh
    r = self.makePostRequest('/call', 'uid=u1&rid=1234&call_type=refresh')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(3, len(resp['params']['conns']))
    self.verifyConn(resp, 'u1', 'u2', 4)
    self.verifyConn(resp, 'u3', 'u1', 2)
    self.verifyConn(resp, 'u3', 'u2', 5)

    r = self.makePostRequest('/call', 'uid=u2&rid=1234&call_type=refresh')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(3, len(resp['params']['conns']))
    self.verifyConn(resp, 'u1', 'u2', 4)
    self.verifyConn(resp, 'u3', 'u1', 2)
    self.verifyConn(resp, 'u3', 'u2', 5)

    r = self.makePostRequest('/call', 'uid=u3&rid=1234&call_type=refresh')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(3, len(resp['params']['conns']))
    self.verifyConn(resp, 'u1', 'u2', 4)
    self.verifyConn(resp, 'u3', 'u1', 2)
    self.verifyConn(resp, 'u3', 'u2', 5)

    # u3 leave
    r = self.makePostRequest('/call', 'uid=u3&rid=1234&call_type=leave')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])

    # refresh
    r = self.makePostRequest('/call', 'uid=u1&rid=1234&call_type=refresh')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(1, len(resp['params']['conns']))
    self.verifyConn(resp, 'u1', 'u2', 4)

    r = self.makePostRequest('/call', 'uid=u2&rid=1234&call_type=refresh')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(1, len(resp['params']['conns']))
    self.verifyConn(resp, 'u1', 'u2', 4)

    # u2 leave
    r = self.makePostRequest('/call', 'uid=u2&rid=1234&call_type=leave')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])

    # refresh
    r = self.makePostRequest('/call', 'uid=u1&rid=1234&call_type=refresh')
    print(r.body)
    resp = json.loads(r.body)
    self.assertEqual('SUCCESS', resp['result'])
    self.assertEqual(0, len(resp['params']['conns']))

if __name__ == '__main__':
  unittest.main()
