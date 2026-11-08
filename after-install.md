# Camoufox Plugin Installed

Anti-detect browser automation for Hermes (Camoufox / Playwright Firefox).

## System Dependencies Prerequisite

On Linux / Docker environments, Camoufox requires Firefox system libraries (e.g. `libgtk-3`, `libdbus-glib-1-2`, `libxtst6`).

The plugin includes an automatic dependency check. If your environment lacks these libraries and automatic installation fails due to missing root permissions, run the following command:

### In Docker Container (Root):
```bash
docker exec -u 0:0 <container_name> python3 -m playwright install-deps firefox
```

### On Debian / Ubuntu Host:
```bash
sudo apt-get update && sudo apt-get install -y libgtk-3-0 libdbus-glib-1-2 libxtst6 xvfb
```

### Or using the helper script:
```bash
sudo bash data/plugins/camoufox/scripts/install-deps.sh
```

## Enable Plugin

If not already enabled:
```bash
hermes plugins enable camoufox
```
