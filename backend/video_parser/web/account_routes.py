"""账号与登录: per-platform saved logins. Responses never contain cookie values."""
from fastapi import APIRouter, Depends, HTTPException

from video_parser.services import accounts
from video_parser.web.security import local_request

router = APIRouter(prefix='/api/workspace', dependencies=[Depends(local_request)])


def guarded(action, *args):
    try:
        return action(*args)
    except KeyError:
        raise HTTPException(404, '不支持该平台，或当前没有进行中的登录。') from None
    except BlockingIOError as error:
        raise HTTPException(409, str(error)) from None
    except RuntimeError as error:
        raise HTTPException(400, str(error)) from None


@router.get('/accounts')
def account_overview():
    return accounts.overview()


@router.get('/accounts/{platform}')
def account_detail(platform: str):
    return guarded(accounts.public, platform)


@router.post('/accounts/{platform}/login')
def account_login(platform: str):
    guarded(accounts.start_login, platform)
    return guarded(accounts.public, platform)


@router.post('/accounts/{platform}/qr')
def account_qr(platform: str):
    """Headless QR login: poll GET /accounts/{platform}; login.qr carries the image while waiting."""
    guarded(accounts.start_qr, platform)
    return guarded(accounts.public, platform)


@router.post('/accounts/{platform}/login/finish')
def account_login_finish(platform: str):
    guarded(accounts.finish_login, platform)
    return guarded(accounts.public, platform)


@router.post('/accounts/{platform}/login/cancel')
def account_login_cancel(platform: str):
    guarded(accounts.cancel_login, platform)
    return guarded(accounts.public, platform)


@router.post('/accounts/{platform}/check')
def account_check(platform: str):
    return guarded(accounts.check, platform)


@router.post('/accounts/{platform}/logout')
def account_logout(platform: str):
    return guarded(accounts.logout, platform)
