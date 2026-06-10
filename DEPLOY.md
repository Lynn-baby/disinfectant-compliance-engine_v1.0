# 消字号合规预审引擎 — 部署指南

> 面向品牌方客户的部署说明书。如遇问题，联系您的 OPC 顾问。

## 前置条件

- 一台服务器（阿里云轻量应用服务器 ¥68/月 即可，或任意 Linux/macOS 机器）
- Python 3.10+
- 一个 QQ 邮箱账号（用于发送登录验证码）

---

## 第一步：上传代码

将整个项目文件夹上传到服务器，例如放在 `/opt/disinfectant-engine/`。

---

## 第二步：安装 Python 依赖

```bash
cd /opt/disinfectant-engine
pip3 install -r requirements.txt
```

---

## 第三步：配置 .env 文件

打开项目根目录下的 `.env` 文件，填入以下内容：

```
DEEPSEEK_API_KEY=sk-你的DeepSeek密钥
ADMIN_KEY=你自定的管理员密钥（如 my-brand-2026）
JWT_SECRET=随机字符串用作加密密钥（如 bXlzZWNyZXQrYW5k 这类乱码）

# QQ 邮箱 SMTP 配置（发送登录验证码用）
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=你的QQ邮箱地址@qq.com
SMTP_PASS=你的QQ邮箱授权码
```

### 如何获取 QQ 邮箱授权码？

1. 登录 QQ 邮箱网页版
2. 点击 **设置 → 账户**
3. 找到 **POP3/IMAP/SMTP 服务**
4. 点击 **开启 SMTP 服务**
5. 按提示发送短信验证，系统会生成一个 **16 位授权码**
6. 将这个授权码填入 `.env` 的 `SMTP_PASS` 字段

> QQ 邮箱必须用授权码，不能用 QQ 登录密码。

---

## 第四步：启动服务

### 开发测试（单 worker，修改代码自动重载）

```bash
cd /opt/disinfectant-engine
python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

### 生产运行（多 worker，性能更好）

```bash
cd /opt/disinfectant-engine
./run_prod.sh
```

或自定义端口和 worker 数：

```bash
PORT=8080 WORKERS=4 ./run_prod.sh
```

启动后访问 `http://你的服务器IP:8000` 即可看到 Web 界面。

---

## 第五步：验证 SMTP 邮件发送

SMTP 配置好后，用管理员端点测试邮件是否发送成功：

```bash
curl -X POST "http://你的服务器IP:8000/api/admin/smtp-test?key=你的ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"收件人邮箱@qq.com"}'
```

返回 `"success": true` 表示邮件发送成功。如失败，检查：
- SMTP_USER 和 SMTP_PASS 是否正确
- QQ 邮箱是否用了授权码（非登录密码）
- 服务器防火墙是否允许出站 465 端口

---

## 常见问题

**Q: 启动报错 `ModuleNotFoundError: No module named 'server'`**

A: 确保在项目根目录（包含 `server/` 文件夹的那个目录）执行命令。

**Q: 上传文件 OCR 没反应**

A: 确保服务器上安装了 Tesseract OCR。macOS: `brew install tesseract`；Ubuntu: `sudo apt install tesseract-ocr`。

**Q: 配额用完了怎么重置？**

A: 浏览器打开 Web 页面，点击右上角 Admin 徽章 → 重置配额。或者调用 API：

```bash
curl -X POST "http://你的服务器IP:8000/api/quota/reset?key=你的ADMIN_KEY"
```

**Q: 如何设置域名 + HTTPS？**

A: 推荐使用 Nginx 反向代理 + Let's Encrypt 免费证书。具体配置请联系 OPC 顾问。
