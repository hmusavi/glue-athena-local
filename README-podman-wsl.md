# Podman on WSL with Docker Compatibility

This guide installs Podman on Ubuntu WSL, enables Docker-compatible commands (`docker`, `docker-compose`), and validates everything works.

## Prerequisites

- Windows with WSL2 enabled
- Ubuntu distro in WSL (tested on Ubuntu 24.04)
- A sudo-capable user

## 1) Install Podman in WSL

```bash
sudo apt-get update
sudo apt-get install -y podman uidmap slirp4netns fuse-overlayfs
```

## 2) Verify Podman

```bash
podman --version
podman info --debug | head -n 40
podman run --rm hello-world
```

Expected: the `hello-world` container runs successfully.

## 3) Enable Docker command compatibility

Install the compatibility package:

```bash
sudo apt-get install -y podman-docker
```

This provides a `docker` CLI shim backed by Podman.

Verify:

```bash
docker version
docker run --rm hello-world
```

Optional (silence shim notice):

```bash
sudo mkdir -p /etc/containers
sudo touch /etc/containers/nodocker
```

## 4) Enable Docker API-compatible socket

Start Podman user socket and enable it on login:

```bash
systemctl --user enable --now podman.socket
systemctl --user is-active podman.socket
systemctl --user is-enabled podman.socket
```

Set `DOCKER_HOST` so Docker clients talk to Podman socket:

```bash
echo 'export DOCKER_HOST=unix:///run/user/$UID/podman/podman.sock' >> ~/.bashrc
source ~/.bashrc
```

Check:

```bash
echo "$DOCKER_HOST"
ls -l /run/user/$UID/podman/podman.sock
```

## 5) Docker Compose compatibility

Ubuntu package:

```bash
sudo apt-get install -y docker-compose
```

Quick smoke test:

```bash
mkdir -p ~/compose-smoke-test && cd ~/compose-smoke-test
cat > docker-compose.yml <<'YAML'
services:
  web:
    image: nginx:alpine
    ports:
      - "8089:80"
YAML

docker-compose up -d
curl -I http://127.0.0.1:8089 | head -n 1
docker-compose down -v
cd ~ && rm -rf ~/compose-smoke-test
```

## 6) VS Code as Docker/Podman desktop (optional)

Install extensions in WSL VS Code server:

```bash
code --install-extension ms-azuretools.vscode-docker --force
code --install-extension dreamcatcher45.podmanager --force
```

Workspace settings (`.vscode/settings.json`) example:

```json
{
  "docker.host": "unix:///run/user/1000/podman/podman.sock",
  "docker.environment": {
    "DOCKER_HOST": "unix:///run/user/1000/podman/podman.sock"
  },
  "docker.dockerPath": "docker",
  "terminal.integrated.env.linux": {
    "DOCKER_HOST": "unix:///run/user/1000/podman/podman.sock"
  }
}
```

> Replace `1000` with your UID if different (`id -u`).

## 7) (Optional) Connect Windows Podman Desktop to WSL Podman

Use SSH connection to the WSL Podman socket.

In WSL:

```bash
sudo apt-get install -y openssh-server
sudo systemctl enable --now ssh
```

Then add a Podman Desktop connection using:

- Host: `localhost`
- User: your WSL username (for example `hamid`)
- Socket path: `/run/user/1000/podman/podman.sock`

Connection URI format:

```text
ssh://<user>@localhost/run/user/<uid>/podman/podman.sock
```

## Troubleshooting

- `"/" is not a shared mount` warning in WSL: usually non-fatal; containers still run.
- `cannot connect to Podman socket`: ensure `podman.socket` is active and `DOCKER_HOST` is set.
- `docker` works but compose fails: ensure `docker-compose` is installed and uses same `DOCKER_HOST`.

## Uninstall (optional)

```bash
sudo apt-get remove -y podman podman-docker docker-compose
sudo apt-get autoremove -y
```
