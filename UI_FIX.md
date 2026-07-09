# UI Fix - Remove Support Short Amount Toggle

**File:** templates/settings.html

## Perubahan yang harus dilakukan:

Hapus blok toggle "Support Short Amount":

```html
<label class="us-check">
    <input type="checkbox" id="r-short">
    <span class="t"><b>Support Short Amount</b><span>Izinkan format 5k, 10k, 25rb, 1jt selain angka penuh (5000).</span></span>
</label>
```

Update teks Enable Dynamic Amount menjadi:

```html
<span class="t"><b>Enable Dynamic Amount</b><span>Aktifkan /qris 10000 (angka penuh only). Short format sudah tidak didukung lagi.</span></span>
```

Hapus / comment baris JavaScript yang masih referensi `r-short` dan `qris_support_short`.

Setelah perubahan, restart/reload aplikasi.

---

**Status:** Backend sudah strict. Toggle di UI sekarang hanya cosmetic dan tidak berpengaruh.
**Commit ini:** Cleanup note untuk UI.
