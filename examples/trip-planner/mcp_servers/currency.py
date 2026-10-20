"""A currency MCP server that was never finished: it exits at start-up.

PLANTED: FlowForge's health check should show this server as down, with the reason below.
"""

import os
import sys

if not os.getenv("CURRENCY_API_URL"):
    sys.exit("currency server: CURRENCY_API_URL is not set")
