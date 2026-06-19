# Hetzner'a Kurulum

Bu uygulama mevcut projenizle çakışmadan ayrı bir Docker servisi olarak çalışabilir. Varsayılan ayar sadece sunucunun kendi içinden erişilen `127.0.0.1:7860` portunu açar. Dış erişim için mevcut Nginx'e ayrı bir subdomain veya path eklenir.

## 1. Sunucuda repo'yu alın

```bash
git clone REPO_URL video-cutter
cd video-cutter
cp .env.example .env
nano .env
```

`.env` içine gerçek OpenAI API key'i yazın:

```bash
OPENAI_API_KEY=sk-...
```

## 2. Docker ile çalıştırın

```bash
docker compose up -d --build
docker compose logs -f
```

Kontrol:

```bash
curl http://127.0.0.1:7860/health
```

## 3. Nginx subdomain örneği

Mevcut projeniz başka portta kalabilir. Bu uygulamayı örneğin `video.example.com` ile yayınlamak için:

```nginx
server {
    server_name video.example.com;

    client_max_body_size 2G;
    proxy_read_timeout 1800;
    proxy_send_timeout 1800;

    location / {
        proxy_pass http://127.0.0.1:7860;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Sonra:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d video.example.com
```

## Notlar

- API key GitHub'a koyulmaz; `.env` dosyası `.gitignore` içindedir.
- `docker-compose.yml` portu sadece localhost'a bağlar, böylece mevcut uygulamanızla çakışmaz.
- Uzun videolarda işlem dakikalar sürebilir; Nginx timeout değerleri bu yüzden yüksek tutuldu.
