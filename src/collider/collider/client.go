// Copyright (c) 2014 The WebRTC project authors. All Rights Reserved.
// Use of this source code is governed by a BSD-style license
// that can be found in the LICENSE file in the root of the source
// tree.

package collider

import (
	"errors"
	"io"
	"log"
	"time"
)

const maxQueuedMsgCount = 1024

type client struct {
	id string
	// rwc is the interface to access the websocket connection.
	// It is set after the client registers with the server.
	rwc io.ReadWriteCloser
	// timer is used to remove this client if unregistered after a timeout.
	timer *time.Timer
}

func newClient(id string, t *time.Timer) *client {
	c := client{id: id, timer: t}
	return &c
}

func (c *client) setTimer(t *time.Timer) {
	if c.timer != nil {
		c.timer.Stop()
	}
	c.timer = t
}

// register binds the ReadWriteCloser to the client if it's not done yet.
func (c *client) register(rwc io.ReadWriteCloser) error {
	if c.rwc != nil {
		log.Printf("Not registering because the client %s already has a connection", c.id)
		return errors.New("Duplicated registration")
	}
	c.setTimer(nil)
	c.rwc = rwc
	return nil
}

// deregister closes the ReadWriteCloser if it exists.
func (c *client) deregister() {
	if c.rwc != nil {
		c.rwc.Close()
		c.rwc = nil
	}
}

// registered returns true if the client has registered.
func (c *client) registered() bool {
	return c.rwc != nil
}

// send sends the message to the other client if the other client has registered,
// or queues the message otherwise.
func (c *client) send(other *client, receiverID, msg string) error {
	if c.id == other.id {
		return errors.New("Invalid client")
	}
	if other.rwc != nil {
		return sendServerMsg(other.rwc, receiverID, msg)
	}
	return nil
}
