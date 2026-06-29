#!/bin/bash
# QFACE Start Script
# Set your internal key before starting:
# export QFACE_INTERNAL_KEY="your-strong-random-key"

if [ "$QFACE_INTERNAL_KEY" = "CHANGE_ME_IN_PRODUCTION" ] || [ -z "$QFACE_INTERNAL_KEY" ]; then
    echo "⚠️  WARNING: QFACE_INTERNAL_KEY not set. Set it via:"
    echo "    export QFACE_INTERNAL_KEY='your-strong-key'"
    echo ""
fi

echo "🚀 Starting QFACE..."
echo "   Recognition: http://localhost:8001  (internal only)"
echo "   Camera:      http://localhost:8000  (stream only public)"
echo "   Dashboard:   http://localhost:8080  (main interface)"
echo ""

# Start recognition server
python3 recognition_server.py &
RECOG_PID=$!

# Start camera server
python3 camera_server.py &
CAM_PID=$!

# Wait for them to be ready
sleep 2

# Start main server
python3 main_server.py &
MAIN_PID=$!

echo "✅ All servers started"
echo "   Recognition PID: $RECOG_PID"
echo "   Camera PID:      $CAM_PID"
echo "   Main PID:        $MAIN_PID"
echo ""
echo "Default login: admin / admin123  — CHANGE THIS IMMEDIATELY"
echo ""

wait
