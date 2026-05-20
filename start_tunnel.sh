#!/bin/sh
echo 'checking tunnel...'
pkill -f 'cloudflared tunnel' 2>/dev/null
sleep 2
cloudflared tunnel run opera-api > /tmp/tunnel.log 2>&1 &
echo 'tunnel started'
