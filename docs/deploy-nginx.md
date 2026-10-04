# Hosting NoteRecall on a Linux server (nginx)

This guide puts NoteRecall on an always-on Linux server so several people can
open it through a web address, protected by a password.

What you end up with:

| Piece | Where it lives |
|---|---|
| The app | `/opt/noterecall` |
| Meetings (audio, transcripts) | `/opt/noterecall/data` |
| Background service file | `/etc/systemd/system/noterecall.service` |
| Web server (nginx) site file | `/etc/nginx/sites-available/noterecall` (+ a link in `/etc/nginx/sites-enabled/`) |
| Password file | `/etc/nginx/.htpasswd` |
| Logs | `journalctl -u noterecall` (app), `/var/log/nginx/noterecall.*.log` (nginx) |

Verified on Ubuntu 24.04 with nginx 1.24. Other Debian-based systems work the
same way.

> ⚠️ **Read this first.** NoteRecall has **no login of its own**. Anyone who
> reaches it can read every transcript, download the audio, replace your
> Gemini API key and delete meetings. nginx's password (step 6) is what keeps
> it private — do not skip it, and never start the app with `HOST=0.0.0.0` on
> a network you don't control.

**How to use this guide:** connect to your server (for example `ssh you@server`)
and paste each grey box into the terminal, **one box at a time**. Words in
`CAPITALS` like `YOUR_DOMAIN` are placeholders — the box right before them
tells you how to set them.

---

## 0. Set your two placeholders

