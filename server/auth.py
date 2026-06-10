"""
邮箱验证码登录 + JWT 鉴权模块。

流程：
  1. POST /api/auth/send-code  — {email} → 发送6位验证码到邮箱
  2. POST /api/auth/verify-code — {email, code} → 返回JWT
  3. GET  /api/auth/me           — Authorization: Bearer <token> → 用户信息

依赖：PyJWT, smtplib（Python内置）
"""

import os
import time
import random
import smtplib
import hashlib
from email.mime.text import MIMEText
from email.header import Header

import jwt

# ── 配置（从环境变量读取）──
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production-" + os.urandom(8).hex())
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "72"))  # JWT 有效期 72 小时
CODE_EXPIRE_SEC = 300  # 验证码有效期 5 分钟

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)  # 发件人，默认同 SMTP_USER

# ── 内存存储（生产环境切换为 SQLite/Redis）──
_pending_codes: dict[str, tuple[str, float]] = {}  # email → (code, expires_at)
_verified_users: dict[str, dict] = {}                # email → user_info


def _make_jwt(email: str) -> str:
    """签发 JWT。"""
    payload = {
        "sub": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRE_HOURS * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _decode_jwt(token: str) -> dict | None:
    """验证 JWT，成功返回 payload，失败返回 None。"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None


def send_verification_code(email: str) -> str | None:
    """生成6位验证码并通过 SMTP 发送。成功返回 success message，失败返回 None。"""
    code = f"{random.randint(0, 999999):06d}"
    expires_at = time.time() + CODE_EXPIRE_SEC
    _pending_codes[email] = (code, expires_at)

    if not SMTP_USER or not SMTP_PASS:
        # 本地开发模式：SMTP 未配置，返回验证码给前端显示
        print(f"[DEV MODE] 验证码已发送到 {email}: {code}")
        return code

    subject = "消字号合规预审 - 登录验证码"
    body = f"""您的登录验证码是：{code}

有效期 5 分钟。如非本人操作请忽略此邮件。

---
消字号合规预审引擎
"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = SMTP_FROM
    msg["To"] = email

    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_FROM, [email], msg.as_string())
        server.quit()
        return "ok"
    except smtplib.SMTPAuthenticationError:
        del _pending_codes[email]
        print(f"[SMTP] 认证失败 — 请检查 SMTP_USER/SMTP_PASS，QQ邮箱需使用授权码而非登录密码")
        return None
    except smtplib.SMTPConnectError as e:
        del _pending_codes[email]
        print(f"[SMTP] 连接失败 {SMTP_HOST}:{SMTP_PORT} — {e}")
        return None
    except Exception as e:
        del _pending_codes[email]
        print(f"[SMTP] 发送失败: {type(e).__name__}: {e}")
        return None


def verify_code(email: str, code: str) -> str | None:
    """校验验证码，成功返回 JWT，失败返回 None。"""
    pending = _pending_codes.get(email)
    if not pending:
        return None
    stored_code, expires_at = pending
    if time.time() > expires_at:
        del _pending_codes[email]
        return None
    if stored_code != code.strip():
        return None
    # 验证通过，清除验证码，记录用户
    del _pending_codes[email]
    _verified_users[email] = {"email": email, "login_at": int(time.time())}
    return _make_jwt(email)


def get_user_from_token(token: str) -> dict | None:
    """从 JWT 获取用户信息。"""
    payload = _decode_jwt(token)
    if not payload:
        return None
    email = payload.get("sub", "")
    return {"email": email}
