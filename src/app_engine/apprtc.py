#!/usr/bin/python2.4
#
# Copyright 2011 Google Inc. All Rights Reserved.

"""WebRTC Demo

This module demonstrates the WebRTC API by implementing a simple video chat app.
"""

import cgi
import json
import logging
import os
import threading
import time
import hashlib
import hmac
import base64

import jinja2
import webapp2
from google.appengine.api import app_identity
from google.appengine.api import memcache
from google.appengine.api import urlfetch

import constants

jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))


def get_wss_parameters(request):
  wss_host_port_pair = request.get('wshpp')
  wss_tls = request.get('wstls')

  if not wss_host_port_pair:
    wss_host_port_pair = constants.WSS_HOST_PORT_PAIRS[0]

  if wss_tls and wss_tls == 'false':
    wss_url = 'ws://' + wss_host_port_pair + '/ws'
    wss_post_url = 'http://' + wss_host_port_pair
  else:
    wss_url = 'wss://' + wss_host_port_pair + '/ws'
    wss_post_url = 'https://' + wss_host_port_pair
  return (wss_url, wss_post_url)

def get_ice_servers():
  timestamp = int(time.time()) + 600
  username = str(timestamp) + ':ninefingers'

  ice_key = str.encode('4080218913', 'UTF-8')
  message = str.encode(username, 'UTF-8')
  digester = hmac.new(ice_key, message, hashlib.sha1)
  
  credential = base64.b64encode(digester.digest()).decode("UTF-8")

  return [
    {
      'urls': [
        'stun:' + constants.ICE_SERVER_IP + ':3478',
        'turn:' + constants.ICE_SERVER_IP + ':3478'
      ],
      'username': username,
      'credential': credential
    }
  ]

def next_seq(memcache_client):
  return memcache_client.incr('conn_seq', initial_value=0)

def get_conn_key(offerer, answerer):
  return offerer + '<====>' + answerer

def get_memcache_key_for_room(rid):
  return 'rooms/%s' % rid

class Room:
  def __init__(self):
    self.users = []
    self.conns = {}
  def add_user(self, uid):
    self.users.append(uid)
  def remove_user(self, uid):
    removed_conns = []
    n = len(self.users)
    i = n - 1
    while i >= 0:
      offerer = self.users[i]
      j = i - 1
      while j >= 0:
        answerer = self.users[j]
        if offerer == uid or answerer == uid:
          removed_conns.append(get_conn_key(offerer, answerer))
        j = j - 1
      i = i - 1
    self.users.remove(uid)
    for conn in removed_conns:
      self.conns.pop(conn, None)
  def get_occupancy(self):
    return len(self.users)
  def has_user(self, uid):
    return uid in self.users
  def refresh_conns(self, invoker, pc_err, memcache_client):
    res = []
    updated = False

    n = len(self.users)
    i = n - 1
    while i >= 0:
      offerer = self.users[i]
      j = i - 1
      while j >= 0:
        answerer = self.users[j]
        conn_key = get_conn_key(offerer, answerer)
        conn = self.conns.get(conn_key)
        if conn is None:
          updated = True
          conn = {
            'offerer': offerer,
            'answerer': answerer,
            'seq': next_seq(memcache_client),
            'pc_err_updated_seq': False,
          }
          self.conns[conn_key] = conn
        elif (offerer == invoker or answerer == invoker) and \
          (answerer if offerer == invoker else offerer) in pc_err:

          if not conn['pc_err_updated_seq']:
            conn['seq'] = next_seq(memcache_client)
            conn['pc_err_updated_seq'] = True
            updated = True
            self.conns[conn_key] = conn
          else:
            conn['pc_err_updated_seq'] = False

        res.append({
          'offerer': offerer,
          'answerer': answerer,
          'seq': conn['seq'],
        })

        j = j - 1
      i = i - 1

    return res, updated
  def __str__(self):
    return str(self.users)

