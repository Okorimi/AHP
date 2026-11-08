"""Envoi du rapport par e-mail avec smtplib et email.mime."""
from __future__ import annotations

import smtplib
import socket
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid


class MailError(Exception):
    """Erreur d'envoi, avec un message directement affichable à l'utilisateur."""


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    sender: str
    security: str  # "starttls", "ssl" ou "none"

    @classmethod
    def from_mapping(cls, values: Mapping) -> "SmtpConfig | None":
        host = str(values.get("host", "")).strip()
        if not host:
            return None
        port = int(values.get("port", 587))
        username = str(values.get("username", "")).strip()
        password = str(values.get("password", ""))
        if "gmail" in host.lower():
            password = password.replace(" ", "")  # Google affiche ses mots de passe par blocs
        sender = str(values.get("sender", username)).strip()
        if not sender:
            return None
        security = str(values.get("security", "ssl" if port == 465 else "starttls")).lower()
        return cls(host, port, username, password, sender, security)


def compose_message(
    sender: str, recipient: str, subject: str, text: str, html: str, pdf: bytes, filename: str,
) -> MIMEMultipart:
    message = MIMEMultipart("mixed")
    message["From"] = formataddr(("Sélection AHP", sender))
    message["To"] = recipient
    message["Subject"] = Header(" ".join(subject.split()), "utf-8")
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1])

    body = MIMEMultipart("alternative")
    body.attach(MIMEText(text, "plain", "utf-8"))
    body.attach(MIMEText(html, "html", "utf-8"))
    message.attach(body)

    attachment = MIMEApplication(pdf, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=filename)
    message.attach(attachment)
    return message


def send_message(config: SmtpConfig, message: MIMEMultipart, recipient: str) -> None:
    context = ssl.create_default_context()
    try:
        if config.security == "ssl":
            server = smtplib.SMTP_SSL(config.host, config.port, timeout=25, context=context)
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=25)
        with server:
            if config.security == "starttls":
                server.starttls(context=context)
            if config.username:
                server.login(config.username, config.password)
            server.sendmail(config.sender, [recipient], message.as_string())
    except smtplib.SMTPAuthenticationError as error:
        raise MailError(
            "Le serveur d'e-mail a refusé la connexion. Vérifiez l'identifiant et le mot de passe "
            "SMTP ; avec Gmail, utilisez un mot de passe d'application."
        ) from error
    except smtplib.SMTPRecipientsRefused as error:
        raise MailError(f"Le serveur a refusé le destinataire {recipient}.") from error
    except (socket.timeout, TimeoutError, ConnectionError, socket.gaierror) as error:
        raise MailError(
            f"Impossible de joindre le serveur {config.host}:{config.port}. "
            "Vérifiez l'adresse, le port et la connexion Internet."
        ) from error
    except (smtplib.SMTPException, ssl.SSLError, OSError) as error:
        raise MailError(f"L'envoi a échoué : {error}") from error
