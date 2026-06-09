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

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from server.pipeline import preaudit, PipelineResult
from server.ocr_service import process_file

# ═══════════════════════════════════════════════════
# 安全配置
# ═══════════════════════════════════════════════════

MAX_UPLOAD_SIZE = 10 * 1024 * 1024   # 10MB
MAX_BODY_SIZE = 10 * 1024             # 10KB
RATE_LIMIT_WINDOW = 60                # 秒
RATE_LIMIT_MAX = 5                    # 每窗口最多 5 次

_rate_log: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    _rate_log[client_ip] = [t for t in _rate_log[client_ip] if t > cutoff]
    if len(_rate_log[client_ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_log[client_ip].append(now)
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


@app.post("/api/preaudit")
async def preaudit_text(payload: dict, request: Request):
    """文本直接提交 — 跳过 OCR，直接跑合规预审。"""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

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
    }


@app.post("/api/upload")
async def preaudit_upload(file: UploadFile = File(...), request: Request = None):
    """上传产品标签文件 — OCR 解析后跑合规预审。最大 10MB。"""
    client_ip = request.client.host if request and request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

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

        product_info = {
            "product_name": f"上传文件: {file.filename}",
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
        }

    finally:
        # 清理临时文件
        os.unlink(tmp_path)


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# 挂载静态文件 — 提供 Web 前端上传界面（在所有 API 路由之后定义，避免抢占 API）
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
