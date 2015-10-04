#!/bin/sh

# start mongodb ochopod
exec /sbin/setuser root /usr/bin/python /opt/mongod/pod/pod.py >>/var/log/mongod.log 2>&1

