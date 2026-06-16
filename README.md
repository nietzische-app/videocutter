# Otomatik Video Kesici

Bu arac videodaki sesi OpenAI `whisper-1` ile metne doker, transkripti GPT modeline gonderip en iyi ~30 saniyeik araligi sectirir ve MoviePy ile 9:16 dikey MP4 uretir.

## Ozellikler

- YouTube linki veya yerel video dosyasi destegi
- Whisper ile otomatik transkripsiyon
- GPT ile en ilgi cekici anin secimi
- Uzun videolarda (>5 dk) parcali analiz: video pencereler halinde bolunur, her pencere ayri puanlanir, en iyi secilir
- 9:16 dikey format (TikTok, Reels, Shorts uyumlu)
- Adim adim ilerleme gosterimi ve video onizleme
- Cikti dosyalari 1 saat sonra otomatik temizlenir
- IP basina saatte 5 islem limiti

## Kurulum

Python 3.11+ onerilir. Bilgisayarinizda `ffmpeg` kurulu olmali.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."  # Windows: $env:OPENAI_API_KEY="sk-..."
```

## Kullanim

### Web Arayuzu

```bash
python app.py
```

Tarayicida `http://127.0.0.1:7860` adresine gidin. YouTube linkini girin, islem adim adim ilerleme cubugunda gorunur, bitince video onizlemesi ve indirme butonu cikar.

### Komut Satiri

```bash
python video_cutter.py "https://www.youtube.com/watch?v=VIDEO_ID" -o "outputs/clip.mp4"
```

Yerel dosya ile:

```bash
python video_cutter.py "/path/to/video.mp4" -o "outputs/clip.mp4"
```

Ayarlar:

```bash
python video_cutter.py "video.mp4" \
  --clip-seconds 30 \
  --language tr \
  --whisper-model whisper-1 \
  --gpt-model gpt-4.1-mini \
  --target-height 1920 \
  -o "outputs/short.mp4"
```

### Docker ile Calistirma

Hetzner veya baska bir Linux sunucuya kurmak icin [DEPLOY.md](DEPLOY.md) dosyasina bakin.

```bash
cp .env.example .env
# .env icine gercek API key'i yazin
docker compose up -d --build
```

## Guvenlik

- `.env` dosyasi `.gitignore` icindedir, API key GitHub'a yuklenmez
- Web arayuzunden girilen API key'ler sunucu tarafinda sadece isleme gecilir, saklanmaz
- Giris dogrulamasi: path traversal ve shell injection korumalari mevcuttur
- Rate limiting: IP basina saatte 5 islem
- YouTube indirme ozelligini yalnizca indirme izniniz olan videolarda kullanin
