# TCDD Koltuk Takibi

Bu proje şu aramayı GitHub Actions üzerinde otomatik kontrol eder:

- **Kalkış:** İzmit YHT
- **Varış:** Ankara Gar
- **Tarih:** 09.08.2026
- **Saat:** 17:02 ve sonrası
- **Sınıflar:** Ekonomi ve Business
- **Hariç:** Tekerlekli sandalye / engelli yolcu kontenjanı

Normal koltuk açıldığında Telegram mesajı gönderir.

## Kurulum

### 1. GitHub'da repository oluştur

1. GitHub'da sağ üstteki **+** düğmesine bas.
2. **New repository** seç.
3. Adını `tcdd-koltuk-takip` yap.
4. 5 dakikalık yoğun tarama için **Public** seçmek daha uygundur.
5. **Create repository** düğmesine bas.

Repository public olsa bile Telegram tokenı dosyalara yazılmaz; GitHub Secrets içinde saklanır.

### 2. Bu ZIP dosyasını yükle

ZIP'i bilgisayarında çıkar. GitHub repository sayfasında:

1. **Add file**
2. **Upload files**
3. Çıkardığın klasörün içindeki bütün dosyaları sürükle.
4. `.github/workflows/tcdd-check.yml` dosyasının da yüklendiğinden emin ol.
5. **Commit changes** düğmesine bas.

Windows bazen `.github` klasörünü sürüklerken sorun çıkarırsa, klasörü GitHub web arayüzünde elle oluştur:
`.github/workflows/tcdd-check.yml`

### 3. Telegram bilgilerini Secrets'a ekle

Repository içinde:

1. **Settings**
2. Sol menüden **Secrets and variables**
3. **Actions**
4. **New repository secret**

İki secret ekle:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Tokenı veya chat ID'yi kod dosyasına yazma.

### 4. Test et

1. Repository içinden **Actions** sekmesine gir.
2. Sol tarafta **TCDD Koltuk Takibi** seç.
3. **Run workflow** düğmesine bas.
4. **Sadece Telegram test bildirimi gönder** kutusunu işaretle.
5. Yeşil **Run workflow** düğmesine bas.

Telegram'a test mesajı geldiyse secret bilgileri doğrudur.

Ardından bir kez daha **Run workflow** çalıştır; bu kez test kutusunu işaretleme.
Bu çalışma TCDD sayfasını gerçekten kontrol eder.

## Çalışma düzeni

Workflow 3-9 Ağustos tarihleri arasında Türkiye saatine göre yaklaşık her 5 dakikada bir çalışır.
GitHub yoğunluğunda birkaç dakika gecikme olabilir.

Aynı boş koltuk durumu devam ediyorsa tekrar tekrar mesaj göndermez.
Koltuk kapanıp daha sonra yeniden açılırsa tekrar bildirir.

## Hata olursa

Actions sekmesinde kırmızı çalışmaya gir:

1. **TCDD'yi kontrol et** adımındaki hata metnine bak.
2. Sayfanın altındaki **Artifacts** bölümünden `tcdd-debug-...` dosyasını indir.
3. İçindeki `debug.png` ekran görüntüsü ve `debug.html` dosyası seçici sorununu gösterir.

TCDD sayfasının HTML yapısı değişirse `tcdd_monitor.py` içindeki seçicilerin güncellenmesi gerekebilir.

## Güvenlik

Bu bot bilet satın almaz, giriş yapmaz ve ödeme bilgisi kullanmaz.
Sadece normal Ekonomi/Business koltuk sayısını kontrol edip Telegram bildirimi gönderir.
