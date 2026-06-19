# GitHub'a Yükleme

Repo: https://github.com/nietzische-app/videocutter

## Yöntem 1: GitHub web arayüzü

1. Repo sayfasını açın.
2. `Add file` -> `Upload files` seçin.
3. Bu klasördeki dosyaları yükleyin.
4. `.env` dosyasını yüklemeyin. Sadece `.env.example` yüklenmeli.
5. Commit mesajı olarak örneğin `Add video cutter app` yazın.

Yüklenecek ana dosyalar:

- `app.py`
- `video_cutter.py`
- `requirements.txt`
- `README.md`
- `DEPLOY.md`
- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `.gitignore`
- `templates/index.html`
- `setup_and_run.ps1`
- `start_web_app.bat`

## Yöntem 2: Git kuruluysa

```bash
git clone https://github.com/nietzische-app/videocutter.git
cd videocutter
copy /Y "C:\Users\n.duman\Documents\Codex\2026-06-16\ben-python-ile-kendi-bilgisayar-mda\app.py" .
copy /Y "C:\Users\n.duman\Documents\Codex\2026-06-16\ben-python-ile-kendi-bilgisayar-mda\video_cutter.py" .
copy /Y "C:\Users\n.duman\Documents\Codex\2026-06-16\ben-python-ile-kendi-bilgisayar-mda\requirements.txt" .
copy /Y "C:\Users\n.duman\Documents\Codex\2026-06-16\ben-python-ile-kendi-bilgisayar-mda\README.md" .
copy /Y "C:\Users\n.duman\Documents\Codex\2026-06-16\ben-python-ile-kendi-bilgisayar-mda\DEPLOY.md" .
copy /Y "C:\Users\n.duman\Documents\Codex\2026-06-16\ben-python-ile-kendi-bilgisayar-mda\Dockerfile" .
copy /Y "C:\Users\n.duman\Documents\Codex\2026-06-16\ben-python-ile-kendi-bilgisayar-mda\docker-compose.yml" .
copy /Y "C:\Users\n.duman\Documents\Codex\2026-06-16\ben-python-ile-kendi-bilgisayar-mda\.env.example" .
copy /Y "C:\Users\n.duman\Documents\Codex\2026-06-16\ben-python-ile-kendi-bilgisayar-mda\.gitignore" .
xcopy /E /I /Y "C:\Users\n.duman\Documents\Codex\2026-06-16\ben-python-ile-kendi-bilgisayar-mda\templates" templates
git add .
git commit -m "Add video cutter app"
git push origin main
```

Repo'nun varsayılan branch'i `main` değilse son komutta branch adını değiştirin.
