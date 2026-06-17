# Hetzner'a Kurulum

Bu uygulama mevcut projenizle cakismadan ayri bir Docker servisi olarak calisabilir. Varsayilan ayar sadece sunucunun kendi icinden erisilen `127.0.0.1:7860` portunu acar. Dis erisim icin mevcut Nginx'e ayri bir subdomain veya path eklenir.

## 1. Sunucuda repo'yu alin

```bash
git clone REPO_URL video-cutter
cd video-cutter
cp .env.example .env
nano .env
```

`.env` icine gercek OpenAI API key'i yazin:

```
OPENAI_API_KEY=sk-...
```

## 2. Docker ile calistirin

```bash
docker compose up -d --build
docker compose logs -f
```

Kontrol:

```bash
curl http://127.0.0.1:7860/health
```

## 3. Nginx subdomain ornegi

Mevcut projeniz baska portta kalabilir. Bu uygulamayi ornegin `video.example.com` ile yayinlamak icin:

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

## 4. Mevcut projeyle birlikte calistirma

Eger sunucuda baska bir Docker Compose projesi varsa, bu uygulama onunla cakismaz cunku:

- **Port**: Sadece `127.0.0.1:7860` kullanir (diger projeler farkli port kullaniyor olmali)
- **Container adi**: `video-cutter` olarak ayri isimlendirilmistir
- **Network**: Kendi Docker network'unu olusturur
- **Kaynaklar**: `docker-compose.yml` icinde CPU (2 core) ve RAM (4 GB) limitleri tanimlidir, diger servisleri etkilemez

Eger portun mesgul oldugunu gorurseniz, `docker-compose.yml` icindeki `7860` degerini baska bir porta degistirin.

## Notlar

- API key GitHub'a koyulmaz; `.env` dosyasi `.gitignore` icindedir.
- `docker-compose.yml` portu sadece localhost'a baglar.
- Cikti dosyalari (`outputs/` dizini) 1 saat sonra otomatik temizlenir; manuel temizlik gerekmez.
- Uzun videolarda islem dakikalar surebilir; Nginx timeout degerleri bu yuzden yuksek tutuldu.
- Kaynak limitleri `docker-compose.yml` icinde tanimlidir (2 CPU, 4 GB RAM).
- Gevent worker kullanilir; tek gunicorn worker poll isteklerini asenkron olarak karsilar, agir islem subprocess'te calisir.
- Rate limiting IP bazlidir (saatte 5 islem). `app.py` icindeki `MAX_JOBS_PER_IP` degerini ihtiyaca gore ayarlayin.
