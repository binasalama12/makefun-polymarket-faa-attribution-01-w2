[![make.fun · polymarket-faa-attribution-01](https://make.fun/badge/polymarket-faa-attribution-01.svg)](https://make.fun/bounty/polymarket-faa-attribution-01?utm_source=github&utm_medium=readme&utm_campaign=polymarket-faa-attribution-01)
[![rank](https://make.fun/badge/polymarket-faa-attribution-01/binasalama12/makefun-polymarket-faa-attribution-01-w2/rank.svg)](https://make.fun/bounty/polymarket-faa-attribution-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=polymarket-faa-attribution-01)
[![reward](https://make.fun/badge/polymarket-faa-attribution-01/binasalama12/makefun-polymarket-faa-attribution-01-w2/reward.svg)](https://make.fun/bounty/polymarket-faa-attribution-01?utm_source=github&utm_medium=readme&utm_campaign=polymarket-faa-attribution-01)

# Lean EWMA forecaster (shrunk centre, 18h window)

Entry w2 (wallet `hazel-harbor-12`) untuk kompetisi
`polymarket-faa-attribution-01` di make.fun: memprediksi harga Yes tiap
market keluarga atribusi FAA, 240 menit ke depan, sebagai lima kuantil
(5%, 25%, 50%, 75%, 95%) per menit. Skor = mean pinball loss (lebih
rendah lebih baik); hadiah butuh kalahkan baseline house (0,363589 di
practice).

## Ide

Forecaster ramping yang sengaja sederhana: harga terakhir sebagai jangkar,
sedikit ditarik ke rata-rata 180 menit terakhir, ditambah drift empiris
yang diredam, dengan lebar interval dari volatilitas EWMA. Tidak ada
regime scaling — aturan yang sama dipakai saat pasar tenang maupun saat
lompat.

## Parameter (w2)

- **Window:** 1080 menit terakhir (18 jam); histori lebih lama diabaikan.
- **Centre:** `centre0 = 0,94 * x + 0,06 * mean180`, dengan `x` harga
  terakhir dan `mean180` rata-rata 180 menit terakhir.
- **Drift empiris:** `drift = 0,35 * (x - mean180) / 180` per menit,
  di-clamp ke ±0,0005/menit. Centre di horizon `h` adalah
  `centre0 + drift * h`, dievaluasi di anchor 1/5/15/30/60/120/240 lalu
  diinterpolasi linear antar anchor.
- **Sigma:** EWMA dari kuadrat perubahan harga 1-menit di window 1080,
  halflife 300 menit, floor 0,001, cap 0,004 (satuan harga per
  akar-menit). Kuantil: `q = clamp(centre(h) + z * sigma * sqrt(h), 0, 1)`
  dengan `z = (-1,644854; -0,67449; 0; 0,67449; 1,644854)`.
- Output dibulatkan 6 desimal dan dipaksa monoton per baris.

## Menjalankan

```sh
python3 main.py <case.json> [output.json]   # satu case; tanpa output -> stdout
# atau mode direktori (dipakai grader):
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13 stdlib saja, tanpa network, deterministik (tanpa random dan
tanpa jam). Satu case jalan <1 detik di mesin validasi, jauh di bawah
batas 8 detik.

## Validasi lokal

Dijalankan pada 6 practice case (`p00`–`p05`): semua output valid
(4 pasar per case di final; practice 19–24 pasar, 240 baris tiap pasar,
5 kuantil monoton dalam [0,1], 6 desimal), deterministik (byte-identik
pada 2 run), runtime 0,27–0,59 detik per case. Kit tidak menyertakan
file reference/answer, jadi skor practice dihitung dari harga aktual
case berikutnya (p01–p05 memuat 240 menit setelah checkpoint p00–p04):
mean pinball loss p00–p04 = **0,416083**, vs baseline house **0,392518**
pada subset yang sama (baseline penuh 6 case: 0,363589). Jadi varian ini
di practice masih di atas baseline — skor practice bukan panduan final,
dan varian ini tetap diajukan apa adanya sesuai parameter yang ditetapkan.

## Revisi

1. Seed variansi EWMA diubah dari 10 perubahan pertama (tertua) menjadi
   rata-rata kuadrat seluruh window — seed lama bisa didominasi satu
   lompatan 18 jam lalu.
2. Estimator drift diganti dari selisih dua window (mean 30 menit
   terakhir vs menit 180–210 lalu) menjadi kemiringan empiris
   `(x - mean180) / 180` yang berjangkar di checkpoint — lebih stabil
   pada harga bertangga. Keduanya menurunkan practice loss dari 0,438857
   ke 0,416083 (subset p00–p04).

## Lisensi

MIT — lihat `LICENSE`.
