# Hosting on a Linux server with nginx

Runs the app as a systemd service on `127.0.0.1:8756`, with nginx in front for
**authentication**, TLS, and large uploads.

Verified on Ubuntu 24.04 (nginx 1.24) with a real upload through the proxy.

> **Read this first.** The app has **no login of its own**. Anyone who reaches
> it can read every transcript, download the audio, replace your Gemini API key
> and delete meetings. nginx is what keeps it private — do not skip the
> `auth_basic` section, and never bind the app itself to `0.0.0.0` on a network
> you don't control.

---

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg nginx apache2-utils
```

`python3-venv` is separate from `python3` on Debian/Ubuntu — without it
`python3 -m venv` fails with *"ensurepip is not available"*.
`apache2-utils` provides `htpasswd`.

## 2. Install the app

```bash
sudo mkdir -p /opt/meeting-transcriber
sudo chown $USER: /opt/meeting-transcriber
# copy the project in (git clone / rsync / scp), then:
cd /opt/meeting-transcriber
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt        # CPU-ready, ~487 MB

# only if `nvidia-smi` shows a card — this pulls ~2.3 GB of CUDA libraries
nvidia-smi && ./.venv/bin/pip install -r requirements-gpu.txt
```

Speaker models (~165 MB), once:

```bash
mkdir -p models
BASE=https://github.com/k2-fsa/sherpa-onnx/releases/download
curl -L -o models/nemo_en_titanet_large.onnx \
  "$BASE/speaker-recongition-models/nemo_en_titanet_large.onnx"
curl -L -o models/seg.tar.bz2 \
  "$BASE/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
tar -xjf models/seg.tar.bz2 -C models && rm models/seg.tar.bz2
```

Whisper `large-v3` (~3 GB) downloads itself on the first transcription. To
fetch it up front:

```bash
./.venv/bin/python -c "from huggingface_hub import snapshot_download; \
  snapshot_download('Systran/faster-whisper-large-v3')"
```

**Use `large-v3` even without a GPU** — ~24 min per hour of audio on 8 CPU
threads. Smaller models silently translate Malay-English speech instead of
transcribing it (see [summary.md §5](summary.md)).

## 3. Service user

```bash
sudo useradd --system --home /opt/meeting-transcriber --shell /usr/sbin/nologin meetings
sudo chown -R meetings: /opt/meeting-transcriber
```

## 4. systemd unit

`/etc/systemd/system/meeting-transcriber.service`:

```ini
[Unit]
Description=NoteRecall
After=network.target

[Service]
Type=simple
User=meetings
Group=meetings
WorkingDirectory=/opt/meeting-transcriber

# Bind to localhost ONLY. nginx is the only thing that should reach it.
Environment=HOST=127.0.0.1
Environment=PORT=8756
# Give the service user a writable model cache (the Setup page honours this).
Environment=HF_HOME=/opt/meeting-transcriber/.cache/huggingface

ExecStart=/opt/meeting-transcriber/.venv/bin/python server.py
Restart=on-failure
RestartSec=5

# Transcription pegs 8 cores for minutes at a time; be a good neighbour.
Nice=10

# Basic hardening — it only ever needs its own directory.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/opt/meeting-transcriber

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now meeting-transcriber
systemctl status meeting-transcriber
curl -s localhost:8756/api/status        # sanity check
```

Logs: `journalctl -u meeting-transcriber -f`

## 5. Password file

```bash
sudo htpasswd -c /etc/nginx/.htpasswd hafiz     # add more users: drop the -c
sudo chown root:www-data /etc/nginx/.htpasswd
sudo chmod 640 /etc/nginx/.htpasswd
```

## 6. nginx

`/etc/nginx/sites-available/meeting-transcriber`:

```nginx
server {
    listen 80;
    server_name meetings.example.com;   # or the server's IP

    # Recordings are big. nginx defaults to 1 MB, which fails EVERY upload
    # with 413. A 2-hour m4a is ~100 MB; leave headroom.
    client_max_body_size 2g;
    client_body_timeout  600s;

    # The app has no login of its own. This is the only thing protecting it.
    auth_basic           "NoteRecall";
    auth_basic_user_file /etc/nginx/.htpasswd;

    access_log /var/log/nginx/meetings.access.log;
    error_log  /var/log/nginx/meetings.error.log;

    location / {
        proxy_pass http://127.0.0.1:8756;
        proxy_http_version 1.1;                 # required for the two off's below

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Stream the upload straight through instead of spooling the whole
        # recording to disk first.
        proxy_request_buffering off;
        # The audio player seeks with HTTP Range and the server answers 206;
        # don't let nginx buffer that.
        proxy_buffering off;

        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/meeting-transcriber /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

## 7. TLS

Basic auth sends the password in clear text over HTTP — put TLS in front of it
if the server is reachable beyond a trusted LAN:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d meetings.example.com
```

certbot edits the same server block and adds the redirect. Re-check
`client_max_body_size` survived.

## 8. Firewall

```bash
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Port 8756 must **not** be open — nginx reaches it over loopback.

---

## Verifying it works

```bash
# 401 without credentials — if this returns 200, auth is not applied
curl -s -o /dev/null -w '%{http_code}\n' http://meetings.example.com/

# 200 with them
curl -s -u hafiz:PASS -o /dev/null -w '%{http_code}\n' http://meetings.example.com/

# uploads over 1 MB pass (413 here means client_max_body_size is wrong)
curl -s -u hafiz:PASS -X POST http://meetings.example.com/api/meetings \
  -F "file=@meeting.m4a" -F "title=Test" -F "num_speakers=0"

# audio seeking works (must be 206, not 200)
curl -s -u hafiz:PASS -o /dev/null -w '%{http_code}\n' \
  -H 'Range: bytes=0-99' http://meetings.example.com/api/meetings/<id>/audio
```

## Troubleshooting

| symptom | cause |
|---|---|
| **413 Request Entity Too Large** | `client_max_body_size` too small (default 1 MB) |
| **504 during a big upload** | raise `proxy_read_timeout` / `client_body_timeout` |
| Player won't seek; restarts from 0 | Range being swallowed — check `proxy_buffering off` and that no cache sits in front |
| Setup says the Whisper model is missing, but it's downloaded | `HF_HOME` differs between the shell you downloaded with and the service user |
| Job stuck at "queued" | one worker, one job at a time — check `journalctl -u meeting-transcriber` |
| **Anyone can open it** | `auth_basic` missing, or the app is bound to `0.0.0.0` and reachable directly on 8756 |
| Permission denied writing `data/` | `chown -R meetings: /opt/meeting-transcriber` |

## Operating notes

- **Disk grows with every meeting** — the original audio is kept in
  `data/<id>/`. Budget roughly 1 GB per 10 hours of recording plus ~3.5 GB of
  models. Delete meetings from the UI to reclaim space.
- **One job at a time.** A 2-hour meeting occupies the worker for ~45 min on
  CPU; anything uploaded meanwhile waits.
- **Restarts are safe.** Jobs interrupted by a restart are re-queued
  automatically on startup.
- **Cloud engine on a server:** `config.json` holds the Gemini key in plain
  text — `chmod 600` it, and remember audio then leaves your server for Google.
