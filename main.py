import uvicorn
import httpx
import secrets
import os
import logging
import re
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from database import init_db, save_lead, get_all_leads, delete_lead, add_visit, get_visit_stats

load_dotenv()

# ─── Логирование ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Константы валидации ───────────────────────────────────────────────────────
NAME_MIN, NAME_MAX       = 2, 50
PHONE_MIN, PHONE_MAX     = 7, 20
PROBLEM_MIN, PROBLEM_MAX = 5, 1000
TIME_MAX                 = 50

PHONE_RE = re.compile(r"^[\d\s\+\(\)\-]+$")  # только цифры, +, (, ), -, пробелы


# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("База данных инициализирована")
    yield
    log.info("Приложение остановлено")


# ─── Приложение ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(title="Вправе API", lifespan=lifespan, docs_url=None, redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Разрешаем только свой домен (замените на реальный)
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")
if ALLOWED_HOSTS != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Middleware для сбора посещений ───────────────────────────────────────────
@app.middleware("http")
async def count_visits(request: Request, call_next):
    # Считаем только GET-запросы к главной странице
    if request.method == "GET" and request.url.path == "/":
        ip = request.headers.get("X-Real-IP") or request.client.host
        user_agent = request.headers.get("User-Agent", "")
        try:
            add_visit(ip, user_agent)
        except Exception as e:
            log.error("Ошибка записи посещения: %s", e)
    response = await call_next(request)
    return response


# ─── Безопасность админки ─────────────────────────────────────────────────────
from fastapi.security import HTTPBasic, HTTPBasicCredentials
security = HTTPBasic()

def check_admin(credentials: HTTPBasicCredentials = Depends(security)):
    admin_user = os.getenv("ADMIN_LOGIN", "admin")
    admin_pass = os.getenv("ADMIN_PASS", "changeme")

    ok_user = secrets.compare_digest(credentials.username.encode(), admin_user.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), admin_pass.encode())

    if not (ok_user and ok_pass):
        log.warning("Неудачная попытка входа в админку: user=%s", credentials.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Доступ запрещён",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ─── Валидация ────────────────────────────────────────────────────────────────
def validate_lead(name: str, phone: str, problem: str, contact_time: str) -> list[str]:
    """Возвращает список ошибок. Пустой список = всё OK."""
    errors = []

    name = name.strip()
    if not (NAME_MIN <= len(name) <= NAME_MAX):
        errors.append(f"Имя должно быть от {NAME_MIN} до {NAME_MAX} символов.")

    phone = phone.strip()
    if not (PHONE_MIN <= len(phone) <= PHONE_MAX):
        errors.append(f"Телефон должен быть от {PHONE_MIN} до {PHONE_MAX} символов.")
    elif not PHONE_RE.match(phone):
        errors.append("Телефон содержит недопустимые символы.")

    problem = problem.strip()
    if not (PROBLEM_MIN <= len(problem) <= PROBLEM_MAX):
        errors.append(f"Описание проблемы: от {PROBLEM_MIN} до {PROBLEM_MAX} символов.")

    if len(contact_time.strip()) > TIME_MAX:
        errors.append(f"Удобное время: не более {TIME_MAX} символов.")

    return errors


# ─── Фоновые задачи ───────────────────────────────────────────────────────────
async def send_tg_notification(name: str, phone: str, contact_time: str, problem: str):
    token   = os.getenv("TG_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        log.warning("TG_TOKEN или TG_CHAT_ID не заданы — уведомление не отправлено")
        return

    text = (
        "<b>🔥 Новая заявка с сайта!</b>\n\n"
        f"👤 <b>Имя:</b> {name}\n"
        f"📞 <b>Телефон:</b> {phone}\n"
        f"🕐 <b>Удобное время:</b> {contact_time or 'не указано'}\n"
        f"💬 <b>Проблема:</b> {problem}"
    )

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=7.0,
            )
            if resp.status_code != 200:
                log.error("Ошибка отправки TG: %s", resp.text)
            else:
                log.info("TG уведомление отправлено успешно")
        except httpx.TimeoutException:
            log.error("Таймаут при отправке TG уведомления")
        except Exception as e:
            log.error("Неожиданная ошибка TG: %s", e)


# ─── Роуты ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, success: bool = False):
    return templates.TemplateResponse("index.html", {"request": request, "success": success})


@app.post("/send-lead")
@limiter.limit("3/minute")
async def handle_form(
    request: Request,
    background_tasks: BackgroundTasks,
    user_name:     str = Form(..., max_length=50),
    user_phone:    str = Form(..., max_length=20),
    contact_time:  str = Form("", max_length=50),
    user_problem:  str = Form(..., max_length=1000),
    bot_trap:      str = Form(None),
):
    # Honeypot: боты заполняют скрытое поле
    if bot_trap:
        ip = request.headers.get("X-Real-IP") or request.client.host
        log.info("Бот пойман через honeypot, IP=%s", ip)
        return RedirectResponse(url="/?success=true", status_code=303)

    # Валидация
    errors = validate_lead(user_name, user_phone, user_problem, contact_time)
    if errors:
        log.warning("Ошибки валидации: %s", errors)
        return RedirectResponse(url="/", status_code=303)

    ip         = request.headers.get("X-Real-IP") or request.client.host
    user_agent = request.headers.get("User-Agent", "")

    # Сохранение в БД
    try:
        save_lead(
            user_name.strip(),
            user_phone.strip(),
            contact_time.strip() or "Не указано",
            user_problem.strip(),
            ip,
            user_agent,
        )
        log.info("Новая заявка сохранена: name=%s phone=%s ip=%s", user_name, user_phone, ip)
    except Exception as e:
        log.error("Ошибка сохранения заявки в БД: %s", e)
        return RedirectResponse(url="/", status_code=303)

    # TG в фоне
    background_tasks.add_task(
        send_tg_notification,
        user_name.strip(),
        user_phone.strip(),
        contact_time.strip(),
        user_problem.strip(),
    )

    return RedirectResponse(url="/?success=true", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, username: str = Depends(check_admin)):
    try:
        leads = get_all_leads()
        visit_stats = get_visit_stats()
    except Exception as e:
        log.error("Ошибка загрузки данных: %s", e)
        leads = []
        visit_stats = {"total": 0, "today": 0, "unique_ips": 0, "recent": []}
    log.info("Админка открыта пользователем: %s", username)
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "leads": leads,
            "total_leads": len(leads),
            "visit_stats": visit_stats
        }
    )


@app.post("/admin/delete/{lead_id}")
def delete_item(lead_id: int, username: str = Depends(check_admin)):
    try:
        delete_lead(lead_id)
        log.info("Заявка #%d удалена пользователем %s", lead_id, username)
    except Exception as e:
        log.error("Ошибка удаления заявки #%d: %s", lead_id, e)
    return RedirectResponse(url="/admin", status_code=303)


# ─── Точка входа ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=os.getenv("DEBUG", "false").lower() == "true",
    )