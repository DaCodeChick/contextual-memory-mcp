#!/usr/bin/env bash

cd /home/admin/Documents/GitHub/contextual-memory-mcp || exit 1

exec uv run contextual-memory-mcp 2>>/tmp/contextual-memory-mcp.log