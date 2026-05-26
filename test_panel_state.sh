#!/usr/bin/env bash
# Test panel state persistence

echo "=== Testing Panel State Persistence ==="
echo ""

# Check server is running
echo "1. Checking server health..."
HEALTH=$(curl -s http://127.0.0.1:5050/api/health)
echo "   Health: $HEALTH"
echo ""

# Get current panel state
echo "2. Current saved panel state..."
curl -s http://127.0.0.1:5050/api/panel-state | python3 -m json.tool
echo ""

# Check localStorage structure just for reference
echo "3. Testing if endpoint works correctly..."
curl -s http://127.0.0.1:5050/api/panel-state | grep -q "panel" && echo "   ✓ /api/panel-state working"
echo ""

# Check server process
echo "4. Server process check..."
ps aux | grep "server.py" | grep -v grep | head -1
echo ""

echo "=== Manual Test Steps ==="
echo "1. Go to CommandCenter web UI"
echo "2. Open channel 1 with any project+agent"
echo "3. Open channel 2 with aws-cloud-architecture + opencode"
echo "4. Switch agents in channel 1"
echo "5. Refresh the page"
echo "6. Check if each channel remembers its project+agent"
echo ""
echo "To check saved state after changes:"
echo "   curl http://127.0.0.1:5050/api/panel-state | python3 -m json.tool"
