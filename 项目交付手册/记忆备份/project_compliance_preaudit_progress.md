---
name: 消字号合规预审引擎项目进度
description: ai_sale_agent001 项目开发进度，2026-06-10 MVP 交付就绪，进入销售/交付阶段
type: project
originSessionId: b1eb8bd1-ed42-46b8-b0d9-c98b4aa150a0
---

## 当前状态：交付就绪

项目代码完整，测试 20/20 PASS。用户是 OPC 顾问（非开发者），将软件销售给品牌方客户，由客户自行部署。

项目路径：`~/Desktop/ai_sale_agent001/`
客户部署文档：项目根目录 `DEPLOY.md`
依赖清单：项目根目录 `requirements.txt`

## 已完成的 MVP 功能

**核心引擎**
- S0-S7 Pipeline 全部实现
- OCR 文件解析（PDF/图片）
- 20/20 测试 PASS

**配额系统**
- 3 次免费/IP，用完后显示付费墙 ¥499/份
- SQLite 持久化（`server/quota_store.py`），重启不丢失
- localhost 自动无限配额

**Admin 鉴权**
- 双重校验：localhost 自动放行；生产环境需邮箱登录(JWT) + admin key
- Admin key 从 `.env` 读取，支持三种传递方式
- Admin 面板：重置配额 / 复制链接 / SMTP 测试

**邮箱验证码登录**
- `server/auth.py`：QQ 邮箱 SMTP 发送 → JWT 签发
- DEV 模式（SMTP 未配置）：验证码自动填入
- SMTP 错误分级诊断（认证/连接/其他三类）

**前端 UI**
- 登录弹窗 + Admin 徽章 + 配额徽章
- StaticFiles 挂载，与 API 同端口

**生产部署**
- `run_prod.sh` 生产启动脚本（支持 PORT/WORKERS 环境变量）
- `requirements.txt` 依赖清单
- `DEPLOY.md` 客户部署指南

## 客户交付文件

| 文件 | 用途 |
|------|------|
| `DEPLOY.md` | 品牌方客户部署说明书（五步：上传→安装→配置.env→启动→验证SMTP） |
| `requirements.txt` | Python 依赖（fastapi, uvicorn, PyJWT, python-multipart） |
| `run_prod.sh` | 一键生产启动脚本 |
| `.env` | 配置文件模板（需客户填入自己的密钥和邮箱） |

## 交付时需提醒客户

1. QQ 邮箱必须用**授权码**（16位），不能填 QQ 登录密码
2. 获取路径：QQ 邮箱网页版 → 设置 → 账户 → POP3/SMTP 服务 → 开启 → 短信验证 → 获取授权码
3. 填好 `.env` 后用 `POST /api/admin/smtp-test?key=ADMIN_KEY {"email":"收件邮箱"}` 验证
4. 生产环境建议用 `run_prod.sh` 而非 `python3 -m uvicorn`

**Why:** 项目从原型到 MVP 到交付就绪，用户以 OPC 顾问身份销售软件给品牌方
**How to apply:** 客户部署问题时，参照 DEPLOY.md 和下方客户支持速查记忆