Your web address (or the server's IP address if you have no domain), and the
name you'll log in with. Change the values between the quotes, then paste:

```bash
YOUR_DOMAIN="meetings.example.com"
YOUR_LOGIN="admin"
```

These only last for this terminal session. If you reconnect, paste this box
again before continuing.

## 1. Install the system packages

```bash
sudo apt update
sudo apt install -y git curl python3-venv nginx apache2-utils
```

(`python3-venv` lets Python create the app's environment; `apache2-utils`
provides the `htpasswd` password tool.)

## 2. Download the app into `/opt/noterecall`

```bash
sudo git clone https://github.com/SirCoolMind/NoteRecall.git /opt/noterecall
sudo chown -R "$USER": /opt/noterecall
cd /opt/noterecall
```

Create its Python environment and install the packages (~500 MB):

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

**Only if the server has an NVIDIA graphics card** (this adds ~2.3 GB):

```bash
nvidia-smi && ./.venv/bin/pip install -r requirements-gpu.txt
```

Download the speaker-detection models (~165 MB) into `/opt/noterecall/models`:

```bash
mkdir -p models
BASE=https://github.com/k2-fsa/sherpa-onnx/releases/download
curl -L -o models/nemo_en_titanet_large.onnx \
  "$BASE/speaker-recongition-models/nemo_en_titanet_large.onnx"
curl -L -o models/seg.tar.bz2 \
  "$BASE/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
tar -xjf models/seg.tar.bz2 -C models && rm models/seg.tar.bz2
```

Download the Whisper speech model (~3 GB) into
`/opt/noterecall/.cache/huggingface` so the service can find it:

```bash
HF_HOME=/opt/noterecall/.cache/huggingface ./.venv/bin/python -c \
  "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-large-v3')"
```

**Use `large-v3` even without a graphics card** — about 24 minutes per hour of
audio on 8 CPU threads. Smaller models silently translate Malay-English speech
instead of transcribing it (see [summary.md §5](summary.md)).

## 3. Create a user for the service

The app runs as its own locked-down user called `noterecall`, which owns the
app folder:

```bash
sudo useradd --system --home /opt/noterecall --shell /usr/sbin/nologin noterecall
sudo chown -R noterecall: /opt/noterecall
```

## 4. Create the service file — `/etc/systemd/system/noterecall.service`

This makes NoteRecall start automatically with the server and restart if it
crashes. Paste the whole box; it writes the file for you:

```bash
sudo tee /etc/systemd/system/noterecall.service > /dev/null <<'EOF'
[Unit]
Description=NoteRecall
After=network.target

[Service]
Type=simple
User=noterecall
Group=noterecall
WorkingDirectory=/opt/noterecall

# Listen on this machine ONLY. nginx is the only thing that should reach it.
Environment=HOST=127.0.0.1
Environment=PORT=8756
# Where the Whisper model was downloaded in step 2.
Environment=HF_HOME=/opt/noterecall/.cache/huggingface

ExecStart=/opt/noterecall/.venv/bin/python server.py
Restart=on-failure
RestartSec=5

# Transcription keeps 8 cores busy for minutes at a time; be a good neighbour.
Nice=10

# Basic hardening: it only ever needs its own folder.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/opt/noterecall

[Install]
WantedBy=multi-user.target
EOF
```

Start it, and make it start on every boot:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now noterecall
```

Check it is running — you should see `active (running)` (press `q` to leave):

```bash
systemctl status noterecall
```

And that it answers (prints a short JSON line):

```bash
curl -s http://127.0.0.1:8756/api/status
```

To watch its log live: `journalctl -u noterecall -f` (Ctrl + C to stop
watching).

## 5. Create the nginx site file — `/etc/nginx/sites-available/noterecall`

nginx is the front door: it asks for the password, accepts big uploads, and
passes everything to NoteRecall. This box writes the file and fills in your
domain from step 0:

```bash
sudo tee /etc/nginx/sites-available/noterecall > /dev/null <<EOF
server {
    listen 80;
    server_name ${YOUR_DOMAIN};

    # Recordings are big. nginx's default is 1 MB, which fails EVERY upload
    # with "413". A 2-hour m4a is ~100 MB; leave headroom.
    client_max_body_size 2g;
    client_body_timeout  600s;

    # NoteRecall has no login of its own. This is the only thing protecting it.
    auth_basic           "NoteRecall";
    auth_basic_user_file /etc/nginx/.htpasswd;

    access_log /var/log/nginx/noterecall.access.log;
    error_log  /var/log/nginx/noterecall.error.log;

    location / {
        proxy_pass http://127.0.0.1:8756;
        proxy_http_version 1.1;

        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # Stream uploads straight through instead of saving them to disk first.
        proxy_request_buffering off;
        # The audio player jumps around using HTTP Range requests; don't buffer.
        proxy_buffering off;

        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
EOF
```

Check the file has your domain in it (look at the `server_name` line):

```bash
grep server_name /etc/nginx/sites-available/noterecall
```

Turn the site on (this creates the link
`/etc/nginx/sites-enabled/noterecall`) and turn off nginx's default welcome
page:

```bash
sudo ln -sf /etc/nginx/sites-available/noterecall /etc/nginx/sites-enabled/noterecall
sudo rm -f /etc/nginx/sites-enabled/default
```

## 6. Set the password — `/etc/nginx/.htpasswd`

This asks you to type a password twice (nothing shows while you type — that's
normal):

```bash
sudo htpasswd -c /etc/nginx/.htpasswd "$YOUR_LOGIN"
sudo chown root:www-data /etc/nginx/.htpasswd
sudo chmod 640 /etc/nginx/.htpasswd
```

To add **another** person later, run this (note: **no** `-c`, which would wipe
the existing users), replacing `OTHER_NAME`:

```bash
sudo htpasswd /etc/nginx/.htpasswd OTHER_NAME
```

Now check nginx's settings and load them. It must say `syntax is ok` and
`test is successful`:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Open `http://YOUR_DOMAIN` in a browser: it should ask for the login, then show
NoteRecall.

## 7. HTTPS (strongly recommended)

Without HTTPS the password travels unencrypted. If you have a real domain name
pointing at this server, this gets a free certificate and updates the nginx
file for you:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d "$YOUR_DOMAIN"
```

Afterwards, confirm the upload limit survived certbot's edit (should print
`client_max_body_size 2g;`):

```bash
grep client_max_body_size /etc/nginx/sites-available/noterecall
```

## 8. Firewall

Allow web traffic, and keep NoteRecall's own port (8756) closed — nginx reaches
it from inside the machine:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

(`OpenSSH` is allowed first so you don't lock yourself out of the server.)

---

## Check that everything works

Replace `YOUR_PASSWORD` with the password from step 6.

Without a password you must be refused — this must print `401`. If it prints
`200`, the password is **not** active; recheck step 5–6:

```bash
curl -s -o /dev/null -w '%{http_code}\n' "http://$YOUR_DOMAIN/"
```

With the password it must print `200`:

```bash
curl -s -u "$YOUR_LOGIN:YOUR_PASSWORD" -o /dev/null -w '%{http_code}\n' "http://$YOUR_DOMAIN/"
```

(After step 7, use `https://` instead of `http://`.)

---

## Updating to a newer version

**In the app (easiest).** Open **Settings (gear) → Updates → Check for updates →
Update now**. NoteRecall fetches the new release, installs any changed
packages, then exits with code 75 so the service restarts itself (the unit's
`Restart=on-failure` already treats that as a failure and restarts it). The
update waits while a meeting is processing and refuses if tracked files were
edited on the server. Everything must be writable by the `noterecall` user
(`sudo chown -R noterecall: /opt/noterecall`).

**On the command line.**

```bash
cd /opt/noterecall
sudo -u noterecall git pull
sudo -u noterecall ./.venv/bin/pip install -r requirements.txt
sudo systemctl restart noterecall
```

Meetings in `/opt/noterecall/data` and settings in
`/opt/noterecall/config.json` are kept.

## Troubleshooting

| What you see | Cause and fix |
|---|---|
| **413 Request Entity Too Large** when uploading | `client_max_body_size` is missing or too small in `/etc/nginx/sites-available/noterecall`. Fix it, then `sudo nginx -t && sudo systemctl reload nginx`. |
| **502 Bad Gateway** | The app isn't running. `systemctl status noterecall` and `journalctl -u noterecall -n 50` show why. |
| **504** during a big upload | Raise `proxy_read_timeout` and `client_body_timeout` in the nginx site file. |
| The player won't jump; always restarts from 0 | Check `proxy_buffering off;` is in the nginx site file, and no other cache sits in front. |
| Setup says the Whisper model is missing, but you downloaded it | It was downloaded somewhere other than `/opt/noterecall/.cache/huggingface`. Repeat the Whisper download in step 2, then `sudo chown -R noterecall: /opt/noterecall`. |
| A meeting stays "Queued" | One meeting is processed at a time; it's waiting its turn. `journalctl -u noterecall -f` shows progress. |
| **Anyone can open it without a password** | `auth_basic` lines missing from the nginx site file, or the app was started with `HOST=0.0.0.0`. |
| `Permission denied` writing `data/` | `sudo chown -R noterecall: /opt/noterecall` |

## Good to know

- **Disk use grows with every meeting** — the original audio is kept in
  `/opt/noterecall/data/<id>/`. Budget about 1 GB per 10 hours of recording,
  plus ~3.5 GB for the models. Deleting a meeting in the app frees its space.
- **One meeting at a time.** A 2-hour meeting keeps the server busy for ~45
  minutes on CPU; anything uploaded meanwhile waits in the queue.
- **Restarts are safe.** Meetings interrupted by a restart are queued again
  automatically.
- **Cloud engine on a server:** `/opt/noterecall/config.json` holds the Gemini
  key in plain text. Lock it down with
  `sudo chmod 600 /opt/noterecall/config.json`, and remember audio then leaves
  your server for Google.
