#!/bin/bash
# restarts ngrok every 90 minutes to prevent the 2-hour session expiry
# add to crontab: 0,30 * * * * /path/to/restart_ngrok.sh

echo "Restarting ngrok..."
pkill ngrok
sleep 2

# Assuming ngrok is started on port 8000 (Edge Server) and 5001 (Dashboard)
# Modify this command based on your actual ngrok startup command in start_all.sh
ngrok http 8000 > /dev/null 2>&1 &
echo "ngrok restarted."
