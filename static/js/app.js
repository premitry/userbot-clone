// ============================================================
// Global shared frontend helpers (P5 consolidation).
// Fungsi-fungsi ini dipakai lintas halaman. Definisi lokal di
// masing-masing template tetap berlaku (shadowing) sehingga aman
// backward-compatible; template baru cukup pakai versi global ini.
// ============================================================

// ===== Auth =====
async function logout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    } catch (e) {
        // ignore
    }
    // Fallback: hapus cookie di sisi klien.
    document.cookie = 'access_token=; Max-Age=0; path=/;';
    window.location.href = '/login';
}

// ===== HTML escape =====
if (typeof window.esc !== 'function') {
    window.esc = function (s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    };
}

// ===== Date formatting =====
if (typeof window.fmtDate !== 'function') {
    window.fmtDate = function (iso) {
        if (!iso) return '-';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '-';
        var p = function (n) { return (n < 10 ? '0' : '') + n; };
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
            ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    };
}

// ===== File size formatting =====
if (typeof window.fmtSize !== 'function') {
    window.fmtSize = function (bytes) {
        var n = Number(bytes);
        if (!n || n < 0) return '0 B';
        var units = ['B', 'KB', 'MB', 'GB', 'TB'];
        var i = 0;
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
        return (i === 0 ? n : n.toFixed(1)) + ' ' + units[i];
    };
}

// ===== Command-log status tag =====
if (typeof window.tagFor !== 'function') {
    window.tagFor = function (s) {
        if (s === 'success') return { cls: 'ok', label: 'OK' };
        if (s === 'failed') return { cls: 'err', label: 'ERR' };
        if (s === 'floodwait') return { cls: 'warn', label: 'WAIT' };
        if (s === 'no_permission') return { cls: 'warn', label: 'NOPERM' };
        return { cls: 'cmd', label: 'PEND' };
    };
}

// ===== Toast / notification =====
function showToast(message, type) {
    type = type || 'success';
    var toast = document.createElement('div');
    toast.className = 'fixed top-4 right-4 z-[100] px-4 py-3 text-sm font-medium animate-slide-in card ' +
        (type === 'success' ? 'text-green-400' : 'text-red-400');
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(function () {
        toast.style.opacity = '0';
        setTimeout(function () { toast.remove(); }, 300);
    }, 3000);
}
window.showToast = showToast;

// NOTE (P2): dulu ada setInterval(location.reload, 30000) di halaman
// dashboard. Itu double-refresh — dashboard.html sudah punya
// loadStats() via fetch tiap 15 detik. Full reload dihapus supaya
// tidak ada permintaan ganda & flicker.

console.log('⚡ Userbot Dashboard loaded');
