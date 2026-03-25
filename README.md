# LitSearch — Academic Literature Scanner

Akademik literatürü otomatik tarayan, sonuçları e-posta olarak gönderen bir masaüstü uygulaması.

## Özellikler

- **10 Yayıncı** desteği: ACS, Wiley, RSC, Elsevier, Springer, Taylor & Francis, SAGE, Nature, Science, Palgrave
- **CrossRef API** ile gerçek zamanlı arama
- **OR / AND** anahtar kelime modu
- Tarih aralığı ve maksimum sonuç sayısı ayarı
- Sonuçları **HTML + düz metin e-posta** olarak Gmail ile gönderme
- Sade ve kullanımı kolay **tkinter GUI**

## Kurulum

```bash
pip install requests
```

> `tkinter` Python ile birlikte gelir, ayrıca kurulum gerekmez.

## Kullanım

```bash
python app.py
```

1. Gmail adresinizi ve [App Password](https://myaccount.google.com/apppasswords) bilgilerinizi girin
2. Anahtar kelimeleri virgülle ayırarak yazın (örn: `biobased, renewable, sustainable`)
3. Taranacak yayıncıları seçin
4. **TARAMAYI BAŞLAT** butonuna tıklayın

## Gmail App Password

Gmail SMTP kullanmak için normal şifre yerine **16 haneli App Password** gereklidir:

1. [myaccount.google.com](https://myaccount.google.com) → Güvenlik
2. 2 Adımlı Doğrulama → Uygulama Şifreleri
3. Oluşturulan 16 haneli şifreyi kullanın
