---
name: 消字号合规引擎客户支持速查
description: 品牌方客户部署和故障排查速查表，含 SMTP、配额、启动三大类常见问题
type: reference
originSessionId: d4cd97c7-2650-4130-b585-0c9b600c512a
---
用户以 OPC 顾问身份销售此软件给品牌方客户。客户自行部署。以下为常见客户问题的标准答案。

## SMTP 邮件问题

**问题：客户说验证码收不到**

排查顺序：
1. `.env` 里 `SMTP_USER` 和 `SMTP_PASS` 是否都填了？
2. `SMTP_PASS` 是 QQ 邮箱**授权码**（16 位字母数字），不是 QQ 登录密码
3. 获取授权码路径：QQ 邮箱网页版 → 设置 → 账户 → POP3/SMTP 服务 → 开启 → 短信验证 → 获取授权码
4. 用 SMTP 测试端点验证：`curl -X POST "http://IP:8000/api/admin/smtp-test?key=ADMIN_KEY" -H "Content-Type: application/json" -d '{"email":"收件邮箱"}'`
5. 如果返回 `"success": false, "detail": "SMTP 未配置"` → .env 文件没有被正确加载
6. 如果返回 `SMTP 认证失败` → 授权码错误或过期

**问题：客户没有 QQ 邮箱**

换其他 SMTP 服务商，修改 `.env` 中这三个值即可：
- `SMTP_HOST` — 如 `smtp.gmail.com`
- `SMTP_PORT` — 如 `587`（Gmail/StartTLS）
- `SMTP_USER` / `SMTP_PASS` — 对应服务的账号和应用专用密码

## 配额问题

**问题：客户说"配额用完"但还没开始用**

- 每个 IP 有 3 次免费配额
- 如果多人共享一个网络出口（同一办公室），会共享配额
- 解决方法：Admin 面板重置，或 `curl -X POST "http://IP:8000/api/quota/reset?key=ADMIN_KEY"`
- localhost 无限配额，不受限制

**问题：重启服务器后配额会丢失吗？**

不会。配额已存 SQLite（`data/quota.db`），重启不丢失。

## 启动问题

**问题：ModuleNotFoundError: No module named 'server'**

解法：必须在项目根目录（包含 `server/` 文件夹的目录）下运行命令，不能用绝对路径指到 `server/main.py`。

**问题：端口已被占用**

`PORT=8080 ./run_prod.sh` 换端口启动。

**问题：OCR 不工作**

需安装 Tesseract OCR：Ubuntu 用 `sudo apt install tesseract-ocr`，macOS 用 `brew install tesseract`。

## 关键文件位置

所有路径相对于项目根目录：
- 主程序：`server/main.py`
- 配置文件：`.env`
- 部署指南：`DEPLOY.md`
- 生产启动：`./run_prod.sh`
- 运行测试：`python3 server/test_server.py`（20 项）
- 配额数据库：`data/quota.db`（SQLite，自动创建）
