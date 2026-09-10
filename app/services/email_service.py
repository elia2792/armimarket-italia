import asyncio
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.email_log import EmailLog, TipologiaEmail


class EmailService:
    @staticmethod
    def _send_smtp_email_sync(to_email: str, subject: str, html_body: str, text_body: str) -> Tuple[bool, Optional[str]]:
        """Invia email tramite SMTP standard sincrono. Ritorna (successo, eventuale_errore)."""
        if not settings.SMTP_HOST:
            # SMTP non configurato: registriamo nei log di console
            print(f"--- [EMAIL SERVICE: SMTP non configurato] Destinatario: {to_email} ---")
            print(f"Oggetto: {subject}")
            print(f"Corpo del messaggio:\n{text_body}")
            print("----------------------------------------------------------------------")
            return False, "SMTP_HOST non configurato nel file .env (Email registrata nella Webmail locale)"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
        msg["To"] = to_email

        part1 = MIMEText(text_body, "plain", "utf-8")
        part2 = MIMEText(html_body, "html", "utf-8")
        msg.attach(part1)
        msg.attach(part2)

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                if settings.SMTP_TLS:
                    server.starttls()
                if settings.SMTP_USER and settings.SMTP_PASSWORD:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.EMAILS_FROM_EMAIL, [to_email], msg.as_string())
            print(f"[EMAIL SERVICE] Email inviata con successo via SMTP a: {to_email}")
            return True, None
        except Exception as e:
            err_msg = str(e)
            print(f"[EMAIL SERVICE ERROR] Impossibile inviare email via SMTP a {to_email}: {err_msg}")
            return False, err_msg

    @classmethod
    async def log_and_send_email(
        cls,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        tipologia: str = TipologiaEmail.SISTEMA.value,
        link_azione: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        from_email: Optional[str] = None
    ) -> bool:
        """Invia l email (se SMTP attivo) e ne registra la copia su database per la casella postale dell amministratore."""
        sender = from_email or f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
        
        loop = asyncio.get_running_loop()
        success, error = await loop.run_in_executor(
            None,
            cls._send_smtp_email_sync,
            to_email,
            subject,
            html_body,
            text_body
        )

        if db is not None:
            log_entry = EmailLog(
                mittente=sender,
                destinatario=to_email,
                oggetto=subject,
                corpo_html=html_body,
                corpo_testo=text_body,
                tipologia=tipologia,
                inviata=success,
                errore=error,
                link_azione=link_azione
            )
            db.add(log_entry)
            await db.commit()
            await db.refresh(log_entry)

        return success

    @classmethod
    async def send_password_reset_email(
        cls,
        to_email: str,
        reset_link: str,
        db: Optional[AsyncSession] = None
    ) -> bool:
        """Invia e memorizza l email con il link crittografico di reimpostazione password."""
        subject = "Recupero Credenziali - ArmiMarket Italia"
        
        if reset_link.startswith("/"):
            full_link = f"{settings.BASE_URL.rstrip('/')}{reset_link}"
        else:
            full_link = reset_link

        text_body = (
            f"Gentile utente,\n\n"
            f"Hai richiesto la reimpostazione della tua password su ArmiMarket Italia.\n"
            f"Clicca sul seguente link (o incollalo nel tuo browser) entro 30 minuti:\n\n"
            f"{full_link}\n\n"
            f"Se non hai richiesto tu il ripristino, ignora questo messaggio. Il tuo account rimarrà al sicuro.\n\n"
            f"ArmiMarket Italia - Bacheca Motore di Ricerca Armi & Tiro"
        )

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
                .container {{ max-width: 560px; margin: 0 auto; background-color: #020617; border: 1px solid #1e293b; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
                .header {{ background-color: #0f172a; padding: 24px; border-bottom: 1px solid #1e293b; text-align: center; }}
                .logo {{ font-size: 20px; font-weight: 900; color: #ffffff; letter-spacing: -0.5px; }}
                .logo span {{ color: #f59e0b; }}
                .content {{ padding: 32px 24px; }}
                h2 {{ color: #ffffff; font-size: 18px; margin-top: 0; }}
                p {{ color: #94a3b8; font-size: 14px; line-height: 1.6; margin: 16px 0; }}
                .btn-container {{ text-align: center; margin: 28px 0; }}
                .btn {{ display: inline-block; background-color: #d97706; color: #020617 !important; font-weight: 800; font-size: 14px; text-decoration: none; padding: 12px 28px; border-radius: 10px; }}
                .link-alt {{ font-size: 11px; color: #64748b; word-break: break-all; margin-top: 20px; }}
                .footer {{ background-color: #020617; padding: 20px 24px; border-top: 1px solid #1e293b; font-size: 11px; color: #64748b; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">ArmiMarket <span>Italia</span></div>
                    <div style="font-size: 11px; color: #94a3b8; margin-top: 2px;">Bacheca Motore di Ricerca Armi & Tiro</div>
                </div>
                <div class="content">
                    <h2>Reimposta la tua Password</h2>
                    <p>Hai richiesto il recupero della password per l account associato a <strong>{to_email}</strong>.</p>
                    <p>Per procedere e scegliere una nuova password, clicca sul pulsante sottostante. Il link rimarrà valido per i prossimi <strong>30 minuti</strong>:</p>
                    <div class="btn-container">
                        <a href="{full_link}" class="btn" target="_blank">Reimposta Password Ora</a>
                    </div>
                    <p class="link-alt">Se il pulsante non funziona, copia e incolla questo link nel tuo browser:<br><a href="{full_link}" style="color: #f59e0b;">{full_link}</a></p>
                    <p style="margin-top: 24px; font-size: 12px; color: #64748b;">Se non sei stato tu a richiedere il recupero, puoi ignorare in tutta sicurezza questa email: la tua attuale password non verrà modificata.</p>
                </div>
                <div class="footer">
                    &copy; 2026 ArmiMarket Italia &bull; Conformità di Pubblica Sicurezza T.U.L.P.S. & D.Lgs. 104/2018
                </div>
            </div>
        </body>
        </html>
        """

        return await cls.log_and_send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            tipologia=TipologiaEmail.RECUPERO_PASSWORD.value,
            link_azione=full_link,
            db=db
        )

    @classmethod
    async def send_contact_request_email(
        cls,
        to_email: str,
        buyer_nome: str,
        buyer_email: str,
        titolo_polizia: str,
        messaggio: str,
        annuncio_titolo: str,
        annuncio_id: int,
        db: Optional[AsyncSession] = None
    ) -> bool:
        """Invia notifica di richiesta informazioni dall acquirente al venditore, registrandola nel log di moderazione."""
        subject = f"Nuovo messaggio per: {annuncio_titolo} - ArmiMarket Italia"
        ad_url = f"{settings.BASE_URL.rstrip('/')}/scheda/{annuncio_id}"

        text_body = (
            f"Gentile Inserzionista,\n\n"
            f"Hai ricevuto una richiesta di contatto per l annuncio: {annuncio_titolo} (#{annuncio_id})\n\n"
            f"Dati del richiedente:\n"
            f"- Nome: {buyer_nome}\n"
            f"- Email: {buyer_email}\n"
            f"- Titolo di Polizia dichiarato: {titolo_polizia}\n\n"
            f"Messaggio:\n{messaggio}\n\n"
            f"Dettaglio annuncio: {ad_url}\n\n"
            f"AVVISO T.U.L.P.S.: La compravendita di armi non può avvenire a distanza. "
            f"Verifica personalmente il titolo di polizia dell acquirente prima di qualunque cessione.\n"
            f"ArmiMarket Italia"
        )

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
                .container {{ max-width: 580px; margin: 0 auto; background-color: #020617; border: 1px solid #1e293b; border-radius: 16px; overflow: hidden; }}
                .header {{ background-color: #0f172a; padding: 20px; border-bottom: 1px solid #1e293b; }}
                .logo {{ font-size: 18px; font-weight: 900; color: #ffffff; }}
                .content {{ padding: 24px; }}
                .box {{ background-color: #0f172a; border: 1px solid #334155; border-radius: 12px; padding: 16px; margin: 16px 0; }}
                .tulps {{ background-color: #451a03; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 8px; font-size: 12px; color: #fef3c7; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">ArmiMarket <span style="color:#f59e0b">Italia</span> &bull; Richiesta di Contatto</div>
                </div>
                <div class="content">
                    <p style="color:#94a3b8; font-size: 14px;">Hai ricevuto un messaggio per il tuo annuncio <strong><a href="{ad_url}" style="color:#f59e0b;">{annuncio_titolo}</a></strong>:</p>
                    
                    <div class="box">
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;"><strong>Mittente:</strong> {buyer_nome} (&lt;a href="mailto:{buyer_email}" style="color:#38bdf8;"&gt;{buyer_email}&lt;/a&gt;)</div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 12px;"><strong>Titolo Polizia dichiarato:</strong> <span style="color:#10b981; font-weight: bold;">{titolo_polizia}</span></div>
                        <div style="font-size: 13px; color: #f8fafc; white-space: pre-wrap; background: #020617; padding: 12px; border-radius: 8px; border: 1px solid #1e293b;">{messaggio}</div>
                    </div>

                    <div class="tulps">
                        <strong>AVVISO DI PUBBLICA SICUREZZA (T.U.L.P.S.):</strong> 
                        Accerta di persona l identità dell acquirente e la validità del porto d armi o titolo abilitativo prima della consegna materiale dell arma.
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

        return await cls.log_and_send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            tipologia=TipologiaEmail.RICHIESTA_CONTATTO.value,
            link_azione=ad_url,
            db=db
        )

    @classmethod
    async def send_test_email(
        cls,
        to_email: str,
        db: Optional[AsyncSession] = None
    ) -> bool:
        """Invia un email di prova per verificare la corretta connessione SMTP dal pannello di amministrazione."""
        subject = "Test Invio Email - ArmiMarket Italia Webmail"
        text_body = (
            f"Questa è un email di test generata dalla casella postale amministratore di ArmiMarket Italia.\n"
            f"Se la ricevi, la configurazione SMTP del server funziona correttamente!"
        )
        html_body = f"""
        <div style="font-family: sans-serif; background: #020617; color: #f8fafc; padding: 24px; border-radius: 12px;">
            <h2 style="color: #f59e0b;">ArmiMarket Italia &bull; Test di Connettività</h2>
            <p>Questa email conferma che il motore di posta elettronica è operativo e collegato al server.</p>
            <p style="color: #94a3b8; font-size: 12px;">Data e ora del test: generato dal pannello di amministrazione.</p>
        </div>
        """
        return await cls.log_and_send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            tipologia=TipologiaEmail.TEST.value,
            db=db
        )

    @classmethod
    async def send_report_notification_to_admin(
        cls,
        annuncio_id: int,
        annuncio_titolo: str,
        motivo: str,
        dettagli: str,
        email_segnalatore: Optional[str] = None,
        db: Optional[AsyncSession] = None
    ) -> bool:
        """Invia notifica di annuncio segnalato alla casella amministratore."""
        subject = f"[SEGNALAZIONE] Annuncio #{annuncio_id} - Motivo: {motivo}"
        text_body = (
            f"Nuova segnalazione pervenuta per l'annuncio #{annuncio_id} ('{annuncio_titolo}'):\n\n"
            f"Motivo: {motivo}\n"
            f"Dettagli: {dettagli}\n"
            f"Email segnalatore: {email_segnalatore or 'Anonimo'}\n\n"
            f"Accedi al pannello amministratore per rimuovere o archiviare l'annuncio."
        )
        html_body = f"""
        <div style="font-family: sans-serif; background: #020617; color: #f8fafc; padding: 24px; border-radius: 12px; border: 1px solid #ef4444;">
            <h3 style="color: #ef4444; margin-top: 0;">⚠️ Annuncio Segnalato per Non Conformità</h3>
            <p><strong>Annuncio:</strong> #{annuncio_id} - {annuncio_titolo}</p>
            <p><strong>Motivo:</strong> <span style="color: #f59e0b;">{motivo}</span></p>
            <p><strong>Dettagli:</strong></p>
            <blockquote style="background: #0f172a; padding: 12px; border-left: 4px solid #ef4444; border-radius: 4px; margin: 8px 0; color: #cbd5e1;">{dettagli}</blockquote>
            <p style="font-size: 13px; color: #94a3b8;">Segnalatore: {email_segnalatore or 'Utente Anonimo'}</p>
            <p style="margin-top: 20px;"><a href="/admin/posta" style="background: #ef4444; color: #ffffff; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: bold;">Gestisci Segnalazioni</a></p>
        </div>
        """
        return await cls.log_and_send_email(
            to_email=settings.ADMIN_EMAIL,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            tipologia=TipologiaEmail.SEGNALAZIONE.value,
            link_azione=f"/annunci/{annuncio_id}",
            db=db
        )

    @classmethod
    async def send_admin_reply_email(
        cls,
        to_email: str,
        subject: str,
        reply_message: str,
        original_subject: Optional[str] = None,
        db: Optional[AsyncSession] = None
    ) -> bool:
        """Invia una risposta ufficiale dall'amministratore (mittente anonimo 'Admin ArmiMarket Italia')."""
        subj = subject if subject.startswith("Re:") else f"Re: {subject}"
        text_body = (
            f"Gentile utente,\n\n"
            f"{reply_message}\n\n"
            f"---\n"
            f"Amministrazione ArmiMarket Italia\n"
            f"https://armimarket.it"
        )
        html_body = f"""
        <div style="font-family: sans-serif; background: #020617; color: #f8fafc; padding: 24px; border-radius: 12px; border: 1px solid #1e293b;">
            <div style="font-size: 18px; font-weight: 900; color: #ffffff; margin-bottom: 16px;">
                ArmiMarket <span style="color: #f59e0b;">Italia</span> &bull; Risposta Amministratore
            </div>
            <div style="background: #0f172a; padding: 16px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 16px; white-space: pre-wrap; color: #e2e8f0; font-size: 14px; line-height: 1.6;">
{reply_message}
            </div>
            <p style="font-size: 12px; color: #64748b; margin-top: 20px;">
                Questa è una risposta ufficiale inviata dall'Amministrazione del portale ArmiMarket Italia in merito alla tua richiesta.
            </p>
        </div>
        """
        return await cls.log_and_send_email(
            to_email=to_email,
            subject=subj,
            html_body=html_body,
            text_body=text_body,
            tipologia=TipologiaEmail.RISPOSTA_ADMIN.value,
            db=db
        )

