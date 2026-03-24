from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_html_email(
    host: str,
    port: int,
    user: str,
    password: str,
    sender: str,
    receivers: list[str],
    subject: str,
    html_body: str,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(receivers)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL(host, port) as server:
        server.login(user, password)
        server.sendmail(sender, receivers, msg.as_string())
