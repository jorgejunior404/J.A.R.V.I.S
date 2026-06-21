#!/bin/bash
cd "/home/jorge/jarvis/J.A.R.V.I.S"
nohup /home/jorge/jarvis/J.A.R.V.I.S/.venv/bin/python3 jarvis_launcher.py > /tmp/jarvis_output.log 2>&1 &
echo "JARVIS iniciado. PID: $!"
echo "Log em: /tmp/jarvis_output.log"
