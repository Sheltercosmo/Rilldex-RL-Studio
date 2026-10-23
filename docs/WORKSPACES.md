# Workspaces

Click the workspace name in the sidebar to switch studies. Search recent workspaces, open an existing database, or create a new one. Relative paths start beside the current database; paths refer to the machine running Rilldex.

Each workspace has its own projects, saved comparisons, records and capture endpoint. Switching restores its last page and leaves collection running. Workspaces opened through the picker close with their launching server; independently started servers remain open. Reopening retains the saved capture port. If that port is occupied, resolve the conflict or start on a new port and update your collectors.

```sh
rilldex workspace add ./study.sqlite --name "Reasoning study"
rilldex workspace list
rilldex --db ./study.sqlite start --open
```

**Remove from recents** removes a closed workspace from the picker without deleting its files. Use **Download workspace** in the experiment list for a portable backup; restore it with `rilldex --db restored.sqlite workspace restore backup.rilldex.zip`.

The recent list lives in `~/.rilldex/workspaces.sqlite`. Set `RILLDEX_WORKSPACE_REGISTRY` to use another location. Switching launches separate loopback ports: use separate servers/tunnels for remote studies and containers. This is local workspace organization; it does not add shared accounts or permissions.
