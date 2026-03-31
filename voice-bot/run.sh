#!/bin/bash
cd /opt/FreeSwitch_VAPI/voice-bot
source ../venv/bin/activate
export PYTHONPATH=/opt/FreeSwitch_VAPI/voice-bot
python app/main.py "$@"
