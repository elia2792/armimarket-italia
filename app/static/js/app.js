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
    localStorage.removeItem("armimarket_token");
    localStorage.removeItem("armimarket_user");
    // Rimozione eventuale cookie di preview se presente
    document.cookie = "armimarket_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    window.location.href = "/";
};

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

            // Stile grafico in base al ruolo
            const roleStyle = u.ruolo === 'armeria'
                ? 'color:#6ee7b7;border-color:#065f46'
                : (u.ruolo === 'admin' ? 'color:#c8a96e;border-color:#4a5c2a' : 'color:#93c5fd;border-color:#1e3a5f');

            // Avatar mini: foto profilo se presente, altrimenti icona FontAwesome
            const avatarHtml = u.foto_profilo
                ? `<img src="${encodeURI(u.foto_profilo)}" class="w-6 h-6 rounded-full object-cover border border-stone-600" alt="avatar">`
                : `<i class="fa-solid ${u.ruolo === 'armeria' ? 'fa-store' : (u.ruolo === 'admin' ? 'fa-user-gear' : 'fa-user-shield')} text-[11px]"></i>`;

            const adminPostaBtn = (u.ruolo === 'admin') ? `
                <a href="/admin/posta" class="text-xs font-bold flex items-center space-x-1.5 py-1 px-2.5 rounded-lg transition-all shadow uppercase tracking-wide"
                   style="background:#1a2010;border:1px solid #4a5c2a;color:#c8a96e;" title="Casella Postale Amministratore">
                    <i class="fa-solid fa-envelope"></i>
                    <span class="hidden sm:inline">Posta</span>
                </a>
                <a href="/admin/utenti" class="text-xs font-bold flex items-center space-x-1.5 py-1 px-2.5 rounded-lg transition-all shadow uppercase tracking-wide"
                   style="background:#1a2010;border:1px solid #4a5c2a;color:#c8a96e;" title="Gestione Account Utenti">
                    <i class="fa-solid fa-users-gear"></i>
                    <span class="hidden sm:inline">Utenti</span>
                </a>
            ` : '';

            navAuth.innerHTML = `
                ${adminPostaBtn}
                <a href="/profilo" class="text-xs font-bold flex items-center space-x-1.5 py-1 px-2 rounded-lg transition-all uppercase tracking-wide"
                   style="background:#0d1008;border:1px solid #2e3a18;${roleStyle}" title="Area Personale">
                    ${avatarHtml}
                    <span class="max-w-[110px] truncate">${window.escapeHtml(label)}</span>
                </a>
                <button onclick="logout()" class="text-[11px] text-stone-500 hover:text-rose-400 ml-1 p-1 transition-colors" title="Esci dall'account">
                    <i class="fa-solid fa-right-from-bracket"></i>
                </button>
            `;

        } catch(e) {
            console.error("Errore parsing utente da localStorage:", e);
        }
    }
});
