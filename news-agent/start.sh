#!/bin/sh
# Start both the news agent (background) and web dashboard (foreground)
echo "Starting News Intelligence Agent..."
python main.py &
AGENT_PID=$!

echo "Starting Web Dashboard on port ${PORT:-8000}..."
python -c "
import uvicorn
from dashboard import app
uvicorn.run(app, host='0.0.0.0', port=int(__import__('os').environ.get('PORT', 8000)))
" &
DASHBOARD_PID=$!

# Handle shutdown gracefully
trap "kill $AGENT_PID $DASHBOARD_PID 2>/dev/null; exit 0" SIGTERM SIGINT

# Wait for either process to exit
wait -n $AGENT_PID $DASHBOARD_PID 2>/dev/null || wait $AGENT_PID
