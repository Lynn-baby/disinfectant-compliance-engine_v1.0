"""
合规预审引擎 FastAPI 服务。

端点:
  POST /api/preaudit   — 文本直接提交，触发 S0→S7 全流程
  POST /api/upload     — 上传产品标签文件，OCR → S0→S7 全流程
  GET  /api/health     — 健康检查

启动:
  cd /Users/ml/Desktop/ai_sale_agent001 && python -m uvicorn server.main:app --reload
"""

import os
import sys
import json
import time
import tempfile
from collections import defaultdict
from pathlib import Path

# 项目根目录加入 path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 加载 .env 文件（不依赖 python-dotenv）
_env_path = os.path.join(_PROJECT_ROOT, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from server.pipeline import preaudit, PipelineResult
from server.ocr_service import process_file
from server.quota_store import get_used, increment as quota_increment, reset as quota_reset

# ═══════════════════════════════════════════════════
# 安全配置
# ═══════════════════════════════════════════════════

MAX_UPLOAD_SIZE = 10 * 1024 * 1024   # 10MB
MAX_BODY_SIZE = 10 * 1024             # 10KB
RATE_LIMIT_WINDOW = 60                # 秒
RATE_LIMIT_MAX = 5                    # 每窗口最多 5 次
FREE_QUOTA_TOTAL = 3                  # 每个 IP 免费报告总次数

_rate_log: dict[str, list[float]] = defaultdict(list)
_LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}
ADMIN_KEY = os.getenv("ADMIN_KEY", "")


def _is_localhost(client_ip: str) -> bool:
    return client_ip in _LOCALHOST_IPS


def _get_jwt_email(request: Request | None) -> str | None:
    """从 Authorization 头提取 JWT 并返回用户邮箱。"""
    if not request:
        return None
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    from server.auth import _decode_jwt
    payload = _decode_jwt(auth[7:])
    return payload.get("sub") if payload else None


def _has_admin_key(request: Request | None) -> bool:
    """检查请求是否携带有效的 admin key（不检查登录状态）。"""
    if not ADMIN_KEY or not request:
        return False
    if request.headers.get("X-Admin-Key") == ADMIN_KEY:
        return True
    if request.query_params.get("key") == ADMIN_KEY:
        return True
    return False


def _is_admin(request: Request | None) -> bool:
    """检查请求是否拥有管理员权限。
    条件（满足任一即可）：
    - localhost 访问（开发环境）
    - 已登录（有效 JWT）+ 携带正确的 admin key（生产环境，双重校验）
    """
    if not request:
        return False
    if _is_localhost(request.client.host if request.client else ""):
        return True
    # 生产环境：必须登录 + admin key 同时满足
    if _has_admin_key(request) and _get_jwt_email(request):
        return True
    return False


