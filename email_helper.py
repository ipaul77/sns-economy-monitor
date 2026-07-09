import smtplib
from email.mime.text import MIMEText
from email.header import Header

def send_email(smtp_config: dict, recipient: str, subject: str, body: str) -> bool:
    """
    Sends an email using the provided SMTP configuration.
    Returns True if successful, raises an Exception if failed.
    """
    if not smtp_config:
        raise ValueError("SMTP configuration is empty.")
        
    server_addr = smtp_config.get("server")
    port = smtp_config.get("port", 587)
    sender_email = smtp_config.get("email")
    password = smtp_config.get("password")
    
    if not all([server_addr, port, sender_email, password]):
        raise ValueError("SMTP settings (server, port, email, password) are not fully configured.")
        
    # Create text message
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = sender_email
    msg["To"] = recipient
    
    # Establish connection and send email
    try:
        print(f"[Email Helper] Connecting to SMTP server {server_addr}:{port}...")
        server = smtplib.SMTP(server_addr, port)
        server.ehlo()
        server.starttls()  # Secure connection via TLS
        server.ehlo()
        
        print(f"[Email Helper] Logging in as {sender_email}...")
        server.login(sender_email, password)
        
        print(f"[Email Helper] Sending email to {recipient}...")
        server.sendmail(sender_email, [recipient], msg.as_string())
        server.quit()
        print("[Email Helper] Email sent successfully.")
        return True
    except Exception as e:
        print(f"[Error] SMTP Email sending failed: {str(e)}")
        raise e
