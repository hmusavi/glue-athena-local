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

### WSL has no internet connection (Cisco AnyConnect VPN)

Cisco AnyConnect VPN takes over the Windows routing table and does not forward
traffic for WSL2's virtual network. This means `apt-get update`, `pip install`,
`curl`, and container image pulls will all fail while the VPN is connected.

You have two options:

#### Option A — Disconnect from VPN before using WSL (quick & easy)

1. Disconnect from Cisco AnyConnect.
2. Use WSL normally — networking will work over Wi-Fi / Ethernet.
3. Reconnect to VPN when you are done with WSL tasks that need internet.

This is the simplest approach if you only need internet in WSL occasionally.

#### Option B — Enable mirrored networking (permanent fix)

WSL 2.1+ supports **mirrored networking mode**, which makes WSL share the
host's network interfaces directly instead of using a NAT'd virtual switch.
This bypasses the VPN routing conflict entirely.

##### Step 1 — Create or update `.wslconfig`

In **PowerShell** (not WSL), create the file at `%USERPROFILE%\.wslconfig`:

```powershell
notepad "$env:USERPROFILE\.wslconfig"
```

Add or merge the following contents:

```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=true
```

- `networkingMode=mirrored` — WSL uses the same network stack as Windows.
- `dnsTunneling=true` — DNS requests are tunneled through Windows, which
  already knows how to resolve names on the VPN.
- `autoProxy=true` — WSL inherits the Windows proxy configuration.

##### Step 2 — Restart WSL

```powershell
wsl --shutdown
```

Then open a new WSL terminal. Verify connectivity:

```bash
ping -c 2 8.8.8.8
```

If pings succeed, IP-level connectivity is restored.

##### Step 3 — Import corporate CA certificates (for HTTPS)

If your organization uses SSL inspection (e.g., **Netskope**, Zscaler, or a
VA TIC firewall), HTTPS connections will fail with
`SSL certificate problem: self-signed certificate in certificate chain` even
after mirrored networking is enabled. You need to import the corporate CA
certificates into WSL's trust store.

**3a. Export certificates from Windows (PowerShell, run as Administrator):**

```powershell
# Create a temp directory for the exported certs
New-Item -ItemType Directory -Path "$env:TEMP\wsl-certs" -Force | Out-Null

# Export Netskope and VA root/intermediate CA certs
# Adjust the -like filters for your organization's CA names
$certs = Get-ChildItem Cert:\LocalMachine\Root | Where-Object {
    $_.Subject -like '*Netskope*' -or
    $_.Subject -like '*VA Internal Root*' -or
    $_.Subject -like '*VA-Internal-S2-RCA*' -or
    $_.Subject -like '*gwlfw*' -or
    $_.Subject -like '*gwsfw*' -or
    $_.Subject -like '*gwnfw*' -or
    $_.Subject -like '*gwefw*' -or
    $_.Subject -like '*gwwfw*'
}

foreach ($cert in $certs) {
    $name = $cert.Thumbprint + ".crt"
    $path = Join-Path "$env:TEMP\wsl-certs" $name
    $bytes = $cert.Export(
        [System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
    $b64 = [Convert]::ToBase64String($bytes,
        [Base64FormattingOptions]::InsertLineBreaks)
    "-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----" |
        Set-Content $path -Encoding ASCII
}

Write-Host "Exported $($certs.Count) certificates to $env:TEMP\wsl-certs"
```

**3b. Import certificates into WSL (run inside WSL):**

```bash
# Copy the exported certs into Ubuntu's trust store
sudo cp /mnt/c/Users/<YOUR_USERNAME>/AppData/Local/Temp/wsl-certs/*.crt \
    /usr/local/share/ca-certificates/

# Rebuild the certificate bundle
sudo update-ca-certificates
```

Replace `<YOUR_USERNAME>` with your Windows username (e.g., `OITWASMUSAVH`).

**3c. Verify HTTPS works:**

```bash
curl -I https://google.com
```

You should see `HTTP/1.1 200 OK` (or a `301` redirect). If you still get
certificate errors, check that the correct CA names were exported in step 3a.

##### Step 4 — Verify full connectivity

```bash
# IP connectivity
ping -c 2 8.8.8.8

# DNS resolution
ping -c 2 google.com

# HTTPS through VPN/proxy
curl -I https://google.com

# Package manager
sudo apt-get update
```

All four commands should succeed while connected to VPN.

---

### Other common issues

- `"/" is not a shared mount` warning in WSL: usually non-fatal; containers still run.
- `cannot connect to Podman socket`: ensure `podman.socket` is active and `DOCKER_HOST` is set.
- `docker` works but compose fails: ensure `docker-compose` is installed and uses same `DOCKER_HOST`.

## Uninstall (optional)

```bash
sudo apt-get remove -y podman podman-docker docker-compose
sudo apt-get autoremove -y
```