def _check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    _rate_log[client_ip] = [t for t in _rate_log[client_ip] if t > cutoff]
    if len(_rate_log[client_ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_log[client_ip].append(now)
    return True


def _get_quota(client_ip: str, *, is_admin: bool = False) -> dict:
    """返回当前 IP 的配额信息。localhost 或 admin key 返回无限配额。"""
    if is_admin or _is_localhost(client_ip):
        return {"total": 999, "used": 0, "remaining": 999}
    used = get_used(client_ip)
    return {
        "total": FREE_QUOTA_TOTAL,
        "used": used,
        "remaining": max(0, FREE_QUOTA_TOTAL - used),
    }


def _consume_quota(client_ip: str, *, is_admin: bool = False) -> bool:
    """尝试消耗一次配额。localhost 或 admin key 永不限制。"""
    if is_admin or _is_localhost(client_ip):
        return True
    used = get_used(client_ip)
    if used >= FREE_QUOTA_TOTAL:
        return False
    quota_increment(client_ip)
    return True

# ═══════════════════════════════════════════════════

app = FastAPI(
    title="消字号合规预审引擎",
    description="消毒产品合规预审 API — 支持文本提交和文件上传（PDF/图片）",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求体大小限制中间件
@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        length = int(content_length)
        path = request.url.path
        if path == "/api/upload" and length > MAX_UPLOAD_SIZE:
            return JSONResponse(status_code=413, content={"success": False, "error": f"文件过大，最大 {MAX_UPLOAD_SIZE // (1024*1024)}MB"})
        if path == "/api/preaudit" and length > MAX_BODY_SIZE:
            return JSONResponse(status_code=413, content={"success": False, "error": f"请求体过大，最大 {MAX_BODY_SIZE // 1024}KB"})
    return await call_next(request)


@app.get("/api/health")
async def health():
    """健康检查。"""
    return {
        "status": "ok",
        "service": "消字号合规预审引擎",
        "version": "1.0.0",
    }


@app.get("/api/quota")
async def check_quota(request: Request):
    """查询当前 IP 的免费配额剩余次数。admin key 返回无限配额。"""
    client_ip = request.client.host if request.client else "unknown"
    return _get_quota(client_ip, is_admin=_is_admin(request))


@app.post("/api/quota/reset")
async def reset_quota(request: Request):
    """重置当前 IP 的免费配额（调试用）。"""
    client_ip = request.client.host if request.client else "unknown"
    quota_reset(client_ip)
    return {"message": "配额已重置", "quota": _get_quota(client_ip)}


@app.post("/api/preaudit")
async def preaudit_text(payload: dict, request: Request):
    """文本直接提交 — 跳过 OCR，直接跑合规预审。消耗一次免费配额。"""
    client_ip = request.client.host if request.client else "unknown"
    admin = _is_admin(request)
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    if not _consume_quota(client_ip, is_admin=admin):
        quota = _get_quota(client_ip, is_admin=admin)
        raise HTTPException(
            status_code=403,
            detail=f"免费配额已用完（{quota['used']}/{quota['total']}），请付费获取完整报告"
        )

    user_input = payload.get("user_input", "") or payload.get("product_name", "")
    result = await preaudit(payload, user_input=user_input)

    return {
        "success": result.success,
        "blocked": result.blocked,
        "block_reason": result.block_reason,
        "report": result.markdown_report,
        "summary": json.loads(result.summary_json) if result.summary_json else {},
        "stages": {
            k: _serialize_stage(v) for k, v in result.stages.items()
        },
        "error": result.error,
        "quota": _get_quota(client_ip, is_admin=admin),
    }


@app.post("/api/upload")
async def preaudit_upload(file: UploadFile = File(...), request: Request = None):
    """上传产品标签文件 — OCR 解析后跑合规预审。最大 10MB。消耗一次免费配额。"""
    client_ip = request.client.host if request and request.client else "unknown"
    admin = _is_admin(request)
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    if not _consume_quota(client_ip, is_admin=admin):
        quota = _get_quota(client_ip, is_admin=admin)
        raise HTTPException(
            status_code=403,
            detail=f"免费配额已用完（{quota['used']}/{quota['total']}），请付费获取完整报告"
        )

    allowed_extensions = {'.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff'}
    ext = Path(file.filename).suffix.lower() if file.filename else ""

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}，仅支持 PDF/PNG/JPG"
        )

    # 保存上传文件到临时目录
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        # OCR 解析
        ocr_result = process_file(tmp_path)

        if not ocr_result["success"]:
            return JSONResponse(
                status_code=422,
                content={
                    "success": False,
                    "error": ocr_result.get("error", "OCR 解析失败"),
                    "raw_text": ocr_result.get("raw_text", ""),
                }
            )

        # 用 OCR 结果构造产品信息 → 跑流水线
        raw_text = ocr_result["raw_text"]
        ingredients = "、".join(ocr_result["ingredients"][:20])  # 取前 20 个
        claims = "、".join(ocr_result["claims"])

        # 从 OCR 文本中提取产品名（取前几行中文内容作为候选），避免文件名含英文被 S2 拒绝
        product_name = _extract_product_name(raw_text, file.filename)

        product_info = {
            "product_name": product_name,
            "dosage_form": "液体",
            "main_ingredients": ingredients or "待人工确认",
            "target_claims": claims,
            "domestic_or_imported": "国产",
            "customer_type": "品牌方",
            "urgency_level": "普通",
        }

        pipeline_result = await preaudit(product_info, user_input=raw_text)

        return {
            "success": pipeline_result.success,
            "ocr": ocr_result,
            "blocked": pipeline_result.blocked,
            "block_reason": pipeline_result.block_reason,
            "report": pipeline_result.markdown_report,
            "summary": json.loads(pipeline_result.summary_json) if pipeline_result.summary_json else {},
            "stages": {
                k: _serialize_stage(v) for k, v in pipeline_result.stages.items()
            },
            "error": pipeline_result.error,
            "quota": _get_quota(client_ip, is_admin=admin),
        }

    finally:
        # 清理临时文件
        os.unlink(tmp_path)


def _extract_product_name(raw_text: str, filename: str = "") -> str:
    """从 OCR 文本中提取产品名，避免文件名含英文被 S2 命名校验拒绝。"""
    import re
    for line in raw_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if re.search(r'[A-Za-z]', line):
            continue
        if re.match(r'^[\d\s\.\-/ICSGBTQ]+$', line) or re.match(r'^\d', line):
            continue
        if any(w in line for w in ["标准", "规范", "规定", "ICS", "附录", "清单", "目录", "方法"]):
            continue
        # 跳过以功能词开头的行（缺商标名）
        if any(line.startswith(w) for w in ["消毒", "抗菌", "抑菌", "杀菌", "医用"]):
            continue
        if 4 <= len(line) <= 40:
            return line
    # 回退：确保通过三段式校验的默认名
    return "待审核消毒液"


def _serialize_stage(stage_output: dict) -> dict:
    """序列化阶段输出，处理不可 JSON 序列化的类型。"""
    result = {}
    for k, v in stage_output.items():
        if isinstance(v, bool):
            result[k] = v
        elif isinstance(v, (int, float)):
            result[k] = v
        elif isinstance(v, str):
            # 尝试解析 JSON 字符串
            if k.endswith("_json") or k.startswith("{"):
                try:
                    result[k.replace("_json", "") or k] = json.loads(v)
                    continue
                except (json.JSONDecodeError, TypeError):
                    pass
            result[k] = v
        else:
            result[k] = str(v)
    return result


# ═══════════════════════════════════════════════════
# 邮箱验证码登录
# ═══════════════════════════════════════════════════

from server.auth import send_verification_code, verify_code, get_user_from_token


@app.post("/api/auth/send-code")
async def auth_send_code(payload: dict):
    """发送邮箱验证码。DEV 模式下返回验证码明文（前端直接显示）。"""
    email = (payload.get("email") or "").strip()
    if not email or "@" not in email:
        return {"success": False, "error": "请输入有效的邮箱地址"}
    result = send_verification_code(email)
    if not result:
        return {"success": False, "error": "验证码发送失败，请检查 SMTP 配置或稍后重试"}
    # DEV 模式：result 是验证码字符串；生产模式：result 是 "ok"
    is_dev = (result != "ok")
    return {
        "success": True,
        "message": "验证码已发送，请查收邮件",
        "dev_code": result if is_dev else None,
    }


@app.post("/api/auth/verify-code")
async def auth_verify_code(payload: dict):
    """验证邮箱验证码，返回 JWT。"""
    email = (payload.get("email") or "").strip()
    code = (payload.get("code") or "").strip()
    token = verify_code(email, code)
    if token:
        return {"success": True, "token": token, "email": email}
    return {"success": False, "error": "验证码错误或已过期"}


@app.get("/api/auth/me")
async def auth_me(request: Request):
    """获取当前登录用户信息。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return {"success": False, "error": "未登录"}
    user = get_user_from_token(auth[7:])
    if user:
        return {"success": True, "user": user}
    return {"success": False, "error": "登录已过期，请重新登录"}


@app.post("/api/admin/smtp-test")
async def admin_smtp_test(payload: dict, request: Request):
    """Admin 端点：发送测试邮件到指定地址，验证 SMTP 配置是否正确。"""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    email = (payload.get("email") or "").strip()
    if not email or "@" not in email:
        return {"success": False, "error": "请输入有效的测试邮箱地址"}

    from server.auth import SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT
    if not SMTP_USER or not SMTP_PASS:
        return {
            "success": False,
            "error": "SMTP 未配置",
            "detail": "请在 .env 中设置 SMTP_USER 和 SMTP_PASS。QQ邮箱需使用授权码而非登录密码。",
        }

    result = send_verification_code(email)
    is_dev = (result != "ok")
    if result is None:
        return {
            "success": False,
            "error": "邮件发送失败",
            "detail": f"SMTP 连接 {SMTP_HOST}:{SMTP_PORT} 失败，请检查 SMTP_USER/SMTP_PASS 是否正确",
        }
    return {
        "success": True,
        "message": f"测试邮件已发送到 {email}，请查收",
        "dev_mode": is_dev,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    workers = int(os.getenv("WORKERS", "1"))
    uvicorn.run("server.main:app", host="0.0.0.0", port=port, workers=workers, reload=(workers == 1))


# 挂载静态文件 — 提供 Web 前端上传界面（在所有 API 路由之后定义，避免抢占 API）
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
