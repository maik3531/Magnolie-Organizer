"""Diagnose local IPC availability without binding or connecting any socket."""
import json
import socket
import sys

result = {"operation": "socket(AF_UNIX, SOCK_STREAM)", "bind_or_connect_attempted": False}
try:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.close()
    result["ok"] = True
except OSError as error:
    result.update(ok=False, errno=error.errno, error=str(error))
print(json.dumps(result))
raise SystemExit(0 if result["ok"] else 1)
