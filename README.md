# Shorts Fabrikasi

YouTube Shorts kanallari icin viral video kesfi, AI klip secimi, beyaz cerceveli sablon ve metadata uretimi.

## Ozellikler

- **6 kategori:** Komedi, Film Sahneleri, Futbol, Roblox, Foodporn, Yayinci Klipleri
- **Otomatik kesif:** Kategoriye gore trend YouTube videolari bulur
- **Manuel ekleme:** Link yapistirip isleyebilirsin
- **Sablon:** Beyaz kenarliklar, ustte baslik, altta `via @kanal`
- **Metadata:** YouTube basligi, aciklama (via + kaynak link), hashtagler
- **YouTube yukleme (opsiyonel):** OAuth ile otomatik yukleme

## Kurulum

Python 3.11+ ve `ffmpeg` gerekli.

```powershell
python -m pip install -r requirements.txt
copy .env.example .env
# .env icine OPENAI_API_KEY yaz
```

## Web arayuzu

```powershell
python app.py
```

Tarayici: http://127.0.0.1:7860

1. Kategori sec (ornegin Komedi)
2. "Videolari Bul" ile otomatik kesif veya link yapistir
3. "Shorts Uret" — indir + metadata kopyala

## CLI

```powershell
python shorts_pipeline.py "https://www.youtube.com/watch?v=..." -o outputs/short.mp4 --category comedy
```

## YouTube otomatik yukleme

1. [Google Cloud Console](https://console.cloud.google.com/) → YouTube Data API v3 etkinlestir
2. OAuth 2.0 Client ID olustur, `client_secrets.json` indir
3. `python youtube_upload.py --auth` calistir
4. Web arayuzunde "YouTube'a otomatik yukle" sec

---

# Otomatik Video Kesici (temel motor)

Bu arac videodaki sesi OpenAI `whisper-1` ile metne döker, transkripti GPT modeline gönderip en iyi 30 saniyelik aralığı seçtirir ve MoviePy ile 9:16 dikey MP4 üretir.

## Kurulum

Python 3.11+ önerilir. Bilgisayarınızda `ffmpeg` kurulu olmalı ve terminalden erişilebilmelidir.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:OPENAI_API_KEY="sk-..."
```

## Kullanım

PowerShell ile uğraşmadan kullanmak için [start_web_app.bat](start_web_app.bat) dosyasına çift tıklayın. Tarayıcıda açılan sayfaya YouTube linkini ve OpenAI API key'inizi yapıştırıp klibi oluşturabilirsiniz.

Hetzner veya başka bir Linux sunucuya kurmak için [DEPLOY.md](DEPLOY.md) dosyasına bakın. Docker Compose ile `127.0.0.1:7860` üzerinde ayrı servis olarak çalışır; mevcut projenizle aynı portu kullanmaz.

```powershell
python video_cutter.py "C:\videolar\kaynak.mp4" -o "outputs\clip_vertical.mp4"
```

YouTube linkiyle de çalışır:

```powershell
python video_cutter.py "https://www.youtube.com/watch?v=VIDEO_ID" -o "outputs\clip_vertical.mp4"
```

Yalnızca indirme ve yeniden kullanma izniniz olan videolarda kullanın.

PowerShell `pip` komutunu bulamazsa `pip install ...` yerine her zaman şunu kullanın:

```powershell
python -m pip install -r requirements.txt
```

Tek komutla kurup çalıştırmak için:

```powershell
.\setup_and_run.ps1 -InputVideo "C:\videolar\kaynak.mp4" -OutputVideo "outputs\clip_vertical.mp4"
```

YouTube için:

```powershell
.\setup_and_run.ps1 -InputVideo "https://www.youtube.com/watch?v=VIDEO_ID"
```

İsteğe bağlı ayarlar:

```powershell
python video_cutter.py "C:\videolar\kaynak.mp4" `
  --clip-seconds 30 `
  --language tr `
  --whisper-model whisper-1 `
  --gpt-model gpt-4o-mini `
  --target-height 1920 `
  -o "outputs\short.mp4"
```

Not: `whisper-1`, kelime zaman damgaları için kullanılır. Çok uzun videolarda transkript prompt sınırına yaklaşırsa script ortayı kısaltarak baş ve son kısmı modele gönderir; daha profesyonel bir sürümde uzun videoları parça parça puanlatmak daha iyi sonuç verir.
