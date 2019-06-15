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

const maxRoomCapacity = 4

type room struct {
	parent *roomTable
	id     string
	// A mapping from the client ID to the client object.
	clients         map[string]*client
	registerTimeout time.Duration
	roomSrvUrl      string
}

func newRoom(p *roomTable, id string, to time.Duration, rs string) *room {
	return &room{parent: p, id: id, clients: make(map[string]*client), registerTimeout: to, roomSrvUrl: rs}
}

// client returns the client, or creates it if it does not exist and the room is not full.
func (rm *room) client(clientID string) (*client, error) {
	if c, ok := rm.clients[clientID]; ok {
		return c, nil
	}
	if len(rm.clients) >= maxRoomCapacity {
		log.Printf("Room %s is full, not adding client %s", rm.id, clientID)
		return nil, errors.New("Max room capacity reached")
	}

	var timer *time.Timer
	if rm.parent != nil {
		timer = time.AfterFunc(rm.registerTimeout, func() {
			if c := rm.clients[clientID]; c != nil {
				rm.parent.removeIfUnregistered(rm.id, c)
			}
		})
	}
	rm.clients[clientID] = newClient(clientID, timer)

	log.Printf("Added client %s to room %s", clientID, rm.id)

	return rm.clients[clientID], nil
}

// register binds a client to the ReadWriteCloser.
func (rm *room) register(clientID string, rwc io.ReadWriteCloser) error {
	c, err := rm.client(clientID)
	if err != nil {
		return err
	}
	if err = c.register(rwc); err != nil {
		return err
	}

	log.Printf("Client %s registered in room %s", clientID, rm.id)

	return nil
}

// send sends the message to the other client of the room, or queues the message if the other client has not joined.
func (rm *room) send(srcClientID string, dstClientID string, msg string) error {
	src, err := rm.client(srcClientID)
	if err != nil {
		return err
	}

	// Send the message to the other client of the room.
	for _, oc := range rm.clients {
		err1 := src.send(oc, dstClientID, msg)
		if err1 != nil {
			err = err1
		}
	}

	return err
}

// remove closes the client connection and removes the client specified by the |clientID|.
func (rm *room) remove(clientID string) {
	if c, ok := rm.clients[clientID]; ok {
		c.deregister()
		delete(rm.clients, clientID)
		log.Printf("Removed client %s from room %s", clientID, rm.id)
	}
}

// empty returns true if there is no client in the room.
func (rm *room) empty() bool {
	return len(rm.clients) == 0
}

func (rm *room) wsCount() int {
	count := 0
	for _, c := range rm.clients {
		if c.registered() {
			count += 1
		}
	}
	return count
}
