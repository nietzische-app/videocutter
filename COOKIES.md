# YouTube Cookie + PO Token Rehberi

YouTube sunucu IP'lerini bot olarak isaretler. Iki katmanli cozum:

1. **cookies.txt** — tarayicindan export (haftalik yenileme)
2. **PO Token provider** — bgutil servisi (bot kontrolunu azaltir)

---

## 1. Cookie export (bilgisayarinda)

1. Chrome'a [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) kur
2. youtube.com'a giris yap
3. Eklenti ile export → `cookies.txt`

**Asla GitHub'a yukleme.** `.gitignore` icinde.

---

## 2. Sunucuya yukle (otomatik script)

```bash
cp scripts/sync-cookies.env.example scripts/sync-cookies.env
nano scripts/sync-cookies.env   # REMOTE=root@IP
chmod +x scripts/sync-cookies.sh
./scripts/sync-cookies.sh
```

Windows:
```powershell
copy scripts\sync-cookies.env.example scripts\sync-cookies.env
# REMOTE duzenle
.\scripts\sync-cookies.ps1
```

Haftalik otomatik (Linux/Mac cron):
```
0 9 * * 1 cd /path/to/videocutter && ./scripts/sync-cookies.sh
```

Windows Gorev Zamanlayici: her Pazartesi `sync-cookies.ps1` calistir.

---

## 3. PO Token provider (sunucuda)

### Docker (onerilen)

```bash
docker run -d --name bgutil-pot --restart unless-stopped \
  -p 127.0.0.1:4416:4416 \
  brainicism/bgutil-ytdlp-pot-provider
```

`.env`:
```env
BGUTIL_POT_URL=http://127.0.0.1:4416
```

### Python plugin

```bash
pip install -U bgutil-ytdlp-pot-provider yt-dlp
```

Provider Docker ile calisirken yt-dlp otomatik kullanir.

---

## 4. .env ornegi

```env
YOUTUBE_COOKIES=cookies.txt
BGUTIL_POT_URL=http://127.0.0.1:4416
COOKIES_MAX_AGE_DAYS=7
# YTDLP_PROXY=http://user:pass@proxy:port
```

---

## 5. Test

```bash
chmod +x scripts/check-youtube.sh
./scripts/check-youtube.sh
```

---

## Sorun giderme

| Hata | Cozum |
|---|---|
| Sign in to confirm you're not a bot | cookies.txt yenile + PO provider calistir |
| Cookie dosyasi X gunluk | sync-cookies script calistir |
| POT provider erisilemiyor | `docker ps`, port 4416 acik mi |
| Hala calismiyor | `pip install -U yt-dlp`, `YTDLP_PROXY` dene |