def add_user_to_room(rid, uid, pc_err):
  key = get_memcache_key_for_room(rid)
  memcache_client = memcache.Client()
  error = None
  retries = 0
  room = None

  seq_updated = False
  conns = []

  # Compare and set retry loop.
  while True:
    room = memcache_client.gets(key)
    if room is None:
      # 'set' and another 'gets' are needed for CAS to work.
      if not memcache_client.set(key, Room()):
        logging.warning('memcache.Client.set failed for key ' + key)
        error = constants.RESPONSE_ERROR
        break
      room = memcache_client.gets(key)

    occupancy = room.get_occupancy()
    if occupancy >= constants.ROOM_SIZE:
      error = constants.RESPONSE_ROOM_FULL
      break

    if not room.has_user(uid):
      seq_updated = True
      room.add_user(uid)

    conns, updated = room.refresh_conns(uid, pc_err, memcache_client)
    if updated:
      seq_updated = True;

    if memcache_client.cas(key, room, constants.ROOM_MEMCACHE_EXPIRATION_SEC):
      logging.info('Added user %s in room %s, retries = %d' \
          %(uid, rid, retries))

      break
    else:
      retries = retries + 1
  return error, conns, seq_updated

def remove_user_from_room(rid, uid):
  key = get_memcache_key_for_room(rid)
  memcache_client = memcache.Client()
  retries = 0
  # Compare and set retry loop.
  while True:
    room = memcache_client.gets(key)
    if room is None:
      logging.warning('remove_user_from_room: Unknown room ' + rid)
      return constants.RESPONSE_UNKNOWN_ROOM
    if not room.has_user(uid):
      logging.warning('remove_user_from_room: Unknown user ' + uid + \
          ' for room ' + rid)
      return None

    room.remove_user(uid)
    if room.get_occupancy() <= constants.AUTO_DESTROY_ROOM_SIZE:
      room = None

    if memcache_client.cas(key, room, constants.ROOM_MEMCACHE_EXPIRATION_SEC):
      logging.info('Removed user %s from room %s, retries=%d' \
          %(uid, rid, retries))
      return None
    retries = retries + 1

def send_message_to_collider(wss_post_url, rid, from_uid, to_uid, message):
  if constants.UNDER_UNIT_TEST:
    return True
  logging.info('Forwarding message to collider for room ' + rid +
                ' from_uid ' + from_uid + ' to_uid ' + to_uid)
  url = wss_post_url + '/' + rid + '/' + from_uid + '/' + to_uid
  result = urlfetch.fetch(url=url,
                          payload=message,
                          method=urlfetch.POST)
  if result.status_code != 200:
    logging.error(
        'Failed to send message to collider: %d' % (result.status_code))

  return result.status_code == 200

class CallPage(webapp2.RequestHandler):
  def post(self):
    uid = self.request.POST['uid']
    rid = self.request.POST['rid']
    call_type = self.request.POST['call_type']
    pc_err = self.request.get_all('pc_err', default_value=[])
    
    logging.warning('handle call: %s, uid %s, rid %s, pc_err %s' % (call_type, uid, rid, ', '.join(pc_err)))

    if call_type == 'join':
      # remove user in case he is already in, which won't update seq
      remove_user_from_room(rid, uid)

    if call_type == 'leave':
      remove_user_from_room(rid, uid)

      wss_url, wss_post_url = get_wss_parameters(self.request)
      send_message_to_collider(wss_post_url, rid, uid, '', json.dumps({
        'type': 'call'
      }))

      self.response.write(json.dumps({
        'result': constants.RESPONSE_SUCCESS
      }))
    elif call_type == 'refresh' or call_type == 'join':
      error, conns, seq_updated = add_user_to_room(rid, uid, pc_err)
      if error is not None:
        self.response.write(json.dumps({
          'result': error
        }))
        return

      wss_url, wss_post_url = get_wss_parameters(self.request)
      if seq_updated:
        send_message_to_collider(wss_post_url, rid, uid, '', json.dumps({
          'type': 'call'
        }))

      self.response.write(json.dumps({
        'result': constants.RESPONSE_SUCCESS,
        'params': {
          'wss_url': wss_url,
          'ice_servers': get_ice_servers(),
          'conns': conns
        }
      }))
    else:
      self.response.write(json.dumps({
        'result': constants.RESPONSE_INVALID_REQUEST,
      }))

app = webapp2.WSGIApplication([
    ('/call', CallPage),
], debug=True)
