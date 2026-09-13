// app.js — Script globale per ArmiMarket Italia
// Funzioni di sicurezza e gestione sessione utente

// Sanitizzazione HTML sicura prima dell'inserimento nel DOM
window.escapeHtml = function(str) {
    if (str === null || str === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
};

// Funzione di logout globale
window.logout = function() {
    try {
        localStorage.removeItem("armimarket_token");
        localStorage.removeItem("armimarket_user");
        sessionStorage.clear();
    } catch(e) {}

    // Rimozione cookie di sessione/auth su tutti i possibili path e domini
    const pastDate = "Thu, 01 Jan 1970 00:00:00 GMT";
    document.cookie = "armimarket_token=; path=/; expires=" + pastDate + "; SameSite=Lax";
    document.cookie = "access_token=; path=/; expires=" + pastDate + "; SameSite=Lax";
    document.cookie = "token=; path=/; expires=" + pastDate + "; SameSite=Lax";
    try {
        const h = window.location.hostname;
        if (h) {
            document.cookie = "armimarket_token=; path=/; domain=" + h + "; expires=" + pastDate + "; SameSite=Lax";
            document.cookie = "armimarket_token=; path=/; domain=." + h + "; expires=" + pastDate + "; SameSite=Lax";
        }
    } catch(e) {}

    // Reset immediato visivo navbar
    const navAuth = document.getElementById("navAuthLinks");
    if (navAuth) {
        navAuth.innerHTML = `
            <a href="/login" class="text-xs text-[#4A4E44] hover:text-[#252821] px-2.5 py-1.5 rounded transition-colors uppercase tracking-wide font-semibold">
                Accedi
            </a>
            <a href="/registrati" class="text-xs px-3 py-1.5 rounded-lg font-bold transition-all uppercase tracking-wide"
               style="background:#F1EFE7;border:1px solid #68733F;color:#4F5A30;">
                Registrati
            </a>
        `;
    }

    // Chiamata facoltativa in background al server
    try {
        if (navigator.sendBeacon) {
            navigator.sendBeacon("/api/v1/auth/logout");
        } else {
            fetch("/api/v1/auth/logout", { method: "POST", keepalive: true }).catch(function(){});
        }
    } catch(e) {}

    // Reindirizzamento garantito a /logout per pulizia server e ricaricamento completo della pagina
    try {
        window.location.replace("/logout");
    } catch(e) {
        window.location.href = "/logout";
    }
};

// Global click delegation per qualsiasi pulsante o link di logout (intercetta in capture phase)
document.addEventListener("click", function(e) {
    const logoutTarget = e.target.closest("[data-action='logout'], .btn-logout, #btnLogout, #btnAdminLogout, #btnAdminPostaLogout, #btnProfileLogout, a[href='/logout']");
    if (logoutTarget) {
        e.preventDefault();
        e.stopPropagation();
        window.logout();
    }
}, true);

// Gestione stato autenticazione in Navbar
document.addEventListener("DOMContentLoaded", () => {
    const token = localStorage.getItem("armimarket_token");
    const rawUser = localStorage.getItem("armimarket_user");
    const navAuth = document.getElementById("navAuthLinks");
    if (token && rawUser && navAuth) {
        try {
            const u = JSON.parse(rawUser);
            let label = u.nickname || u.display_name || u.nome;
            if (u.ruolo === 'admin') {
                label = 'Admin';
            } else if (u.ruolo === 'armeria') {
                label = u.nickname || u.ragione_sociale || u.nome;
            }

            // Stile grafico in base al ruolo nel tema chiaro
            const roleStyle = u.ruolo === 'armeria'
                ? 'background:#EBEFE0;border:1px solid #68733F;color:#27471E;'
                : (u.ruolo === 'admin' ? 'background:#F7F3EA;border:1px solid #8C734B;color:#634D21;' : 'background:#EFF6FF;border:1px solid #93C5FD;color:#1E3A8A;');

            // Avatar mini: foto profilo se presente, altrimenti icona FontAwesome
            const avatarHtml = u.foto_profilo
                ? `<img src="${encodeURI(u.foto_profilo)}" class="w-6 h-6 rounded-full object-cover border border-stone-300" alt="avatar">`
                : `<i class="fa-solid ${u.ruolo === 'armeria' ? 'fa-store' : (u.ruolo === 'admin' ? 'fa-user-gear' : 'fa-user-shield')} text-[11px]"></i>`;

            const adminPostaBtn = (u.ruolo === 'admin') ? `
                <a href="/admin" class="text-xs font-bold flex items-center space-x-1.5 py-1 px-2.5 rounded-lg transition-all shadow uppercase tracking-wide"
                   style="background:#F1EFE7;border:1px solid #68733F;color:#4F5A30;" title="Dashboard Statistiche">
                    <i class="fa-solid fa-chart-pie"></i>
                    <span class="hidden sm:inline">Statistiche</span>
                </a>
                <a href="/admin/posta" class="text-xs font-bold flex items-center space-x-1.5 py-1 px-2.5 rounded-lg transition-all shadow uppercase tracking-wide"
                   style="background:#F1EFE7;border:1px solid #68733F;color:#4F5A30;" title="Casella Postale Amministratore">
                    <i class="fa-solid fa-envelope"></i>
                    <span class="hidden sm:inline">Posta</span>
                </a>
                <a href="/admin/utenti" class="text-xs font-bold flex items-center space-x-1.5 py-1 px-2.5 rounded-lg transition-all shadow uppercase tracking-wide"
                   style="background:#F1EFE7;border:1px solid #68733F;color:#4F5A30;" title="Gestione Account Utenti">
                    <i class="fa-solid fa-users-gear"></i>
                    <span class="hidden sm:inline">Utenti</span>
                </a>
            ` : '';

            navAuth.innerHTML = `
                ${adminPostaBtn}
                <a href="/profilo" class="text-xs font-bold flex items-center space-x-1.5 py-1 px-2 rounded-lg transition-all uppercase tracking-wide shadow-sm"
                   style="${roleStyle}" title="Area Personale">
                    ${avatarHtml}
                    <span class="max-w-[110px] truncate">${window.escapeHtml(label)}</span>
                </a>
                <a href="/logout" id="btnLogout" data-action="logout" class="btn-logout text-xs text-stone-500 hover:text-rose-600 ml-1 p-1 transition-colors cursor-pointer flex items-center justify-center" title="Esci dall'account">
                    <i class="fa-solid fa-right-from-bracket pointer-events-none"></i>
                </a>
            `;

        } catch(e) {
            console.error("Errore parsing utente da localStorage:", e);
        }
    }
});
