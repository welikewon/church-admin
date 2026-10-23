# -*- coding: utf-8 -*-
"""교회 종합행정시스템 — 웹 대시보드(모던 UI). 브라우저에서 카드로 사용.
실행: python church_web.py  → 자동으로 브라우저 열림(localhost). church.py를 그대로 구동."""
import os, sys, json, subprocess, threading, webbrowser, re, time, hashlib, hmac, secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE=os.path.dirname(os.path.abspath(__file__))
CHURCH_PY=os.path.join(BASE,"church.py")
PORT=8899
def _engine_ver():
    """church.py의 VERSION을 단일 소스로 읽어 웹 버전 표기를 엔진과 일치(불일치 방지, #6)."""
    try:
        m=re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', open(CHURCH_PY,encoding='utf-8').read())
        return m.group(1) if m else "?"
    except Exception:
        return "?"
def cfg():
    p=os.path.join(BASE,"church_config.json")
    if os.path.exists(p):
        try: return json.load(open(p,encoding='utf-8'))
        except Exception: pass
    return {"교회명":"○○교회","담임":"담임목사"}
C=cfg()

# ── 📱 폰 접속 자물쇠 ──────────────────────────────────────────────────────
#    ★인증은 ★항상 요구한다. "이 컴퓨터에서 왔으니 통과"라는 예외를 두지 않는다.
#      접속 주소(client_address)로 통과를 결정하면, 나중에 누가 중계(프록시)를 한 겹만 얹어도
#      ★모든 접속이 이 컴퓨터에서 온 것처럼 보여 전원이 무인증 통과가 된다.
#      그 대신 사무실 컴퓨터는 기동할 때 발급한 '로컬 열쇠'로 ★자동 로그인한다 —
#      목사님은 지금처럼 바탕화면 아이콘만 누르시면 되고, 비밀번호를 치실 일이 없다.
#    ★세션·비밀번호는 church_config.json 에만 둔다. 새 파일을 만들지 않는다.
#      새 파일은 빌드·발행·설치본ZIP·업데이트보호 네 곳에 모두 등록해야 하고 하나만 빠져도 샌다.
#      church_config.json 은 네 곳 모두에서 이미 안전함을 기계로 확인했다(발행 EXCL_NAMES /
#      빌드 미복사 / 설치본 미포함 / update prot_files 보호).
COOKIE_NAME="church_phone_sid"
CSRF_HEADER="X-Church-App"     # 단순 폼(enctype=text/plain)은 이 헤더를 붙일 수 없다 = CSRF 차단
# ── 무차별 대입 대비 — ★잠금이 아니라 '점증 지연' (오너 티켓 2026-08-20 §1-4) ────────
#   ★왜 잠그지 않는가: 잠그면 **목사님 본인이 못 들어가는 사고**가 난다(심방 중에 10분 대기).
#     막으려는 것은 '기계가 초당 수백 번 두드리는 것'이지 '사람이 몇 번 틀리는 것'이 아니다.
#     지연은 기계에는 치명적이고(수천 번 시도가 수십 시간이 된다) 사람에게는 몇 초다.
FAIL_MAX=5          # 이 횟수부터 지연을 건다(그 전까지는 즉답)
FAIL_DELAY=1.5      # 틀릴 때마다의 기본 지연 — 자동 대입의 속도를 떨어뜨린다
DELAY_MAX=60        # 지연 상한(초). ★여기까지만 늘어난다 — 무한히 늘리면 그것이 곧 잠금이다
FAIL_KEEP=1800      # 실패 기억 보관 시간(초) — 이만큼 조용하면 잊는다
_SESS={}                       # {토큰: [만료, 발급, 종류]}  종류 = local | remote
_SESS_LOCK=threading.Lock()
FAIL_KEYS_MAX=512   # 실패 기억 항목 상한(무한 증식 방지)
GLOBAL_MAX=30       # 대역을 바꿔 가며 두드릴 때를 위한 전체 상한
_FAILS={}                      # {대역키: [연속실패, (미사용·0), 최종시각]}  ★두 번째 칸은 잠금해제시각이었다 — 잠금을 없애며 0 으로 둔다
_GLOBAL=[0,0,0]                # [전체실패, (미사용·0), 최종시각]
# ★프록시가 붙인 머리글들. 신뢰하려고 보는 게 아니라 ★거절하려고 본다 —
#   이 머리글이 있다는 것은 중계를 거쳤다는 뜻이고, 그러면 접속 주소가 이 컴퓨터로 보인다.
PROXY_HEADERS=("X-Forwarded-For","X-Forwarded-Host","X-Forwarded-Proto","X-Real-IP",
               "Forwarded","Via","Tailscale-User-Login","Tailscale-User-Name")
_SAVED_EXP={}                  # 디스크에 적어 둔 만료 — 이만큼 밀렸을 때만 다시 적는다
_LOCAL_KEY=""                  # 기동할 때마다 새로 만드는 사무실 컴퓨터용 열쇠(메모리)
_BOUND=[]                      # 실제로 바인딩한 주소들 — Host 화이트리스트의 근거

CFG_PATH=os.path.join(BASE,"church_config.json")
_CFG_CACHE={"mtime":None,"data":{}}
_CFG_LOCK=threading.Lock()
_CFG_BROKEN=[""]        # 설정 파일이 깨졌을 때의 사유(한국어). 비어 있으면 정상.

def _cfg_live():
    """설정을 그때그때 반영하되, 바뀌지 않았으면 파일을 다시 읽지 않는다.
       (방금 정하신 비밀번호·방금 켠 스위치가 바로 먹히면서도 요청마다 파일을 여는 낭비는 없게)
       ★파일이 깨져 있으면 ★기본값을 지어내지 않는다 — 지어내면 '비밀번호가 없는 상태'로 보여
         원인 모를 폰접속 사망이 되거나, 더 나쁘게는 보호가 조용히 사라진다. 사유를 남기고 멈춘다."""
    try: mt=os.path.getmtime(CFG_PATH)
    except Exception:
        _CFG_BROKEN[0]=""                 # 아직 설정 파일이 없는 것은 정상(첫 실행)
        return _CFG_CACHE["data"] or {}
    if _CFG_CACHE["mtime"]!=mt:
        try:
            d=json.load(open(CFG_PATH,encoding='utf-8'))
            if not isinstance(d,dict): raise ValueError("설정 형식이 아닙니다")
            _CFG_CACHE["data"]=d; _CFG_CACHE["mtime"]=mt; _CFG_BROKEN[0]=""
        except Exception as e:
            _CFG_BROKEN[0]=("설정 파일(church_config.json)을 읽지 못했습니다 — "+type(e).__name__+
                            ". 폰 접속을 잠급니다. 사무실 컴퓨터에서 확인해 주세요"
                            " (바로 옆의 church_config.json.bak 이 직전 정상본입니다).")
    return _CFG_CACHE["data"]

def _cfg_write(patch):
    """설정 파일에 몇 항목만 얹어 저장한다.
       ★다시 읽고 → 직전 정상본 백업 → 임시파일 → fsync → 바꿔치기(os.replace).
         메모리에 들고 있던 옛 설정으로 통째로 쓰면 방금 다른 기능이 저장한 값(교회 이름 등)을 지운다.
         중간에 전원이 나가도 반쪽짜리 설정 파일이 남지 않는다.
       ★깨진 설정 위에는 쓰지 않는다 — 덮어쓰면 교회명·아카이브루트·숨긴카드까지 함께 잃는다."""
    with _CFG_LOCK:
        try:
            c={}
            if os.path.exists(CFG_PATH):
                try:
                    c=json.load(open(CFG_PATH,encoding='utf-8'))
                    if not isinstance(c,dict): raise ValueError("설정 형식이 아닙니다")
                except Exception:
                    return False          # 깨진 설정을 덮어써 교회 이름까지 날리지 않는다
                try: __import__("shutil").copy2(CFG_PATH, CFG_PATH+".bak")   # 직전 정상본 보관
                except Exception: pass
            c.update(patch)
            tmp=CFG_PATH+".tmp"
            with open(tmp,'w',encoding='utf-8') as f:
                json.dump(c,f,ensure_ascii=False,indent=2)
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp,CFG_PATH)
            _CFG_CACHE["mtime"]=None      # 다음 읽기 때 새로 읽게
            return True
        except Exception:
            return False

def _sess_days():
    try: return max(1, int(_cfg_live().get("폰세션유효일",30) or 30))
    except Exception: return 30

def _sess_cut():
    """이 시각 이전에 로그인한 ★폰(remote) 기기를 끊는다('모든 기기 로그아웃'을 누르셨을 때).
       ★사무실(local) 로그인에는 걸지 않는다 — 대조하는 곳은 _sess_get 이고, 거기서 remote 로 한정한다.
       (여기 설명과 그쪽 코드가 어긋나면 안 된다. 한쪽만 고치지 마라.)"""
    try: return float(_cfg_live().get("폰세션무효화") or 0)
    except Exception: return 0.0

def _sess_load():
    """서버가 다시 떠도(업데이트 자동 재시작 포함) 폰이 다시 로그인하지 않게 — 심방 중에 로그인 화면을 만나면 안 된다."""
    try:
        now=time.time()
        with _SESS_LOCK:
            for t,v in (_cfg_live().get("폰세션") or {}).items():
                if not isinstance(v,(list,tuple)) or len(v)<4: continue
                if float(v[0])>now:
                    # 5번째 칸 = 그 세션의 길이(초). 옛 기록에는 없으므로 그때는 설정값을 쓴다.
                    _ttl=float(v[4]) if len(v)>=5 and v[4] else _sess_days()*86400
                    # ★옛 기록에는 «마지막접속·기기» 칸이 없다 — 없으면 발급 시각·빈 이름으로 채운다
                    #   (없는 것을 지어내지 않되, 목록이 무너지지도 않게).
                    _last=float(v[5]) if (len(v)>=6 and v[5]) else float(v[1])
                    _dev=str(v[6]) if (len(v)>=7 and v[6]) else ""
                    _SESS[t]=[float(v[0]),float(v[1]),str(v[2]),float(v[3]),_ttl,_last,_dev]
                    _SAVED_EXP[t]=float(v[0])
    except Exception: pass

def _tok_key(t):
    """토큰을 저장할 때 쓰는 값. ★파일에는 토큰 원문을 적지 않는다 — 원문을 적으면
       그 파일을 보는 사람이 그대로 로그인할 수 있다. 원문은 폰의 쿠키에만 있고,
       여기에는 되돌릴 수 없는 형태만 남는다(새어도 그 값으로는 위조가 안 된다)."""
    return hashlib.sha256(("church-sess:"+(t or "")).encode('utf-8')).hexdigest()

def _pw_gen():
    """지금 비밀번호의 '세대'. 비밀번호를 바꾸면 이 값이 바뀐다.
       ★화면 프로그램과 설정 프로그램은 별개 프로세스라 서로의 기억을 지울 수 없다.
         그래서 '지운다' 대신 '세대가 다르면 무효'로 취소 경로를 만든다."""
    r=_cfg_live().get("폰비밀번호")
    try: return float(r.get("세대") or 0) if isinstance(r,dict) else 0.0
    except Exception: return 0.0

def _sess_save():
    """세션을 설정 파일에 적는다. ★요청마다 적지 않는다 — 만들거나 지울 때, 그리고
       접속 갱신이 하루 넘게 밀렸을 때만 부른다(디스크 혹사 방지)."""
    try:
        now=time.time()
        with _SESS_LOCK:
            snap={t:v for t,v in _SESS.items() if v[0]>now}   # 지난 것은 적지 않는다(설정 파일 비대화 방지)
            _SESS.clear(); _SESS.update(snap)
            _SAVED_EXP.clear(); _SAVED_EXP.update({t:v[0] for t,v in snap.items()})
        _cfg_write({"폰세션":snap})
    except Exception: pass

NOREMEMBER_SEC=12*3600   # '이 폰 기억하기'를 끄셨을 때의 서버측 유효시간(12시간)

def _ua_label(ua):
    """브라우저가 보낸 자기소개를 ★목사님이 알아보실 만한 짧은 말로 바꾼다.
       ★목적은 «기기를 식별»하는 것이 아니라 «내 것이 아닌 것을 알아보시게» 하는 것이다.
         그래서 정밀한 지문이 아니라 «아이폰 사파리»처럼 ★대충 알아볼 만큼만 적는다.
       ★자기소개는 얼마든지 꾸며 낼 수 있다 — 이 값을 ★통과·차단의 근거로는 절대 쓰지 않는다.
         오직 ★보여 드리는 용도다(보안 판단이 아니라 알아보심을 돕는 것)."""
    u=(ua or "")
    if not u.strip(): return "알 수 없는 기기"
    if "iPhone" in u: os_="아이폰"
    elif "iPad" in u: os_="아이패드"
    elif "Android" in u: os_="안드로이드 폰"
    elif "Windows" in u: os_="윈도우 컴퓨터"
    elif "Macintosh" in u or "Mac OS" in u: os_="맥"
    elif "Linux" in u: os_="리눅스"
    else: os_="기타 기기"
    if "Edg/" in u: br="엣지"
    elif "SamsungBrowser" in u: br="삼성 인터넷"
    elif "FxiOS" in u or "Firefox" in u: br="파이어폭스"
    elif "CriOS" in u or "Chrome" in u: br="크롬"
    elif "Safari" in u: br="사파리"
    else: br=""
    return (os_+" · "+br) if br else os_

def _sess_touch(k, ua):
    """이 세션이 ★방금 쓰였다고 적어 둔다 — 「들어와 있는 기기」 목록의 «마지막 접속»이 이 값이다.
       ★이 함수는 디스크에 안 적는다(요청마다 파일을 쓰면 디스크를 혹사한다). 기억에만 둔다 —
         프로그램을 껐다 켜면 «마지막 접속»은 세션 만든 시각으로 되돌아간다. 그 정도면 목적에 족하다.
       ★단, «디스크에 영영 안 남는다»는 뜻은 아니다 (reviewer-claude-1 R2 지적 · 문장 보완):
         다른 일로 `_sess_save()` 가 돌 때(세션 생성·삭제·하루 넘긴 갱신) ★이 값도 함께 실려 나가
         church_config.json 의 «폰세션» 에 적힌다. 여기서 안 적을 뿐이지 안 적히는 것은 아니다.
         (그 파일은 발행·빌드·설치본 어디에도 안 실리므로 위험이 늘지는 않는다 — 사실만 바로잡는다.)"""
    try:
        with _SESS_LOCK:
            v=_SESS.get(k)
            if not v: return
            while len(v)<7: v.append("")
            v[5]=time.time()
            if ua and not v[6]: v[6]=_ua_label(ua)   # ★처음 본 기기 이름을 남긴다(나중에 안 덮는다)
    except Exception: pass

def _sess_new(kind, ttl=None):
    """kind: local = 이 컴퓨터(열쇠로 자동 로그인) / remote = 폰(비밀번호로 로그인)
       ttl: 이 세션의 유효시간(초). 안 주면 설정값(기본 30일).
       ★유효시간을 세션마다 들고 다니는 이유: '기억하기'를 끄신 로그인은 짧게 끝나야 하는데,
         아래 _sess_get 이 접속할 때마다 만료를 다시 미는(슬라이딩) 구조라
         길이를 세션에 안 적어 두면 짧은 세션도 30일로 밀려 버린다."""
    now=time.time(); t=secrets.token_urlsafe(32)
    _ttl=float(ttl if ttl else _sess_days()*86400)
    # 칸 = [만료, 발급, 종류, 세대, 길이, ★마지막접속, ★기기이름]
    #   뒤의 두 칸은 「들어와 있는 기기」 목록을 위해 2026-08-27 에 더했다.
    #   ★옛 기록에는 이 칸이 없다 — 읽는 쪽(_sess_load·_sess_list)이 없어도 견디게 돼 있다.
    with _SESS_LOCK: _SESS[_tok_key(t)]=[now+_ttl, now, kind, _pw_gen(), _ttl, now, ""]
    _sess_save(); return t          # 원문은 쿠키로만 나간다

def _sess_get(t):
    """살아 있으면 [만료, 발급, 종류, 세대], 아니면 None. ★접속할 때마다 만료를 다시 30일로 민다
       (슬라이딩) — 심방지에서 갑자기 로그아웃되어 비밀번호가 기억 안 나는 상황을 막는다.
       계속 쓰시는 한 안 끊기고, 폰을 잃어 안 쓰면 30일 뒤 저절로 막힌다."""
    if not t: return None
    if _CFG_BROKEN[0]: return None      # 설정을 못 읽는 동안에는 아무도 통과시키지 않는다(fail-closed)
    now=time.time(); k=_tok_key(t)
    with _SESS_LOCK: v=_SESS.get(k)
    if not v: return None
    # ★비밀번호를 바꾸면 폰 로그인은 전부 끊는다 — 폰을 잃어버리셨을 때의 유일한 조치가 이것이다.
    #   사무실 로그인(local)은 이 컴퓨터에서만 얻는 열쇠로 만들어진 것이라 여기서 끊지 않는다
    #   (비밀번호를 정하신 그 화면이 그 순간 로그아웃되면 안 되기 때문이다).
    if v[2]=="remote" and v[3]!=_pw_gen():
        with _SESS_LOCK: _SESS.pop(k,None)
        _sess_save(); return None
    # ★'모든 기기에서 로그아웃'도 폰(remote)에만 걸린다 — 폰을 잃어버려 그 버튼을 누르신 목사님이
    #   보고 계신 사무실 화면까지 함께 잃으면 안 된다. 사무실 로그인은 이 컴퓨터에서만 얻는
    #   열쇠로 만들어진 것이라 잃어버린 폰과 함께 끊을 이유가 없다(위 세대 대조와 같은 형태다).
    if v[0]<=now or (v[2]=="remote" and v[1]<_sess_cut()):
        with _SESS_LOCK: _SESS.pop(k,None)
        _sess_save(); return None
    # ★슬라이딩은 ★그 세션의 길이만큼만 민다 — '기억하기'를 끄신 로그인(12시간)이
    #   접속할 때마다 30일로 밀려나면 그 선택이 무의미해진다. 옛 세션(길이 칸 없음)은 종전대로.
    _ttl=float(v[4]) if len(v)>=5 and v[4] else _sess_days()*86400
    new_exp=now+_ttl
    with _SESS_LOCK: v[0]=new_exp
    if new_exp-_SAVED_EXP.get(k,0)>86400: _sess_save()   # 하루 넘게 밀렸을 때만 디스크에
    return list(v)

def _sess_ok(t): return _sess_get(t) is not None

def _sess_drop(t):
    if not t: return
    with _SESS_LOCK: _SESS.pop(_tok_key(t),None)
    _sess_save()

# ── 📱 QR 1회용 열쇠 ──────────────────────────────────────────────────────
#   ★목사님이 하실 일을 «QR 비추기» 한 번으로 줄이려는 것이다. 그 대신 이것은
#     ★비밀번호를 건너뛰는 문이므로, 문의 조건을 못 박아 둔다 — 하나라도 어긋나면 열리지 않는다.
#       ㉮ 수명 3분 ㉯ ★한 번 쓰면 죽는다 ㉰ ★기억(메모리)에만 둔다 — 설정 파일에 안 적는다
#       ㉱ 원문은 ★QR 그림 안에만 있다. 화면 글자·기록·설정 어디에도 안 남는다
#       ㉲ 어긋나면 ★기존 비밀번호 화면으로 떨어진다(fail-closed)
#   ★기억에만 두는 이유 — 프로그램을 껐다 켜면 지금까지 뿌린 QR 이 ★전부 죽는다.
#     설정 파일에 적으면 ★그 파일을 보는 사람이 QR 없이 들어올 길이 생긴다(세션과 다른 판단이다:
#     세션은 재시작 후에도 살아 있어야 심방 중에 안 끊기지만, 이 열쇠는 3분이면 될 일이다).
#   ★저장할 때도 원문이 아니라 되돌릴 수 없는 값으로 둔다 — 기억을 덤프해도 그 값으로는 못 들어온다.
# ══════════════════════════════════════════════════════════════════════════════
# ★★이 기계를 «설명하는 곳» 목록 — 하나 고치면 ★넷을 다 읽어라
# ══════════════════════════════════════════════════════════════════════════════
#   ★왜 목록이 필요한가 (2026-08-27 · reviewer-claude-1 R3 진단 · master 재정):
#     F-3 → R2-N1 → R3-N1·N2 로 ★세 라운드 연속 같은 부류가 나왔다. 뿌리는 하나다 —
#     ★«화면 문장이 그것이 설명하는 기계와 다른 시각에 쓰인다».
#     기계를 고칠 때 문장을 같이 안 고치니, 문장이 어제의 기계를 설명하고 있다.
#   ★사람 기억에 맡기면 또 놓친다. 그래서 ★자리를 코드 옆에 적어 두고,
#     `_실험/문장검증.py` 가 ★이 목록을 근거로 «약속 문장»을 뽑아 검사한다.
#
#   QR 열쇠(_qr_new/_qr_take/_qr_clear)를 고치면 ★아래 넷을 다 읽어야 한다:
#     ① PAGE 의 `qrwarn`  — 「3분 안에 찍은 기기는 약 30일…」 위험 안내
#     ② PAGE 의 `qr_count` — 「N초 뒤 못 쓰게 됩니다」 남은 시간
#     ③ PAGE 의 renderQR 끝 `note` — 「①②③」 사용 순서 안내
#     ④ `_do_qr` 독스트링 — 문 안쪽 조건(㉮~㉲)
#   그리고 열쇠 «수명»을 바꾸면 ★QR_TTL 과 위 ①②의 숫자가 함께 움직여야 한다.
QR_SENTENCE_SITES=("PAGE.qrwarn","PAGE.qr_count","PAGE.renderQR.note","H._do_qr.__doc__")

# ★★불변식 — 이 줄을 지우지 마라 (reviewer-claude-1 R4 문안 · master 재정으로 못 박음):
#     **QR_TTL 은 ★상수다. ★설정에서 받지 마라 — 받는 순간 PAGE 주입 통로가 된다.**
#   지금 이 값은 화면으로 나간다(`__QRTTL__`). 지금은 안전하다 — 코드에 박힌 정수라
#   `str(int)` 로만 실려 나가기 때문이다. ★그러나 이것을 설정 파일에서 읽게 만드는 순간,
#   설정에 무엇을 적느냐가 ★화면 코드에 그대로 들어가는 길이 열린다.
#   ★이건 R2 의 「id 무해의 근거는 «해시라서»가 아니라 ★«아무도 신원으로 안 받아서»다」와 같은 모양이다 —
#     남길 것은 «지금 안전하다»가 아니라 ★«무엇이 깨지면 안전이 무너지는가»다.
QR_TTL=180          # 1회용 열쇠 수명(초). 화면의 QR 을 찍기엔 넉넉하고, 흘러 나가도 곧 죽는다
QR_MAX=12           # 동시에 살아 있을 수 있는 열쇠 수 — 무한 증식 방지
_QRTOK={}           # {되돌릴 수 없는 값: 만료시각}
_QRTOK_LOCK=threading.Lock()

def _qr_new():
    """1회용 열쇠를 만들어 ★원문을 돌려준다. 부르는 쪽은 이것을 ★QR 그림에만 싣는다."""
    now=time.time(); t=secrets.token_urlsafe(24)
    with _QRTOK_LOCK:
        for k in [k for k,v in _QRTOK.items() if v<=now]: _QRTOK.pop(k,None)
        while len(_QRTOK)>=QR_MAX:
            _QRTOK.pop(min(_QRTOK,key=_QRTOK.get),None)     # 가장 먼저 죽을 것부터 버린다
        _QRTOK[_tok_key("qr:"+t)]=now+QR_TTL
    return t

def _qr_take(t):
    """★한 번만 통한다 — 확인과 ★동시에 지운다(꺼내 보고 되돌려 놓지 않는다).
       ★같은 QR 을 두 사람이 동시에 찍어도 자물쇠 안에서 pop 하므로 ★한 쪽만 통과한다.
       ★'qr:' 를 앞에 붙여 세션 토큰과 섞이지 않게 한다 — 값이 겹쳐도 서로의 문이 되지 않는다."""
    if not t: return False
    now=time.time(); k=_tok_key("qr:"+t)
    with _QRTOK_LOCK: exp=_QRTOK.pop(k,None)
    return bool(exp and exp>now)

def _qr_clear():
    """살아 있는 QR 열쇠를 ★전부 죽인다. 돌려주는 값 = 죽인 개수.

       ★왜 필요한가 (2026-08-27 · reviewer-claude-1 R2-N1 · master 재정 «유코드로»):
         이 기능의 설계 전제는 «화면을 남이 보면 위험하니 ★목사님이 조치하실 수 있게»였다.
         그런데 「🔄 새 QR 만들기」·「닫기」가 ★옛 열쇠를 안 죽였다. 그래서
         10초 만에 옆사람을 알아채고 새 QR 을 누르셔도 ★옛 열쇠는 170초를 더 살았다.
         ⇒ ★목사님이 믿고 누르신 조치가 아무 효과가 없었다. 문장을 낮추는 대신 코드를 고친다.
       ★진행 중인 로그인을 깨지 않는다 — 이미 찍힌 열쇠는 `_qr_take` 가 그때 pop 해서
         여기 남아 있지 않기 때문이다(그 판단이 이 수리의 안전 근거다).
       ★덤: 열쇠 상한(QR_MAX)에 밀려 «방금 만든 QR 이 조용히 죽는» 경로도 함께 줄어든다 —
         닫으실 때마다 비워지므로 12개가 쌓이기 어렵다.
       ★★이것은 ★전역이다 (reviewer-claude-1 R3 · 등재). 이 프로그램은 하나뿐이므로 열쇠 보관함도
         하나다 — 사무실에서 탭을 둘 열어 두시면 ★한쪽에서 「닫기」를 누르는 순간 ★다른 탭의 QR 도
         함께 죽는다. 「왜 방금 만든 게 안 되지」가 될 수 있는 자리다.
         지금은 그렇게 두는 편이 안전 방향이라 그대로 둔다(적게 사는 쪽이 낫다) — ★사실만 적어 둔다."""
    with _QRTOK_LOCK:
        n=len(_QRTOK); _QRTOK.clear()
    return n

def _sess_list():
    """지금 ★들어와 있는 기기 목록. 「모르는 기기」를 목사님이 알아보시게 하는 것이 목적이다.

       ★왜 필요한가 (2026-08-27 · reviewer-claude-1 지적):
         QR 열쇠는 3분·1회용이지만, 그것으로 만들어지는 ★세션은 약 30일이고 쓸 때마다 연장된다.
         그러니 «열쇠가 짧다»는 것과 «피해가 짧다»는 것은 ★다른 말이다.
         종전에는 열쇠가 새어도 목사님이 ★알 방법이 자체가 없었다 — 그 눈을 여기서 만든다.
       ★★불변식 — 이 줄을 지우지 마라 (reviewer-claude-1 R2 · master 재정으로 못 박음):
         **`id`(세션 해시)를 ★신원 입력으로 절대 받지 않는다.**
         지금 이 값이 새어도 무해한 근거는 «sha256 이라서»가 ★아니다. 해시를 뒤집을 수 없다는 것은
         «이 값으로 토큰을 만들 수 없다»까지만 말해 준다. 무해의 진짜 근거는
         ★«이 프로그램의 어느 문도 id 를 받아 «너로구나» 하지 않는다» 는 것이다.
         `_do_devicedrop` 은 이 값을 ★끊을 대상을 고르는 데만 쓰고, 통과의 근거는 ★쿠키다.
         ⇒ 나중에 누가 «id 로 조회/로그인» 같은 문을 만들면 ★그 순간 이 값이 열쇠가 된다.
           남길 것은 «지금 안전하다»가 아니라 ★«지킬 축»이다."""
    now=time.time(); out=[]
    with _SESS_LOCK: snap=list(_SESS.items())
    for k,v in snap:
        if v[0]<=now: continue
        out.append({"id":k,
                    "종류":("이 컴퓨터" if v[2]=="local" else "폰·바깥 기기"),
                    "kind":v[2],
                    "기기":(v[6] if len(v)>=7 and v[6] else "알 수 없는 기기"),
                    "처음":float(v[1]),
                    "마지막":float(v[5]) if len(v)>=6 and v[5] else float(v[1]),
                    "만료":float(v[0])})
    out.sort(key=lambda d:-d["마지막"])
    return out

def _sess_drop_id(sid):
    """그 기기 ★하나만 끊는다. «전체 로그아웃»은 폰을 잃어버렸을 때의 큰 조치라,
       «모르는 기기 하나»를 보셨을 때 쓰기에는 너무 크다(목사님 사무실 화면까지 끊긴다)."""
    if not sid: return False
    with _SESS_LOCK: gone=_SESS.pop(sid,None) is not None
    if gone: _sess_save()
    return gone

def _pw_rec():
    r=_cfg_live().get("폰비밀번호")   # 설정은 그때그때 다시 읽는다 — 방금 정하신 비밀번호가 바로 먹혀야 한다
    return r if isinstance(r,dict) else None

def _pw_verify(pw):
    rec=_pw_rec()
    if not rec: return False
    try:
        s=rec.get("솔트") or ""; want=rec.get("해시") or ""
        if not s or not want: return False
        it=int(rec.get("반복") or 240000)
        got=hashlib.pbkdf2_hmac('sha256',(pw or "").encode('utf-8'),bytes.fromhex(s),it).hex()
        return hmac.compare_digest(got,want)
    except Exception:
        return False

def _fail_key(ip):
    """잠금을 셀 단위. ★IPv6 는 주소 하나가 아니라 대역(/64)으로 센다 —
       주소를 하나씩 바꿔 가며 시도하면 주소별 잠금은 그냥 무력화되기 때문이다."""
    s=(ip or "").strip()
    if ":" in s:
        p=s.split("%")[0].split(":")
        return "v6:"+":".join(p[:4])          # 앞 64비트만
    return s

def _fail_sweep():
    """지난 항목 청소 + 상한. ★안 하면 주소를 바꿔 가며 두드리는 것만으로 기억이 무한히 불어난다."""
    now=time.time()
    for k in [k for k,v in _FAILS.items() if v[2]<now-FAIL_KEEP]: _FAILS.pop(k,None)
    if len(_FAILS)>FAIL_KEYS_MAX:
        for k,_ in sorted(_FAILS.items(), key=lambda kv: kv[1][2])[:len(_FAILS)-FAIL_KEYS_MAX]:
            _FAILS.pop(k,None)

def _delay_for(ip):
    """이번 시도에 걸 ★지연 시간(초). 0 이면 즉답.
       ★잠금이 아니다 — 언제든 맞는 비밀번호를 넣으면 들어가진다. 늦게 답할 뿐이다.
       계단: 5회째부터 1s → 2s → 4s → 8s … ★최대 60s(그 이상 늘리면 사실상 잠금이 된다).
       ★어느 주소도 예외로 두지 않는다. 예외를 두면 중계가 한 겹 얹혔을 때 그 예외가
         전원에게 적용되어 비밀번호를 무제한으로 시도할 수 있게 된다.
       사무실 컴퓨터는 열쇠로 자동 로그인해 비밀번호를 칠 일이 없으므로, 지연을 만날 일이 없다."""
    now=time.time()
    f=_FAILS.get(_fail_key(ip))
    n=f[0] if (f and f[2]>now-FAIL_KEEP) else 0
    # 대역을 바꿔 가며 두드리는 경우 — 주소별 계단을 다 피해 가므로 전체 카운터도 함께 본다.
    g=_GLOBAL[0] if _GLOBAL[2]>now-FAIL_KEEP else 0
    n=max(n, g-(GLOBAL_MAX-FAIL_MAX) if g>=GLOBAL_MAX else 0)
    if n<FAIL_MAX: return 0
    return min(DELAY_MAX, 2**(n-FAIL_MAX))

def _fail_mark(ip):
    now=time.time(); k=_fail_key(ip)
    f=_FAILS.get(k) or [0,0,now]
    if f[2]<now-FAIL_KEEP: f[0]=0                     # 오래 조용했으면 계단을 처음부터
    f[0]+=1; f[2]=now; f[1]=0                         # ★잠금해제시각 칸은 이제 쓰지 않는다
    _FAILS[k]=f
    if _GLOBAL[2]<now-FAIL_KEEP: _GLOBAL[0]=0         # 조용한 시간이 지나면 초기화
    _GLOBAL[0]+=1; _GLOBAL[2]=now
    _fail_sweep()

def _fail_clear(ip):
    _FAILS.pop(_fail_key(ip),None); _GLOBAL[0]=0

VPN_EXE_NAME="tailscale.exe"    # 사설망 프로그램 — 주소를 이 프로그램에 직접 물어본다
VPN_ADAPTER_HINT="tailscale"    # 랜 카드 이름에 이 낱말이 들어 있으면 사설망 카드다

def _vpn_exe():
    """사설망(VPN) 프로그램의 위치. 없으면 빈 문자열(= 아직 안 깔려 있다)."""
    for d in (os.environ.get("ProgramFiles") or r"C:\Program Files",
              os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"):
        try:
            p=os.path.join(d,"Tailscale",VPN_EXE_NAME)
            if os.path.exists(p): return p
        except Exception: pass
    return ""

def _vpn_ip():
    """폰이 들어올 ★사설망(VPN) 주소. 돌려주는 값 = (주소, 못 연 사유).
       ★2026-08-27: 이름만 `_phone_ip` → `_vpn_ip` 로 바꿨다(본문 무수정).
         길이 둘(사설망·같은 와이파이)이 되었으므로, «폰 주소»라는 이름은 이제
         ★어느 길인지 고르는 함수(아래 `_phone_ip`)가 가져간다. 이 함수는 그중 «사설망 길» 담당이다.
       ① ★사설망 프로그램에 직접 물어본다 — 가장 정확하다(이름이 달라도, 카드가 여러 개여도 맞다).
       ② 안 되면 ★랜 카드 '이름'으로 지목한다.
       ③ 둘 다 안 되면 ★빈 문자열 — 그리고 ★사유를 두 가지로 갈라 알려 드린다
          (안 깔려 있다 / 깔려 있는데 아직 연결이 안 됐다). 목사님이 하실 일이 서로 다르기 때문이다.
       ★랜(공유기) 주소에는 절대 붙이지 않는다 — 같은 와이파이의 다른 기기에 보이면 안 된다.
       ★주소 숫자(100.으로 시작)로 고르지 않는다 — 그 대역은 ★통신사가 쓰는 대역과 같아서,
         인터넷 회선이 그 대역을 쓰는 집·교회에서는 ★엉뚱한 랜 카드를 사설망으로 착각한다.
       ★IPv4 만 쓴다. 사설망은 IPv6 주소도 주지만 여기서는 열지 않으므로, 안내에도 IPv4 만 적는다.
       ★church.py 의 _phone_addr() 와 ★같은 규칙이어야 한다 — 한쪽만 고치지 마라.
         카드에 적힌 주소와 실제로 열린 주소가 어긋나면 목사님이 헛걸음하신다."""
    exe=_vpn_exe(); installed=bool(exe)
    # ① 사설망 프로그램에 직접 물어본다
    try:
        out=subprocess.run([exe or "tailscale","ip","-4"],capture_output=True,text=True,
                           encoding='utf-8',errors='replace',timeout=10).stdout or ""
        installed=True                                      # 실행이 됐다 = 깔려 있다
        m=re.search(r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s*$", out, re.M)
        if m: return m.group(1), ""
    except FileNotFoundError: pass                          # 그 이름의 프로그램이 없다 = 안 깔려 있다
    except Exception: pass
    # ② 랜 카드 이름으로 지목 — 이름 안에 사설망 프로그램 이름이 있는 칸의 IPv4 를 쓴다
    try:
        out=subprocess.run(["ipconfig"],capture_output=True,text=True,
                           encoding='cp949',errors='replace',timeout=10).stdout or ""
        cur=""
        for ln in out.splitlines():
            if ln.strip() and not ln.startswith(" "): cur=ln          # 어댑터 제목 줄
            elif VPN_ADAPTER_HINT in cur.lower():
                m=re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", ln)
                if m and ("IPv4" in ln or "IP Address" in ln or "주소" in ln):
                    return m.group(1), ""
    except Exception: pass
    # ③ 못 찾았으면 열지 않는다 — 숫자만 보고 아무 카드에나 붙이지 않는다.
    #    (폰 접속을 못 여는 것이 ★잘못 여는 것보다 낫다.)
    # ★가리키는 곳은 ★화면의 카드다. 바깥 문서를 가리키면 목사님이 그 파일을 찾아 헤매신다.
    #   ★church.py 의 _phone_addr() 에 ★같은 문장이 있다(이중 상수) — 한쪽만 고치지 마라.
    #     들어온 길에 따라 다른 말이 나오면 그것만으로 목사님은 헷갈리신다.
    if installed:
        return "", "사설망(VPN)은 깔려 있지만 아직 연결되지 않았습니다 — 사설망 프로그램에서 로그인·연결을 마쳐 주세요."
    return "", "사설망(VPN)이 아직 깔려 있지 않습니다 — 「📱 폰 접속 설정」 카드에 설치 순서가 적혀 있습니다."

# ══════════════════════════════════════════════════════════════════════════════
# ★폰 접속 «길» 2가지 — 부채 4-2 이식분 (2026-08-27 · 오너 결정: 와이파이 먼저, 밖은 사설망)
#   "사설망"   = 사설망(VPN) 주소에만 연다. ★밖에서도 된다. 설치·로그인이 필요하다.
#   "와이파이" = 같은 공유기 안의 랜 주소에만 연다. ★설치 0회. 밖에서는 안 된다.
#   "자동"     = 사설망을 먼저 찾고, 없으면 와이파이로 연다.
#   ★기본값을 "사설망"으로 둔다 — 이미 폰 접속을 켜 두신 분이 업데이트만 했는데
#     어느 날 갑자기 교회 와이파이에 로그인 화면이 열려서는 안 된다. 와이파이는 ★직접 고르셔야 열린다.
PHONE_WAY_DEFAULT="사설망"
PHONE_WAYS=("사설망","와이파이","자동")

def _phone_way():
    """지금 고르신 폰 접속 방식. 설정에 없거나 모르는 값이면 ★기본값(사설망)으로 본다 —
       설정 파일의 오타 하나로 와이파이가 조용히 열리는 일은 없어야 한다.
       ★church.py 의 `_phone_way()` 와 ★같은 규칙이어야 한다 — 한쪽만 고치지 마라.
         (두 파일은 서로 import 하지 않는다. 그래서 ★기계 대조 시험으로 지킨다:
          시험대 `_실험/lane4_rule_parity.py` — 한쪽만 고치면 그 시험이 빨간불을 낸다.)"""
    w=(_cfg_live().get("폰접속방식") or "").strip()
    return w if w in PHONE_WAYS else PHONE_WAY_DEFAULT

def _is_lan_v4(ip):
    """이 주소가 ★사설 대역(RFC1918)인가 — 10. / 172.16~31. / 192.168. 만 참이다.
       ★공인(인터넷) 주소에는 어떤 경우에도 붙지 않는다 — 붙으면 세상 전체에 열린다.
       ★100.64~100.127 은 여기서 ★거짓이다. 그 대역은 통신사가 쓰는 대역과 같아서
         숫자만 보고 '내 랜'이라 부를 수 없다(사설망 주소는 숫자가 아니라 프로그램에 물어 고른다).
       ★169.254(주소를 못 받았을 때 스스로 붙이는 임시 주소)도 거짓 — 폰이 그리로는 못 온다.
       ★church.py 의 `_is_lan_v4()` 와 ★같은 규칙이어야 한다 — 한쪽만 고치지 마라."""
    try:
        p=[int(x) for x in (ip or "").split(".")]
    except Exception: return False
    if len(p)!=4 or any(x<0 or x>255 for x in p): return False
    if p[0]==10: return True
    if p[0]==172 and 16<=p[1]<=31: return True
    if p[0]==192 and p[1]==168: return True
    return False

def _is_cgnat_v4(ip):
    """100.64.0.0/10 — 사설망(Tailscale)이 나눠 주는 대역. ★사설망으로 찾았을 때만 인정한다.
       숫자만 보고 이 대역을 '내 랜'으로 삼으면, 이 대역을 쓰는 인터넷 회선에서 엉뚱한 카드를 연다."""
    try:
        p=[int(x) for x in (ip or "").split(".")]
    except Exception: return False
    return len(p)==4 and p[0]==100 and 64<=p[1]<=127

# 랜 주소를 찾을 때 ★건너뛰는 카드 이름. 가상 카드에 붙으면 주소는 사설 대역이지만
#   폰은 그 주소에 절대 닿지 못한다 — 있으나 마나 한 주소를 카드에 적어 드리게 된다.
LAN_SKIP_HINTS=("tailscale","vethernet","wsl","hyper-v","hyperv","virtualbox","vmware",
                "loopback","bluetooth","docker","가상","tap-","openvpn","zerotier","teredo")

def _lan_ip():
    """폰이 들어올 ★같은 와이파이(사설 랜) 주소. 돌려주는 값 = (주소, 못 연 사유).
       ① ★바깥으로 나갈 때 쓰이는 내 주소를 운영체제에 물어본다.
          (UDP 라서 ★실제로 나가는 것은 없다 — 어느 랜 카드로 나가는지만 물어보는 것이다.)
       ② 그게 안 되면 ipconfig 를 읽어 가상 카드를 걸러내고 사설 대역 하나를 고른다.
       ★어느 길로 찾았든 ★사설 대역이 아니면 버린다. 공유기 없이 인터넷에 바로 붙은
         컴퓨터라면 그 주소는 공인 주소이고, 거기에 열면 세상 전체에 로그인 화면이 열린다.
       ★church.py 의 `_lan_addr()` 와 ★같은 규칙이어야 한다 — 한쪽만 고치지 마라."""
    pub=""
    try:
        import socket as _sk          # ★이 파일 머리에는 socket 이 없다 — 여기서만 부른다(lane4 와 같은 방식)
        s=_sk.socket(_sk.AF_INET, _sk.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80)); ip=s.getsockname()[0]
        finally:
            s.close()
        if _is_lan_v4(ip): return ip,""
        if ip and ip!="0.0.0.0" and not ip.startswith("127."): pub=ip
    except Exception: pass
    try:
        out=subprocess.run(["ipconfig"],capture_output=True,text=True,
                           encoding='cp949',errors='replace',timeout=10).stdout or ""
        cur=""
        for ln in out.splitlines():
            if ln.strip() and not ln.startswith(" "): cur=ln.lower()       # 어댑터 제목 줄
            elif any(h in cur for h in LAN_SKIP_HINTS):                    # 가상·사설망 카드는 건너뛴다
                continue
            else:
                m=re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", ln)
                if m and ("IPv4" in ln or "IP Address" in ln or "주소" in ln):
                    if _is_lan_v4(m.group(1)): return m.group(1),""
    except Exception: pass
    if pub:
        return "", ("이 컴퓨터가 공유기 없이 인터넷에 바로 붙어 있는 것 같습니다 — "
                    "안전을 위해 같은 와이파이 방식으로는 열지 않았습니다(사설망 방식을 써 주세요).")
    return "", "같은 와이파이 주소를 찾지 못했습니다 — 컴퓨터가 공유기(와이파이·랜)에 연결돼 있는지 확인해 주세요."

def _phone_way_label(mode):
    """열린 길을 목사님 말로. 화면 어디에서나 ★같은 낱말을 쓰기 위한 한 곳이다."""
    return {"vpn":"사설망","wifi":"같은 와이파이"}.get(mode,"")

def _phone_ip():
    """폰이 들어올 주소. 돌려주는 값 = (주소, 못 연 사유, ★어느 길로 열렸는지).
       길 = "vpn"(사설망) · "wifi"(같은 와이파이) · ""(못 찾음).
       ★어느 길인지를 함께 돌려주는 이유 — 화면에 적어 드릴 안내문이 서로 정반대다.
         사설망은 "밖에서도 됩니다", 와이파이는 "교회 와이파이 안에서만 됩니다".
         이걸 안 돌려주면 안내문이 둘 중 하나는 반드시 거짓말이 된다.
       ★church.py 의 `_phone_addr()` 와 ★같은 규칙이어야 한다 — 한쪽만 고치지 마라."""
    way=_phone_way()
    if way=="와이파이":
        ip,why=_lan_ip()
        return (ip,"","wifi") if ip else ("",why,"")
    ip,vwhy=_vpn_ip()
    if ip: return ip,"","vpn"
    if way=="자동":
        lip,lwhy=_lan_ip()
        if lip: return lip,"","wifi"
        return "", f"{vwhy} 그리고 {lwhy}", ""
    return "",vwhy,""

def _phone_ips():
    """폰이 들어올 주소들. 돌려주는 값 = ([(주소, 길), …], 하나도 못 찾은 사유).
       ★위 `_phone_ip()` 와 다른 점은 ★하나가 아니라 ★전부를 돌려준다는 것 하나다.
       ★왜 이 함수가 따로 필요한가 (2026-08-27 · master 재정 — 앞선 권고의 결함 수정):
         「자동」은 사설망을 먼저 찾고 없으면 와이파이로 갔다. 그래서 사설망이 잡히면
         ★와이파이 주소는 아예 열리지 않았다. 그러면 ★같은 교회 와이파이에 있는 폰이라도
         Tailscale 이 꺼져 있으면 못 들어온다 — 목사님은 «왜 안 열리지» 만 겪으신다.
         ⇒ 「자동」은 ★둘 다 연다. 고르는 것은 프로그램이 아니라 ★폰이 하게 둔다.
       ★「사설망」·「와이파이」를 ★직접 고르신 경우는 그 길 ★하나만 연다 — 고르신 뜻을 넘지 않는다."""
    way=_phone_way()
    if way=="와이파이":
        ip,why=_lan_ip()
        return ([(ip,"wifi")] if ip else []), ("" if ip else why)
    if way=="사설망":
        ip,why=_vpn_ip()
        return ([(ip,"vpn")] if ip else []), ("" if ip else why)
    out=[]                                        # ── 자동 = 찾아지는 길을 ★모두 ──
    vip,vwhy=_vpn_ip()
    if vip: out.append((vip,"vpn"))
    lip,lwhy=_lan_ip()
    if lip: out.append((lip,"wifi"))
    if out: return out,""
    return [], f"{vwhy} 그리고 {lwhy}"

FORBIDDEN_BIND=("0.0.0.0","::","")   # ★공용 바인딩 금지 — 이 한 줄이 미래에 조용히 되돌아오는 자리다

def _bind_plan():
    """어느 주소에 열지 결정한다. 돌려주는 값 = (주소목록, 폰포트를 못 연 사유, ★[(주소,길), …]).
       ① 127.0.0.1 은 ★항상 연다 — 사무실 컴퓨터의 일상 동선이 이 주소다.
       ② 폰 주소는 ★세 가지가 모두 참일 때만 연다 — 자물쇠 3중 조건이다.
            ㉮ 폰 접속을 켜셨고 · ㉯ 비밀번호가 있고 · ㉰ 주소를 실제로 찾았다.
          ★셋 중 하나라도 없으면 폰 포트는 열지 않는다. 특히 ㉯가 없으면 절대 안 연다 —
            비밀번호 없이 열리면 그 순간 명부가 그냥 공개된다.
       ★공용 바인딩(0.0.0.0 · ::)은 어떤 방식에서도 쓰지 않는다. 와이파이 방식이라 해도
         ★랜 카드의 구체적 주소 하나(예 192.168.0.7)에만 붙인다 — 그래야 그 카드 말고는
         어디에도 나타나지 않고, 나중에 카드가 하나 더 생겨도 조용히 번지지 않는다.
       ★마지막 자물쇠 — 찾은 주소가 사설 대역이 아니면 ★버린다.
         위쪽에서 아무리 잘못 찾아 와도 여기서 걸린다(공인 주소에 붙는 사고는 되돌릴 수 없다).
       ★주소가 둘이 되어도 자물쇠는 ★주소마다 따로 건다 (2026-08-27).
         「하나가 통과했으니 나머지도」가 아니다 — ★한 줄로 다 여는 판단을 만들지 않는다."""
    hosts=["127.0.0.1"]; why=""; ways=[]
    cf=_cfg_live()
    if cf.get("폰접속허용"):
        if not isinstance(cf.get("폰비밀번호"),dict):
            why="비밀번호가 아직 없습니다 — 「폰 접속 설정」 카드에서 먼저 정해 주세요."
        else:
            found,fwhy=_phone_ips(); bad=[]
            for ip,m in found:
                # ★사설망 주소만 100.64~ 대역이 허용된다. 와이파이로 찾은 주소가 그 대역이면
                #   그것은 통신사 대역일 수 있으므로 ★여기서 떨어진다(종전 판단 그대로).
                if ip and (_is_lan_v4(ip) or (m=="vpn" and _is_cgnat_v4(ip))):
                    if ip not in hosts:                 # 두 길이 같은 주소를 가리키면 한 번만 연다
                        hosts.append(ip); ways.append((ip,m))
                elif ip:
                    bad.append(ip)
            if not ways:
                if bad:
                    why=(f"찾은 주소({' · '.join(bad)})가 사설 대역이 아니라 열지 않았습니다 — "
                         "공인 주소에는 붙지 않습니다(그 주소는 인터넷 전체에 열립니다).")
                else:
                    why=fwhy or "폰에서 들어오실 주소를 찾지 못했습니다 — 「📱 폰 접속 설정」 카드에서 상태를 확인해 주세요."
    return hosts, why, ways

def _cookie_token(header):
    for part in (header or "").split(";"):
        k,_,v=part.strip().partition("=")
        if k==COOKIE_NAME: return v.strip()
    return ""

def _allowed_hosts():
    """Host 머리글 화이트리스트 — 우리가 실제로 바인딩한 주소만.
       ★이걸 검사하지 않으면 DNS 재바인딩으로 남의 웹사이트가 우리 주소인 척할 수 있다."""
    out=set()
    for h in (_BOUND or ["127.0.0.1"]):
        out.add(f"{h}:{PORT}"); out.add(h)
    out.add(f"localhost:{PORT}"); out.add("localhost")
    return out

def _via_proxy(handler):
    """중계(프록시)를 거쳐 들어온 요청인가.
       ★머리글은 '이 사람이 누구다'의 근거로는 못 쓰지만 '이 요청은 거절한다'의 근거로는 쓸 수 있다."""
    return any(handler.headers.get(h) for h in PROXY_HEADERS)

def _is_https(handler):
    """이 요청이 https 로 들어왔는가. 우리 서버는 http 로만 듣지만, 앞에 https 중계가 붙으면
       그 사실이 머리글에 남는다. ★이 머리글을 믿어서 문을 여는 게 아니라 ★쿠키를 더 조이는 데만 쓴다 —
       속아 봐야 쿠키가 더 엄격해질 뿐이라 안전한 방향의 신뢰다."""
    if (handler.headers.get("X-Forwarded-Proto") or "").strip().lower()=="https": return True
    for k in ("Origin","Referer"):
        if (handler.headers.get(k) or "").strip().lower().startswith("https://"): return True
    return False

def _cookie_attrs(handler):
    # ★Secure 를 언제 붙이고 언제 빼는지: 사설망 주소에 직접 붙는 기본 경로는 http 라서 붙이면
    #   쿠키가 저장되지 않아 로그인 자체가 막힌다. 그러나 https 로 들어온 요청이라면 반드시 붙인다
    #   (붙이지 않으면 그 쿠키가 http 로도 나가 남의 손에 들어갈 수 있다).
    return "; Secure" if _is_https(handler) else ""

def _csrf_ok(handler):
    """이 POST 가 우리 화면에서 온 것인가. 넷 중 하나라도 어긋나면 거부한다.
       (목사님이 아무 웹사이트나 방문했을 때 그 사이트가 몰래 명령을 실행시키는 것을 막는다)
       ★주의 — "머리글은 위조될 수 있으니 안 본다"는 ★신뢰용엔 맞고 거절용엔 거꾸로다.
         브라우저는 Origin 을 위조하지 못한다. 머리글은 "이 사람이 누구다"의 근거로는 못 쓰지만
         "이 요청은 거절한다"의 근거로는 쓸 수 있다. 그래서 여기서는 ★거절에만 쓴다."""
    h=handler.headers
    if (h.get(CSRF_HEADER) or "")!="1": return False          # 단순 폼은 이 머리글을 못 붙인다
    ct=(h.get("Content-Type") or "").split(";")[0].strip().lower()
    if ct!="application/json": return False                    # text/plain 폼 공격 차단
    ok=_allowed_hosts()
    if (h.get("Host") or "").strip().lower() not in ok: return False
    for k in ("Origin","Referer"):
        v=(h.get(k) or "").strip()
        if not v: continue
        try:
            from urllib.parse import urlparse
            if (urlparse(v).netloc or "").lower() not in ok: return False
        except Exception: return False
    return True

# ══════════════════════════════════════════════════════════════════════════════
# 📱 QR 그림 만들기 — ★의존성 0 (파이썬 내장만 쓴다)
# ══════════════════════════════════════════════════════════════════════════════
#   ★왜 남의 꾸러미를 안 쓰나: 새 파일이 하나 생기는 순간 ★발행 6통로에 전부 등재해야 하고
#     하나만 빠져도 «내 컴퓨터에서는 되는데 목사님 컴퓨터에서는 QR 이 안 나오는» 사고가 된다.
#     QR 은 규격이 공개돼 있고 우리가 실을 것은 80자 안쪽 주소 하나라 직접 만드는 편이 싸다.
#   ★검증 방법(중요): 이 인코더는 ★OpenCV 판독기·OpenCV 인코더와 대조해 검증했다.
#     내 코드가 내 코드를 검사하면 그것은 검증이 아니다 — 실제로 «형식정보 비트 순서»를
#     세상과 반대로 쓰고 있었고, 내 판독기끼리는 맞아떨어져 ★못 잡을 뻔했다.
#     대조군(같은 글자를 OpenCV 인코더로도 만들어 같은 판독기에 태우기)까지 세워서 갈랐다.
#     시험대: `_실험/qr_selftest.py`
#
#   ★버전 9 까지만 둔다 — 버전 10 부터 바이트모드 «길이 칸»이 8비트→16비트로 바뀐다.
#     그 한 줄을 안 바꾸면 판독기가 길이를 잘못 읽어 엉뚱한 데까지 읽으러 간다(실제로 그렇게 터졌다).
#     버전 9 는 180자를 담는다 — 우리가 실을 「http://주소:8899/q?t=열쇠」는 80자 안쪽이라 넉넉하다.
_QR_M={1:(10,[(1,16)]), 2:(16,[(1,28)]), 3:(26,[(1,44)]), 4:(18,[(2,32)]),
       5:(24,[(2,43)]), 6:(16,[(4,27)]), 7:(18,[(4,31)]), 8:(22,[(2,38),(2,39)]),
       9:(22,[(3,36),(2,37)])}                       # 버전:(블록당 오류정정 코드워드, [(블록수, 데이터 코드워드)])
_QR_ALIGN={1:[],2:[6,18],3:[6,22],4:[6,26],5:[6,30],6:[6,34],7:[6,22,38],8:[6,24,42],9:[6,26,46]}
_QR_REM={1:0,2:7,3:7,4:7,5:7,6:7,7:0,8:0,9:0}        # 맨 끝에 채우는 나머지 비트

def _qr_gf():
    exp=[0]*512; log=[0]*256; x=1
    for i in range(255):
        exp[i]=x; log[x]=i
        x<<=1
        if x&0x100: x^=0x11D
    for i in range(255,512): exp[i]=exp[i-255]
    return exp,log
_QGEXP,_QGLOG=_qr_gf()

def _qr_rs(data,n):
    """오류정정 코드워드 — 이게 있어서 QR 이 좀 가려지거나 구겨져도 읽힌다."""
    g=[1]
    for i in range(n):
        g2=[0]*(len(g)+1)
        for j,c in enumerate(g):
            g2[j]^=c; g2[j+1]^=(_QGEXP[(_QGLOG[c]+i)%255] if c else 0)
        g=g2
    res=list(data)+[0]*n
    for i in range(len(data)):
        c=res[i]
        if not c: continue
        lc=_QGLOG[c]
        for j,gc in enumerate(g):
            res[i+j]^=_QGEXP[(_QGLOG[gc]+lc)%255] if gc else 0
    return res[len(data):]

def _qr_bch_fmt(fmt):
    v=fmt<<10
    for i in range(4,-1,-1):
        if v&(1<<(i+10)): v^=0b10100110111<<i
    return ((fmt<<10)|v)^0b101010000010010

def _qr_bch_ver(ver):
    v=ver<<12
    for i in range(5,-1,-1):
        if v&(1<<(i+12)): v^=0b1111100100101<<i
    return (ver<<12)|v

def _qr_matrix(text):
    """글자 → QR 격자(0/1). 바이트 모드 · 오류정정 M 등급."""
    data=text.encode('utf-8'); ver=None
    for v in sorted(_QR_M):
        if 4+8+len(data)*8 <= sum(b*c for b,c in _QR_M[v][1])*8: ver=v; break
    if ver is None: raise ValueError("QR 에 담기엔 주소가 너무 깁니다")
    ecn,blocks=_QR_M[ver]; total=sum(b*c for b,c in blocks)
    bits=[]
    def put(val,n):
        for i in range(n-1,-1,-1): bits.append((val>>i)&1)
    put(4,4); put(len(data),8)                    # 모드=바이트(4) · 길이(8비트, 버전 1~9)
    for b in data: put(b,8)
    put(0,min(4,total*8-len(bits)))               # 종료자
    while len(bits)%8: bits.append(0)
    cw=[int("".join(str(x) for x in bits[i:i+8]),2) for i in range(0,len(bits),8)]
    pad=[0xEC,0x11]; i=0
    while len(cw)<total: cw.append(pad[i%2]); i+=1
    dbl=[]; ebl=[]; p=0
    for cnt,sz in blocks:
        for _ in range(cnt):
            d=cw[p:p+sz]; p+=sz; dbl.append(d); ebl.append(_qr_rs(d,ecn))
    out=[]                                        # 끼워 짜기(interleave)
    for i in range(max(len(b) for b in dbl)):
        for b in dbl:
            if i<len(b): out.append(b[i])
    for i in range(ecn):
        for b in ebl: out.append(b[i])
    final=[]
    for b in out:
        for i in range(7,-1,-1): final.append((b>>i)&1)
    final+=[0]*_QR_REM[ver]

    n=ver*4+17
    m=[[0]*n for _ in range(n)]; res=[[0]*n for _ in range(n)]
    for (fr,fc) in ((0,0),(0,n-7),(n-7,0)):       # 세 모서리의 «찾기 무늬»
        for dr in range(-1,8):
            for dc in range(-1,8):
                rr,cc=fr+dr,fc+dc
                if 0<=rr<n and 0<=cc<n:
                    res[rr][cc]=1
                    inb=(0<=dr<7 and 0<=dc<7)
                    m[rr][cc]=1 if (inb and (dr in(0,6) or dc in(0,6) or (2<=dr<=4 and 2<=dc<=4))) else 0
    for i in range(8,n-8):                        # 타이밍 무늬
        m[6][i]=m[i][6]=1-(i%2); res[6][i]=res[i][6]=1
    for r in _QR_ALIGN[ver]:                      # 정렬 무늬
        for c in _QR_ALIGN[ver]:
            if (r<9 and c<9) or (r<9 and c>n-10) or (r>n-10 and c<9): continue
            for dr in range(-2,3):
                for dc in range(-2,3):
                    m[r+dr][c+dc]=1 if (abs(dr)==2 or abs(dc)==2 or (dr==0 and dc==0)) else 0
                    res[r+dr][c+dc]=1
    m[n-8][8]=1; res[n-8][8]=1                    # 늘 검은 칸
    for i in range(9):
        if i!=6: res[8][i]=res[i][8]=1
    res[8][8]=1
    for i in range(8): res[8][n-1-i]=res[n-1-i][8]=1
    if ver>=7:
        for i in range(6):
            for j in range(3): res[n-11+j][i]=1; res[i][n-11+j]=1
    idx=0; up=True; col=n-1                       # 데이터 채우기(오른쪽 아래에서 지그재그)
    while col>0:
        if col==6: col-=1                         # 6번 세로줄은 타이밍 무늬라 건너뛴다
        for r in (range(n-1,-1,-1) if up else range(n)):
            for c in (col,col-1):
                if res[r][c]: continue
                m[r][c]=final[idx] if idx<len(final) else 0; idx+=1
        up=not up; col-=2

    def mk(k,r,c):
        return [ (r+c)%2==0, r%2==0, c%3==0, (r+c)%3==0, (r//2+c//3)%2==0,
                 (r*c)%2+(r*c)%3==0, ((r*c)%2+(r*c)%3)%2==0, ((r+c)%2+(r*c)%3)%2==0 ][k]
    def penalty(g):
        s=0
        lines=list(g)+[list(x) for x in zip(*g)]
        for line in lines:                                    # ①같은 색 5칸 이상
            run=1
            for i in range(1,n):
                if line[i]==line[i-1]: run+=1
                else:
                    if run>=5: s+=3+(run-5)
                    run=1
            if run>=5: s+=3+(run-5)
        for r in range(n-1):                                  # ②2×2 같은 색
            for c in range(n-1):
                if g[r][c]==g[r][c+1]==g[r+1][c]==g[r+1][c+1]: s+=3
        p1=[1,0,1,1,1,0,1,0,0,0,0]; p2=[0,0,0,0,1,0,1,1,1,0,1]
        for line in lines:                                    # ③찾기 무늬를 닮은 줄
            for i in range(n-10):
                if line[i:i+11]==p1 or line[i:i+11]==p2: s+=40
        s+=10*(abs(sum(sum(r) for r in g)*100//(n*n)-50)//5)  # ④검은 칸 비율
        return s
    best=None
    for k in range(8):                            # 마스크 8개를 다 씌워 보고 ★벌점이 낮은 것을 고른다
        g=[[m[r][c]^(1 if (not res[r][c]) and mk(k,r,c) else 0) for c in range(n)] for r in range(n)]
        # ★형식정보 — 자리와 비트 순서는 «내 규약»이 아니라 표준이다. ★첫 자리에 ★최상위 비트.
        #   이걸 뒤집어 쓰면 내 판독기끼리는 맞지만 ★세상의 판독기는 하나도 못 읽는다(실제로 그랬다).
        f=_qr_bch_fmt((0b00<<3)|k)                # 오류정정 M 등급 = 00
        s1=[(8,0),(8,1),(8,2),(8,3),(8,4),(8,5),(8,7),(8,8),(7,8),(5,8),(4,8),(3,8),(2,8),(1,8),(0,8)]
        s2=[(n-1,8),(n-2,8),(n-3,8),(n-4,8),(n-5,8),(n-6,8),(n-7,8),
            (8,n-8),(8,n-7),(8,n-6),(8,n-5),(8,n-4),(8,n-3),(8,n-2),(8,n-1)]
        for i in range(15):
            b=(f>>(14-i))&1
            g[s1[i][0]][s1[i][1]]=b; g[s2[i][0]][s2[i][1]]=b
        g[n-8][8]=1                               # ★늘 검은 칸(어느 사본에도 들지 않는다)
        if ver>=7:
            vb=_qr_bch_ver(ver)
            for i in range(18):
                b=(vb>>i)&1
                g[i//3][n-11+i%3]=b; g[n-11+i%3][i//3]=b
        p=penalty(g)
        if best is None or p<best[0]: best=(p,g)
    return best[1]

def _qr_svg(text, px=8, quiet=4):
    """QR 을 SVG 그림으로. ★확대해도 안 깨진다 — 폰 카메라가 화면의 QR 을 읽을 때 이게 중요하다.
       ★같은 색 칸을 가로로 묶어 한 조각으로 그린다(칸마다 그리면 글자 수가 몇 배가 된다)."""
    mat=_qr_matrix(text); n=len(mat); side=(n+quiet*2)*px; d=[]
    for r in range(n):
        c=0
        while c<n:
            if mat[r][c]:
                s=c
                while c<n and mat[r][c]: c+=1
                d.append(f"M{(s+quiet)*px} {(r+quiet)*px}h{(c-s)*px}v{px}h-{(c-s)*px}z")
            else: c+=1
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{side}" height="{side}" '
            f'viewBox="0 0 {side} {side}" shape-rendering="crispEdges" role="img" '
            f'aria-label="폰 접속 QR"><rect width="{side}" height="{side}" fill="#fff"/>'
            f'<path fill="#000" d="{"".join(d)}"/></svg>')

def _png(pix, w, h):
    """작은 PNG 하나 만들기 — 홈 화면 아이콘용. ★zlib·struct 는 파이썬 내장이라 새 꾸러미가 없다.
       pix = 행별 (R,G,B) 목록. 아이폰은 SVG 아이콘을 못 읽어서 PNG 가 필요하다."""
    import zlib as _z, struct as _s
    raw=b"".join(b"\x00"+bytes(v for p in row for v in p) for row in pix)
    def chunk(tag,data):
        return _s.pack(">I",len(data))+tag+data+_s.pack(">I",_z.crc32(tag+data)&0xffffffff)
    return (b"\x89PNG\r\n\x1a\n"
            +chunk(b"IHDR",_s.pack(">IIBBBBB",w,h,8,2,0,0,0))
            +chunk(b"IDAT",_z.compress(raw,9))+chunk(b"IEND",b""))

_ICON_CACHE={}
def _app_icon(size=192):
    """교회 아이콘 — 초록 바탕에 흰 십자가. 폰 홈 화면에서 이 그림을 누르면 프로그램이 열린다.
       ★사진이 아니라 ★그려서 만든다 — 파일을 하나도 늘리지 않기 위해서다(발행 6통로 무접촉).
       ★한 번 그린 것은 기억해 둔다 (2026-08-29) — 512 짜리는 픽셀 262,144 개를 파이썬으로 그려
         ★1.5초가 걸렸다. 그림은 크기마다 ★언제나 같으므로 다시 그릴 이유가 없다.
         (크기는 48~512 로 이미 제한돼 있어 이 기억이 무한히 커지지 않는다 — 최대 465칸)"""
    _hit=_ICON_CACHE.get(size)
    if _hit is not None: return _hit
    bg=(31,110,90); fg=(255,255,255); s=size
    bar=max(2,s//9); half=bar//2; cy=int(s*0.42); top=int(s*0.16); bot=int(s*0.84)
    rows=[]
    for y in range(s):
        row=[]
        for x in range(s):
            on=((top<=y<=bot and abs(x-s//2)<=half) or         # 세로 기둥
                (abs(y-cy)<=half and abs(x-s//2)<=int(s*0.20)))# 가로 팔
            row.append(fg if on else bg)
        rows.append(row)
    _ICON_CACHE[size]=_png(rows,s,s)
    return _ICON_CACHE[size]

def _way_note(mode):
    """길마다 «무엇이 필요한지»를 한 줄로. ★목사님이 QR 을 잘못 고르시면 안 열리고 원인을 모르신다 —
       그래서 라벨에 ★필요한 것을 반드시 적는다(master 지시 2-1)."""
    if mode=="wifi":
        return ("교회·집에서", "같은 와이파이에 연결된 폰 · 앱 설치 필요 없음",
                "밖에서는 열리지 않습니다")
    if mode=="vpn":
        return ("밖에서도", "폰에 사설망(Tailscale) 앱이 깔려 있고 연결돼 있어야 함",
                "심방지·이동 중에도 열립니다")
    return ("폰 접속","","")

ACTIONS=[
 # group, cmd, title, icon, fields[(name,label,placeholder,required)]
 ("목양","member-add","교우 등록·수정 & 조회 (한 카드로)","🙌",[("name","이름","",1),("role","직분 (권찰/집사/권사/안수집사/장로 등)","",0),("officedate","직분 임직·취임일 (직분 바뀔 때만)","",0),("cell","구역(셀)","",0),("leader","인도자","",0),("tel","연락처","",0),("addr","주소","",0),("birth","생년월일","",0),("birthtype","생일 양력/음력 (양력/음력)","",0),("marital","결혼 상태 (미혼/기혼/사별/이혼)","",0),("wedding","결혼기념일","",0),("edu","학력","",0),("job","직장","",0),("car","차량","",0),("baptismdate","세례일","",0),("catechism","학습일","",0),("infantbaptism","유아세례일","",0),("confirm","입교일","",0),("regpath","등록 경로 (초신자 등록/타교회 전입)","",0),("prevchurch","이전 교회","",0),("transferdate","전입일","",0),("family","가정 식구 (이름:관계 ; 로 구분 · 예: 김영희:아내; 홍길동:아들; 홍부모:부모)","",0),("memo","메모","",0)],"한 카드로 등록·수정·조회를 다 합니다. ▸이름만 넣고 실행 = 조회. ▸새 이름 + 필요한 칸 = 등록(모든 칸을 다 채울 필요 없습니다). ▸이미 등록된 교우 + 고칠 칸만 = 그 칸만 수정되고 나머지는 그대로 보존(안전). ▸직분을 새로 넣으면 '직분 연혁'으로 쌓이고 임직일을 함께 넣으면 그 날짜로 기록됩니다."),
 ("목양","member-import","교인 명단 한 번에 등록 (엑셀·CSV) 📥","📥",[("file","엑셀·CSV 파일 (프로그램 폴더에 두고 파일 이름만 넣으셔도 됩니다)","교인명단.xlsx",1),("apply","실제로 등록 (확인 후 1 · 비워두면 미리보기)","",0),("dup","이미 등록된 분 (비우면 건너뜀 · 보완 = 빈 칸만 채움)","",0),("sheet","시트 이름 (여러 장일 때만)","",0)],"이미 엑셀·한글로 갖고 계신 교인 명단을 통째로 불러옵니다. 한 분씩 입력하지 않으셔도 됩니다. ▸★이 카드로 들어오신 분은 모두 «기존 성도»로 등록됩니다 — 처음 설치하실 때 넣으시는 명단은 당연히 이미 다니시던 분들이기 때문입니다. 그래서 새가족 수에 섞이지 않습니다. ▸새로 나오신 분은 이 카드가 아니라 '새가족 등록' 카드로 넣어 주세요(정착 관리가 시작됩니다). ▸열 제목이 '성명·휴대폰·구역(셀)'처럼 달라도 알아서 맞춰 드립니다(이름 칸만 있으면 됩니다). ▸처음 실행하면 '미리보기'라 자료가 바뀌지 않습니다 — 몇 명이 등록될지 먼저 확인하세요. ▸확인 후 '실제로 등록'에 1을 넣으면 등록되며, 그 직전에 자동으로 백업합니다. ▸이미 등록된 분은 기본적으로 건너뛰고, '보완'을 넣으면 비어 있는 칸만 채웁니다(기존 정보는 절대 덮어쓰지 않습니다)."),
 ("목양","member-glance","👤 성도 한눈에 보기 (신앙생활 종합)","👤",[("name","성도 이름","",1)],"이름을 넣으시면 그 성도의 출석·헌금·직분·생일·가족·성례·심방·기도제목을 한 화면에 모아 보여 드립니다. ▸맨 위 «한눈에» 한 줄로 상태를 먼저 알려 드립니다. ▸출석은 최근 12주를 막대로, 헌금은 월별 흐름과 마지막 헌금일을 보여 드립니다. ▸가족을 등록해 두셨으면 가계도로 그려 드립니다. ▸★등급을 매기지 않습니다 — 숫자만 보여 드리고 판단은 목사님께 남깁니다. ▸인쇄해 들고 가실 것은 아래 '교인 목양 카드'입니다."),
 ("목양","member-roster","📜 교인 명단 — 교회 등록순 · 가나다순","📜",[("sort","정렬 (비우면 «교회 등록순» · «가나다» 라고 적으시면 이름순 · «최근» 이라고 적으시면 최근 등록순)","",0),("cell","구역(셀) (비우면 전체)","",0)],"우리 교회에 ★먼저 오신 분부터 차례로 보여 드립니다. ▸등록번호는 그분이 교회에 ★처음 오신 날입니다 — 2006년 8월 2일에 오셨으면 등록번호가 20060802 입니다. ▸그래서 «우리 교회에 누가 가장 먼저 오셨는지 · 누가 오래 다니셨는지»가 한눈에 보입니다(맨 아래에 가장 먼저 오신 분을 따로 적어 드립니다). ▸이름으로 찾으실 때는 «정렬» 칸에 «가나다» 라고 적으시면 이름순으로 바뀝니다. ▸«최근» 이라고 적으시면 최근에 오신 분부터 봅니다. ▸★등록일이 아직 비어 있는 분은 순서에 넣을 수 없어 맨 아래에 따로 몇 분인지 알려 드립니다 — 조용히 빠뜨리지 않습니다."),
 ("목양","sms-open","📱 폰에서 문자 앱 열기","📱",[("names","받으실 분 이름 (여러 분이면 ; 로 구분 · 예: 김동철; 이영희)","",0),("text","문구 (비우면 문구 없이 · 다른 카드에서 만든 축하 문구를 붙여 넣으셔도 됩니다)","",0),("cell","구역(셀) 전체에게 (이름 대신 구역 이름만 넣으셔도 됩니다)","",0)],"심방 길에서 폰으로 바로 문자를 보내실 수 있게, 받으실 분과 문구가 ★미리 채워진 «문자 앱 여는 주소»를 만들어 드립니다. ▸★2026-08-28 기준, ★실제 폰에서 문자 앱이 뜨는 것은 아직 확인하지 못했습니다 — 그래서 «열립니다»라고 적지 않습니다. 폰에서 한 번 눌러 보시고 안 되면 알려 주십시오. ▸★프로그램이 문자를 보내지 않습니다 — 이 단추가 하는 일은 «문자 앱을 여는 주소를 만드는 것»까지이고, ★보내기는 목사님이 문자 앱에서 직접 누르셔야 합니다. ▸그래서 문자 발송 업체를 쓰지 않고, ★이 프로그램 때문에 드는 돈은 없습니다(문자 요금 자체는 목사님 휴대폰 요금제대로입니다). ▸★사무실 컴퓨터에는 문자 앱이 없어 열리지 않을 것입니다 — 폰에서 눌러 주세요. 컴퓨터에서는 문구를 복사해 쓰시면 됩니다. ▸연락처가 비어 있는 분은 단추를 못 만들어 드리므로, 몇 분인지 이름과 함께 알려 드립니다. ▸'생일·결혼기념일 축하'나 '축하·위로 문자'에서 만든 문구를 그대로 붙여 넣으시면 됩니다."),
 ("목양","member-card","교인 목양 카드 (인쇄용 한 장) 🪪","🪪",[("name","교인 이름","",1)],"바로 위 '교우 등록·수정 & 조회'에 담긴 모든 정보(생일 양/음·직분 연혁·성례·전교회·학력·직장 등)와 가족·심방이력·기도제목·양육·경조사·헌금요약·최근출석까지 — 한 사람의 모든 것을 인쇄용 문서 한 장으로 만듭니다. 심방 전 파악용. ▸이름만 넣어 '조회'한 결과의 '📄 목양 카드 만들기' 버튼으로도 바로 만들 수 있습니다. (조회=화면 요약 / 이 카드=인쇄용 문서)"),
 ("목양","member-transfer","교적 이동(전입·전출·이명) + 대장","↔️",[("kind","종류(전입/전출/이명)","전출",0),("name","이름 (비우면 대장만 봅니다)","",0),("date","날짜","",0),("church","상대 교회","",0),("memo","사유","",0)],"이름을 넣으면 전입·전출·이명을 기록하고 교인 상태를 갱신하며, 항상 '교적 이동 대장'을 함께 출력합니다. 이름을 비우면 대장만 봅니다. 이명증서는 '증명서 발급'에서."),
 ("목양","visit-add","심방 센터 (브리핑·기록·현황·지침)","📝",[("name","이름 (비우면 심방 센터: 현황·지침 바로가기)","",0),("kind","구분(정기/춘계대심방/추계대심방/입원/새가족/구역(셀))","정기",0),("word","전한 말씀(다녀와서 기록)","",0),("prayer","기도제목(;로 구분)","",0),("note","나눈 내용","",0),("followup","후속","",0)],"한 카드로 심방의 모든 것을 챙깁니다. ▸이름을 비우고 실행 = 심방 센터(대심방 현황·상황별 지침 바로가기 버튼). ▸이름만 넣고 실행 = 그 교우의 지난 말씀·기도제목 브리핑(반복 방지) + 대심방 현황·지침·목양 카드 버튼. ▸심방 다녀와서 '전한 말씀·기도제목·나눈 내용'을 채워 실행 = 기록."),
 ("목양","newfamily-add","새가족 등록","🌱",[("name","이름","",1),("tel","연락처","",0),("leader","인도자","",0),("cell","구역(셀)","",0)],"★새로 나오신 분만 이 카드로 넣어 주세요 — 정착 관리(주차별 양육·미이행 경고)가 시작됩니다. 이미 다니시던 기존 교인은 위의 '교우 등록·수정' 카드로 넣으셔야 새가족 수에 섞이지 않습니다."),
 ("목양","newfamily-board","새가족 정착 현황","📊",[],"'새가족 등록' 카드로 넣으신 분들의 정착 진행 상황입니다. ▸등록일이 최근이라는 이유로 기존 교인이 여기 올라오지는 않습니다."),
 ("목양","member-restore","기존 성도로 일괄 정리 🔁","🔁",[("names","이름 (;로 구분 · 비우면 전체 대상 · 비우고 실행하면 미리보기)","",0),("apply","실제로 정리 (확인 후 1 · 비워두면 미리보기)","",0),("undo","되돌리기 (직전 정리를 원래대로 · 1)","",0)],"잘못 '새가족'으로 들어간 분들을 기존 성도로 되돌립니다. ▸처음 설치하셨을 때 기존 교인이 새가족으로 표시되셨다면 이 카드로 정리하세요. ▸★비우고 실행하면 미리보기입니다 — 몇 명이 어떻게 바뀌는지만 보여드리고 자료는 그대로입니다. ▸확인 후 '실제로 정리'에 1을 넣으면 바뀌며, 그 직전에 자동 백업합니다. ▸★양육·정착 기록이 있는 분(정말 새로 오신 분일 수 있는 분)은 자동으로 빼 드립니다 — 그분도 정리하시려면 이름을 직접 적으세요. ▸정리 후에도 '되돌리기'에 1을 넣으면 원래대로 돌아갑니다."),
 ("목양","care","돌봄 필요 성도","💗",[("days","기준일수","90",0)],"오래 못 뵌 성도를 프로그램이 찾아 드립니다 — 심방 기록을 기준으로 기준일수(기본 90일) 넘게 만나지 못한 분들의 명단과 연락처를 뽑아 드립니다. ▸바쁘시다 보면 조용한 분일수록 더 오래 잊히기 쉽습니다. 이 카드가 그 분들을 대신 기억해 드립니다."),
 ("목양","attend-check","주간 출석 체크 ✅","✅",[("names","참석자 이름 (;로 구분 · 비우면 현황보기)","",0),("date","날짜(비우면 오늘)","",0),("service","예배","주일예배",0)],"매주 예배 참석자 이름을 ;로 구분해 넣으면 기록됩니다. 몇 주 쌓이면 '장기결석자 찾기'가 오래 안 나오신 분을 자동으로 찾아 드립니다."),
 ("목양","attend-board","✅ 구역(셀)별 52주 출석 체크판","✅",[("group","구역(셀) 이름 (비우고 실행하시면 구역 목록을 보여 드립니다)","",0),("names","참석하신 분 이름 (; 로 구분 · 예: 김철수; 이영희)","",0),("date","날짜 (비우면 오늘)","",0),("service","예배 (비우면 주일예배)","",0)],"한 구역(셀)의 52주 출석을 한 판에 놓고 ★찍는 카드입니다(보기만 하는 판이 아닙니다). ▸구역 칸을 비우고 실행하시면 지금 있는 구역과 인원수를 보여 드립니다. ▸구역 이름을 넣으시면 그 구역 52주 판이 열리고, 참석하신 분 이름을 함께 넣으시면 그 주에 바로 찍힙니다. ▸★찍으신 구역만 기록됩니다 — 아직 안 찍으신 구역은 «안 나오심»이 아니라 «기록 없음»으로 남습니다. 한 구역을 찍었다고 다른 구역이 결석이 되지 않습니다. ▸★구역을 아직 안 적으신 분들은 「미배정」 구역으로 모아 드립니다 — 그분들도 찍으실 수 있습니다. ▸표시: ▇ 나오심 · ▁ 안 나오심(그 주에 그 구역을 찍으셨을 때만) · · 기록 없음. ▸★등록하시기 전의 주도 세지 않습니다 — 그때는 아직 우리 교회에 계시지 않았으므로 «안 나오심»이 아니라 «해당 없음»입니다. 그래서 오늘 등록하신 분이 «12주 연속 결석»으로 뜨지 않습니다(등록일을 아직 안 적으신 분은 이 기준을 적용하지 않습니다). ▸여기서 쌓인 기록이 '성도 한눈에 보기'의 출석률과 '장기결석자 찾기'를 켭니다."),
 ("목양","long-absent","장기결석자 찾기 (잃은 양) 🔍","🔍",[("weeks","기준 주수(기본 4주)","4",0)],"출석 기록을 바탕으로 N주 이상 예배에 안 나오신 성도를 자동으로 찾아 명단·연락처로 만들어 드립니다. 심방·안부 연락 대상을 놓치지 마세요."), ("목양","weekly-brief","주간 목회 브리핑","🗞️",[],"이번 주 교인·출석·재정·생일·돌봄 대상을 한 장으로 요약해 드립니다 — 주간 사역을 한눈에 살피실 때 쓰십니다. ▸★프로그램이 카톡을 보내지는 않습니다 — 붙여넣으실 초안을 파일로 만들어 드립니다(카카오 정책상 개인 카톡 자동발송은 불가합니다). ▸★예전에 만드신 파일에는 이름이 「[카톡발송]」이라고 적혀 있을 수 있습니다 — ★같은 것입니다(이제부터는 「[카톡초안]」으로 만들어집니다)."),
 ("목양","birthday","🎂 생일·결혼기념일 축하","🎂",[("days","며칠 이내를 볼까요? (오늘만 보려면 0)","7",0)],"다가오는 생일·결혼기념일을 미리 확인하고, 당일에 보낼 축하 카톡을 함께 만들어 드립니다('오늘'로 표시). 100가지 문구가 매년 다르게 자동 선택되고, 지난 축하도 보여드려 겹치지 않아요. ▸★프로그램이 카톡을 보내지는 않습니다 — 붙여넣으실 초안을 파일로 만들어 드립니다(카카오 정책상 개인 카톡 자동발송은 불가합니다). ▸★예전에 만드신 파일에는 이름이 「[카톡발송]」이라고 적혀 있을 수 있습니다 — ★같은 것입니다(이제부터는 「[카톡초안]」으로 만들어집니다)."),
 ("목양","careevent-add","축하·위로 문자 (상황별·경조사 통합) 🎉","🎉",[("kind","상황(취업·이사·합격·군입대·출산… / 경조사: 결혼·장례·출생·회갑·입원)","",1),("name","대상 이름","",1),("jik","호칭·직분(형제/집사 등)","",0),("date","날짜(결혼→기념일 자동연동)","",0),("amount","경조금(경조사만·기록됨)","",0),("note","내용·메모(경조사 기록용)","",0)],"상황이나 사건을 넣으면 골라 쓸 축하·위로 카톡 문구를 만들어 드립니다. 취업·이사·합격 등 상황별은 3문구, 결혼·장례·출생 등 경조사는 문자+경조금 기록·심방 연동까지. 생일·결혼기념일은 옆의 '생일·결혼기념일 축하' 카드가 자동으로 챙깁니다."),
 ("목양","cell-worship","구역(셀)·속회 예배 순서지","🏠",[("title","제목","구역(셀)예배",0),("text","본문","",0),("date","날짜","",0),("leader","인도(구역장)","",0)],"구역(셀)·속회 예배 순서 + 나눔 질문 + 기도제목 기입란. 구역장이 인도용으로 출력합니다."),
 ("목양","group-add","소그룹(구역·셀) 등록","🧩",[("name","소그룹명","",1),("leader","리더","",0),("day","모임요일","",0),("place","장소","",0)],"구역(셀)·속회 같은 소그룹을 등록합니다(이름·리더·모임 요일·장소). ▸한 번 등록해 두시면 '구역 주간보고'·'구역 보고서 양식'에서 그대로 쓰입니다. ▸교인 등록의 '구역' 칸과 이름을 같게 적어 주시면 명단이 자동으로 이어집니다."),
 ("목양","group-report","구역(셀) 주간보고","🗒️",[("name","소그룹명","",1),("attend","참석","",0),("note","나눔","",0),("absent","결석자","",0)],"구역장이 올린 주간 나눔을 기록합니다(참석·나눔 내용·결석자). ▸쌓이면 어느 구역(셀)이 잘 돌아가고 어디에 손이 필요한지 보이고, 결석자는 심방 대상으로 이어집니다."),
 ("목양","group-form","구역(셀) 보고서 양식(인쇄)","🖨️",[("name","소그룹명","",0)],"구역장에게 나눠 드릴 ★빈 보고서 양식을 인쇄용으로 만들어 드립니다. ▸손으로 적어 오시면 '구역(셀) 주간보고' 카드에 옮겨 넣으시면 됩니다. ▸소그룹명을 넣으면 그 이름이 인쇄된 양식이, 비우면 공용 양식이 나옵니다."),
 ("목양","train-add","양육·제자훈련 기록","🎓",[("name","교인","",1),("course","과정","제자훈련",0),("stage","단계","",0),("status","상태(진행/수료)","진행",0)],"제자훈련·새가족반·성경공부 같은 양육 과정의 수강과 수료를 기록합니다(과정·단계·진행/수료). ▸누가 어디까지 훈련받았는지 남아, 직분자를 세우실 때와 목양 카드에서 그대로 보입니다."),
 ("예배·설교","sermon","설교 초안 작성","✍️",[("title","제목","",1),("text","본문","요3:16",0),("service","예배유형","주일오전예배/새벽기도회/수요예배/목요집회/금요기도회/주일오후예배/중고등부/초등부",0),("theme","주제","믿음 은혜",0),("points","대지(;로 구분)","",0),("series","시리즈","",0)],"제목·본문·주제·대지를 넣으시면 설교 초안 문서를 만들어 드립니다. ▸대지는 ;(세미콜론)으로 나눠 적으시면 각각 소제목이 됩니다. ▸예배 유형을 고르시면 그 예배에 맞는 길이와 형식으로 짜입니다. ▸만들어진 초안은 09번 폴더에 저장되고 '지난 설교'에서 다시 여실 수 있습니다."),
 ("예배·설교","sermon-plan","연간 설교 계획표 🗓️","🗓️",[("year","연도(비우면 올해)","2026",0)],"그 해 모든 주일을 자동으로 나열하고 절기(부활절·성탄 등)를 자동 표시합니다. 본문·제목·시리즈를 미리 계획해 여유 있게 준비하세요(빈 표에 채워 인쇄·보관)."),
 ("예배·설교","sermon-files","지난 설교 (목록·열기·검색)","📚",[("open","설교 제목 (비우면 전체 목록·눌러 열기)","",0),("query","이력 검색어(본문/제목)","",0),("service","예배유형(검색 필터)","",0)],"지난 설교 파일을 봅니다 — 비우면 전체 목록(눌러 열기), 제목을 넣으면 그 파일 열기, '검색어'로 설교 이력(본문·제목)에서 찾기."),
 ("예배·설교","sermon-reuse","지난 설교 재활용 (새 초안 작성)","♻️",[("query","지난설교 검색(본문/제목)","",1),("title","새 제목(비우면 동일)","",0),("service","예배유형","",0)],"지난 설교(본문·제목으로 검색)를 바탕으로 새 설교 초안을 작성합니다 — 재묵상·재작성에 좋습니다."),
 ("예배·설교","bulletin","주보 만들기","📰",[("sermon","설교 제목","",0),("notice","교회소식(;로 구분)","",0),("week","주간일정(;로 구분)","",0)],"★이 카드는 자료를 바꾸지 않고 문서만 만듭니다. 이번 주 ★주보를 만들어 드립니다. ▸예배 순서를 비워 두시면 «묵도;찬송;기도;성경봉독;찬양;설교;헌금;광고;축도» 로 들어갑니다. 바꾸시려면 ★세미콜론(;)으로 이어 적어 주세요. ▸설교·광고·기도제목·날짜를 넣으시면 그대로 실립니다. ▸★되돌리실 것이 없습니다. 만들어진 문서를 열어 손보신 뒤 인쇄하셔도 됩니다."),
 ("예배·설교","devotion","오늘의 묵상 (말씀카드·해설·질문 자동) 🕊️","🕊️",[("title","제목","",1),("text","★성경구절을 넣어보세요 (예: 엡 2:19-22)","",0),("theme","주제(사랑·믿음·공동체·시련·감사·기도·순종·은혜·소망·회개·사명·평안 / 비우면 자동)","",0),("verse","본문 말씀 — 목사님이 직접 입력(저작권 안전)","",0),("body","묵상/해설(비우면 주제 참고문장 자동 제안)","",0),("apply","오늘의 적용","",0),("pray","기도","",0)],"★성경구절을 넣으면 이쁜 말씀카드 그림 + 간단한 해설·적용·질문이 자동으로. 성도들께 카톡으로 보내면 은혜가 됩니다. ▸★프로그램이 카톡을 보내지는 않습니다 — 붙여넣으실 초안을 파일로 만들어 드립니다(카카오 정책상 개인 카톡 자동발송은 불가합니다). ▸★예전에 만드신 파일에는 이름이 「[카톡발송]」이라고 적혀 있을 수 있습니다 — ★같은 것입니다(이제부터는 「[카톡초안]」으로 만들어집니다)."),
 ("행정서식","cert","증명서·상장 발급 & 대장","📜",[("name","이름 (비우면 발급대장 보기)","",0),("kind","종류(교인/세례/재적/출석/이명/헌금/재직/수료/임명/위촉)","교인",0),("role","직분·과정(재직/수료/임명/위촉 시)","",0),("term","임기·재직기간","",0),("purpose","용도·근거","",0)],"이름을 넣으면 증명서·상장을 발급하고(문서번호 자동·대장 자동기록), 이름을 비우면 지금까지 발급한 내역(발급대장)을 봅니다. 한 카드로 발급과 대장을 다 합니다."),
 ("성례","sacrament-add","성례 등록 & 대장 (세례·학습·입교)","💧",[("name","이름 (비우면 성례대장 보기)","",0),("kind","종류(유아세례/세례/학습/입교)","세례",0),("birth","생년월일","",0),("addr","주소","",0),("date","성례일","",0),("by","집례자(비우면 담임)","",0),("memo","비고","",0)],"이름을 넣으면 성례(세례·학습·입교·유아세례)를 대장에 등록하고, 이름을 비우면 성례대장 전체를 봅니다. 진학용 세례증명의 근거."),
 ("성례","communion","🍞 성찬 준비·안내","🍞",[("date","시행일 (예: 2026-09-06 · 비우면 적어 두신 일정과 준비 사항만 봅니다)","",0),("service","예배 (비우면 주일예배)","",0),("note","메모 (배찬 순서·준비 인원 등)","",0)],"성찬 시행일을 적어 두고, 성찬 전에 챙기실 것과 회중에게 미리 알려 드릴 말씀을 한 장으로 드립니다. ▸시행일을 넣으시면 일정으로 적어 두고, 비우고 실행하시면 적어 두신 일정과 준비 사항을 보여 드립니다. ▸주보·광고에 그대로 넣으실 수 있는 안내 문장을 함께 드립니다(고쳐 쓰셔도 됩니다). ▸★성찬은 «성례 등록 대장»에 쌓지 않습니다 — 그 대장은 세례·학습·입교처럼 한 번 받고 증명서를 떼는 것을 위한 자리라, 매번 받는 성찬을 넣으면 세례 기록이 그 속에 묻히기 때문입니다. ▸★참여하신 분 명단을 남기는 기능은 아직 넣지 않았습니다 — 목사님께 먼저 여쭙고 정하려고 비워 두었습니다. ▸떡·잔을 몇 분 준비할지는 «구역(셀)별 52주 출석 체크판»의 지난 주일 출석을 참고하시면 편합니다."),
 ("성례","sacrament-class","📖 성례 교육 (세례 · 유아세례 · 학습 · 입교)","📖",[("kind","종류 (세례 / 유아세례 / 학습 / 입교 · 비우면 세례)","",0),("names","교육 받으실 분 (; 로 구분 · 비우면 지금까지 적어 두신 것만 봅니다)","",0),("date","날짜 (비우면 오늘)","",0),("note","그날 다룬 내용 메모","",0)],"세례 · 유아세례 부모교육 · 학습 · 입교 ★네 가지 교육의 회차를 적어 두고, 무엇을 다룰지 안내해 드립니다. ▸종류마다 ★2회분 차례(회차 제목 · 그날 다룰 항목 · 인도하실 때 유의하실 점)를 함께 드립니다. ▸★유아세례 교육을 받으시는 분은 아기가 아니라 ★부모님입니다 — 아기의 믿음이 아니라 부모의 서약이기 때문입니다. ▸★학습은 세례를 준비하는 걸음이고, ★입교는 유아세례를 받은 이가 자기 입으로 신앙을 고백하는 자리입니다. ▸이름을 넣고 실행하시면 그날 회차로 적히고, 비우고 실행하시면 지금까지 누가 몇 회차까지 왔는지 보여 드립니다. ▸흔히 다루는 항목을 종류별로 드립니다 — ★교단·교회마다 다르니 고쳐 쓰십시오(교단 공인 과정이 아닙니다). ▸★수료증은 만들지 않습니다 — 교육을 인정하는 절차는 교단·당회마다 달라, 프로그램이 «수료»를 발급하면 없는 권위를 만드는 것이 됩니다. ▸★이 기록은 성례 대장이 아닙니다(«받기 전 준비»이지 «받았다»가 아닙니다) — 실제로 성례를 베푸신 뒤에는 «성례 등록 & 대장»에 넣으셔야 증명서가 나옵니다. ▸★성찬은 여기 없습니다 — 정식 교육과정이 아니라서 «🍞 성찬 준비·안내» 카드가 따로 맡습니다."),
 ("성례","sacrament-apply","성례 서식 (신청서·증명서 발급)","📝",[("mode","무엇을? (신청서 / 증명서 · 비우면 신청서)","",0),("name","이름","",0),("kind","종류(유아세례/세례/학습/입교)","세례",0),("birth","생년월일","",0),("addr","주소","",0),("tel","연락처","",0),("cell","소속 구역(셀)·부서","",0),("leader","추천 인도자","",0),("purpose","용도(증명서·예: 진학)","",0)],"'신청서'는 당회 제출용 성례 신청서 서식, '증명서'는 세례교인 증명서를 발급합니다. 이름을 넣으면 채워서, 비우면 빈 양식으로."),
 ("성경자료","bible","성경 찾기 (KJV·WEB)","📖",[("ref","찾을 곳(예: 요한복음 3:16 · 요 3장 · 요 3:16-18)","요한복음 3:16",1),("version","역본(kjv/web)","web",0)],"성경 본문을 찾아봅니다(KJV·WEB 영어 역본). 장 전체·범위·약칭 다 인식합니다."),
 ("성경자료","bible-plan","성경 통독표","📖",[("type","유형(1년/90일/맥체인)","1년",0),("date","시작일(YYYY-MM-DD·비우면 오늘)","",0),("dept","부서(선택)","",0)],"1년 일독·90일·맥체인 중에서 고르시면 날짜별 읽을 범위가 적힌 통독표를 만들어 드립니다. ▸시작일을 넣으시면 그 날짜부터 계산됩니다(비우면 오늘부터). ▸인쇄해 성도들께 나눠 드리기 좋습니다."),
 ("성경자료","bible-quiz","성경 퀴즈","📝",[("ref","범위(예: 요한복음 3 · ★아래에 본문을 붙여넣으실 때는 비워 두셔도 됩니다)","요한복음 3",0),("verses","★성경 본문 붙여넣기 — 찾으신 성경 본문을 여기에 붙여넣으세요 (한 줄에 한 절)","요 3:16 (쓰시는 성경 본문을 한 줄에 한 절씩 붙여넣으세요 · 대한성서공회 «성경읽기» bskorea.or.kr 에서 보실 수 있습니다)",0),("type","유형 (사지선다 / 빈칸 / 성구찾기 · 빈칸과 성구찾기가 주관식입니다)","빈칸",0),("count","문항수","10",0),("source","역본 이름 (예: 개역개정 · 문서 맨 아래에 출처로 적힙니다)","",0),("version","역본 파일(비우면 자동 · web·kjv 는 영어 공개역본입니다)","",0),("level","난이도(초/중/고)","",0),("dept","부서","",0)],"쓰시는 성경 본문을 아래 «성경 본문 붙여넣기» 칸에 붙여넣으세요(대한성서공회 «성경읽기» bskorea.or.kr 에서 보실 수 있습니다). ▸옮겨 적으신 글에는 오탈자가 섞여 문제와 정답이 함께 틀어질 수 있으니, 보고 계신 본문을 그대로 붙여넣으시면 좋습니다. ▸붙여넣으신 그 본문으로 ★사지선다 · ★빈칸 채우기 · ★성구 찾기 중 원하시는 것으로 만들어 드립니다(빈칸과 성구 찾기가 주관식입니다) — 정답지까지 함께. ▸이 프로그램에는 성경 본문이 들어 있지 않습니다. ▸★5절 이상 넣으시면 보기가 다양해집니다. ▸붙여넣으신 본문은 이 컴퓨터 안에서만 쓰이고 ★교회 밖으로 나가지 않습니다. ▸본문을 안 넣으시면 «성구 찾아쓰기»(성구 주소만 드리고 성경에서 찾아 적게 하는 문제)로 만들어 드리고, 화면이 그 사실을 말씀드립니다. ▸역본 이름을 적어 주시면 문서 맨 아래에 출처로 적히고, 정답지에는 ★원문 절을 그대로 함께 실어 드립니다. ▸주일학교·수련회·구역(셀) 모임에서 그대로 쓰시고, 난이도와 문항 수도 정하실 수 있습니다."),
 ("성경자료","memory-verse","성경 암송표·카드","💳",[("refs","성구들(;로 구분·예: 요한복음 3:16; 로마서 8:28)","",1),("set","세트명(예: 구원/절기/부서)","암송",0),("version","역본(비우면 자동: 개역개정 있으면 한국어·없으면 주소중심 / web·kjv 지정가능)","",0),("dept","부서","",0)],"암송할 성구들을 ;로 나눠 적으시면 암송표와 카드를 만들어 드립니다. ▸주일학교 암송 대회, 구역(셀) 암송, 개인 암송에 쓰십니다. ▸세트명을 넣으시면 그 이름으로 묶여 나옵니다."),
 ("전도","vip-add","태신자(전도대상) 등록","🌟",[("name","이름","",1),("sponsor","담당 성도","",0),("tel","연락처","",0)],"전도할 태신자(아직 교회에 안 나오는 전도 대상자)를 담당 성도와 함께 등록·관리합니다. 새생명축제(초청잔치)에 초청할 명단이 됩니다."),
 ("전도","harvest-plan","새생명축제 준비 타임라인 (D-day)","🗓️",[("title","축제명","새생명 초청잔치",0),("dday","축제일(YYYY-MM-DD)","",0)],"축제일을 넣으면 D-56~D+28 월·일별 준비사항을 날짜까지 자동 계산해 체크리스트로 만들어 드립니다."),
 ("전도","harvest-checklist","새생명축제 당일 진행 체크리스트","✅",[("title","축제명","새생명 초청잔치",0),("date","날짜","",0)],"축제 당일 시간대·역할별 진행 점검표(세팅~맞이~예배·초청~배웅~정리)."),
 ("다음세대(주일학교)","student-add","학생 등록(청소년·청년)","🎒",[("name","이름","",1),("school","학교","",0),("grade","학년","",0),("dept","부서","중고등부",0),("tel","연락처","",0),("guardian","보호자","",0),("gtel","보호자연락처","",0)],"중고등부·청년부 학생을 등록합니다(학교·학년·부서·보호자 연락처). ▸보호자 연락처를 함께 넣어 두시면 급한 일이 있을 때 바로 연락하실 수 있습니다. ▸'학생 명단'에서 부서별로 뽑아 보실 수 있습니다."),
 ("다음세대(주일학교)","student-list","학생 명단(부서별)","📋",[("dept","부서(비우면 전체)","",0),("grade","학년","",0)],"등록된 학생을 부서·학년별로 뽑아 봅니다. ▸부서를 비우시면 전체가 나옵니다. ▸수련회 명단, 출석부, 보호자 연락망을 만드실 때 이 목록에서 시작하세요."),
 ("다음세대(주일학교)","lesson","공과·교안 만들기","📝",[("title","제목","",1),("target","대상(부서·학년)","중고등부",0),("text","본문","요3:16",0),("theme","주제","",0),("goal","목표","",0)],"주일학교 공과와 교안을 만들어 드립니다 — 제목·대상 부서·본문·주제·목표를 넣으시면 도입·본문 해설·나눔 질문·적용까지 짜인 교안이 나옵니다. ▸교사에게 그대로 나눠 드릴 수 있는 형태입니다."),
 ("다음세대(주일학교)","exam-cheer","시험 응원 카톡","💪",[("exam","시험명","중간고사",0),("dept","부서(전체는 비움)","",0)],"★이 카드는 자료를 바꾸지 않고 ★문구만 만들어 드립니다. 시험 기간에 학생과 부모님께 보내실 격려 문구 꾸러미입니다. ▸그대로 ★복사해 붙여 넣어 보내시면 됩니다. ▸시험 이름과 부서를 넣으시면 그에 맞게 문구가 나옵니다. ▸★되돌리실 것이 없습니다. 마음에 안 드는 문구는 그냥 고쳐 쓰십시오."),
 ("다음세대(주일학교)","event-plan","수련회·여름사역 기획서","⛺",[("title","수련회·행사명","여름수련회",1),("date","일시","",0),("place","장소","",0),("theme","주제","",0),("host","담당","",0)],"수련회·여름사역의 기획서를 만들어 드립니다 — 주제·일시·장소·담당을 넣으시면 목적, 프로그램 얼개, 준비물, 역할 분담, 예산 항목이 들어간 문서가 나옵니다. ▸제직회·당회에 올릴 서류로 바로 쓰십니다. ▸아래 '대외행사 기획서'와 ★같은 서식으로 만들어집니다(제목만 다르게 넣으시면 됩니다)."),
 ("다음세대(주일학교)","vbs","여름 성경학교(수련회) 공과 (7주제) 📖","📖",[("no","주제 번호를 적으세요 1~7 (비우고 실행하면 1과)","","")],"여름 성경학교·수련회용 7주제 공과를 한 카드에 — 칸에 1~7 중 하나를 적고 실행하면 그 공과가 열립니다. 1창조·2복음·3동행·4사랑섬김·5믿음·6기도·7제자도."),
 ("행정서식","annual-plan","연간 사역 계획표","📅",[("year","연도","2026",0)],"월별 절기·주요 사역을 한 장으로. 우리 교회 계획 기입란 포함(절기는 그 해 달력 확인)."),
 ("행정서식","meeting-minutes","회의록","🗒️",[("type","종류(제직회/공동의회/당회/교사회)","제직회",0),("date","날짜","",0),("place","장소","",0),("host","사회","",0),("clerk","서기","",0),("attend","참석(;로 구분)","",0),("absent","불참(;로 구분)","",0),("agenda","안건(;로 구분)","",0)],"제직회·공동의회·당회·교사회의 회의록을 서식에 맞게 만들어 드립니다. ▸참석·불참·안건을 ;로 나눠 적으시면 표로 정리됩니다. ▸노회 제출이나 보관용으로 형식이 맞게 나옵니다."),
 ("행정서식","official-doc","공문(협조문)","📄",[("to","수신","",1),("title","제목","",1),("body","본문(;로 구분)","",0),("via","경유","",0),("sender","발신(비우면 담임)","",0),("date","날짜","",0)],"노회·기관·관공서에 보낼 공문(협조문)을 서식에 맞게 만들어 드립니다 — 수신·제목·본문·발신이 갖춰진 형태로 나옵니다. ▸본문은 ;로 나눠 적으시면 항목별로 정리됩니다."),
 ("행정서식","asset-register","비품대장","📦",[("name","품목(비우면 대장만)","",0),("qty","수량","1",0),("place","위치","",0),("manager","담당","",0),("status","상태","사용",0),("date","구입일","",0)],"교회 비품을 대장으로 관리합니다(품목·수량·위치·담당·상태·구입일). ▸품목을 비우고 실행하시면 지금까지 등록된 대장 전체를 보십니다. ▸무엇이 어디 있는지, 누가 맡고 있는지가 남아 인수인계가 쉬워집니다."),
 ("행정서식","vehicle-log","차량운행일지","🚗",[("driver","운전자","",0),("dest","행선지","",0),("km","거리(km)","",0),("fuel","주유","",0),("date","일자","",0)],"교회 차량의 운행을 기록합니다(운전자·행선지·거리·주유). ▸쌓이면 유류비 정산과 보험·사고 대응의 근거가 됩니다. ▸비우고 실행하시면 지금까지의 운행 일지를 보십니다."),
 ("예배·설교","calendar","교회력·절기","✝️",[("year","연도","2026",0)],"★이 카드는 자료를 바꾸지 않고 ★계산해서 보여 드리기만 합니다. 그 해 ★교회력·절기 날짜를 부활절 기준으로 산출해 알려 드립니다. ▸연도를 비우시면 올해로 봅니다. ▸사순절·부활절·성령강림절처럼 ★해마다 날짜가 움직이는 절기를 미리 확인하시고 설교·주보 준비 일정을 잡으실 때 쓰십니다. ▸★되돌리실 것이 없습니다."),
 ("예배·설교","cal-open","🗓️ 일정 캘린더","🗓️",[],"탁상 달력처럼 월별 일정을 봅니다. 날짜를 눌러 행사를 기록하고, ★ 중요한 날은 대시보드에도 뜹니다."),
 ("찬양","setlist","찬양 콘티","🎶",[("songs","곡목(;로 구분)","",1),("size","용지(A4/A3)","A4",0),("title","콘티 제목","",0)],"★이 카드는 자료를 바꾸지 않고 문서만 만듭니다. 예배·연습에 쓰실 ★찬양 콘티를 만들어 드립니다. ▸곡 목록을 적어 주시면 곡별로 ★key·BPM·가사·악보를 붙여 A4나 A3로 엮어 드립니다. ▸「찬양곡·자작곡 등록」에 넣어 두신 곡이 자동으로 쓰입니다. ▸★되돌리실 것이 없습니다."),
 ("찬양","compose","AI 찬양 작곡 (수노·작업지) 🎼","🎼",[("title","곡 제목","새 찬양",1),("theme","주제(예: 은혜·감사·부흥)","",0),("bible","성경 본문(예: 시 103편)","",0),("mood","분위기(예: 은혜롭고 벅찬)","",0),("key","조(Key)","G",0),("bpm","BPM","72",0),("lyrics","가사(직접 쓰면 그대로·비우면 틀만)","",0)],"★찬양 한 곡을 만들기 위한 작업지를 만들어 드립니다 — 가사 틀(1절·후렴·2절·브릿지) + 수노(Suno)·유디오(Udio) 같은 무료 음악 AI에 그대로 붙여넣는 영어 프롬프트까지. 작업지의 프롬프트를 복사해 수노(suno.com, 무료)에 붙여넣으면 실제 멜로디·음원이 만들어집니다. 완성곡을 유튜브에 올린 뒤 '찬양곡·자작곡 등록'에 링크를 넣으면 찬양 콘티에 자동 반영됩니다. ※가사는 직접 창작하므로 저작권 걱정이 없습니다."),
 ("찬양","song-add","찬양곡·자작곡 등록","🎼",[("title","곡명","",1),("composer","작곡가","",0),("key","조(Key)","D",0),("bpm","BPM","72",0),("youtube","유튜브 링크","",0),("lyrics","가사","",0)],"★이 카드는 문서를 만드는 카드가 아니라 ★자료를 저장하는 카드입니다. 찬양곡을 찬양곡 라이브러리에 등록합니다(직접 지으신 자작곡도 함께). ▸★바뀌는 것: 등록하신 곡이 라이브러리에 ★남고, 「찬양 콘티」· 「찬양 가사 PPT」·「찬양집」에서 곧바로 불러 쓰입니다. ▸제목·작곡·작사·key·BPM·주제·가사·악보· 유튜브·앨범·저작권까지 넣어 두실 수 있고, ★같은 제목으로 다시 등록하시면 내용이 갱신됩니다. ▸★되돌리시려면: 잘못 넣으신 곡은 다시 등록해 고치시거나, 크게 어긋났으면 「🔥 피닉스 복구」로 이전 시점으로 되살리실 수 있습니다. ▸제목은 ★비워 두지 마세요 — 제목 없는 곡은 목록에서 찾을 수 없습니다."),
 ("찬양","song-sheet","작곡 곡 악보 열기","🎼",[("title","곡 제목","",1)],"'AI 찬양 작곡'으로 만드신 곡의 작업지(악보·가사·프롬프트)를 다시 열어 봅니다. ▸곡 제목을 넣으시면 그 곡의 작업지가 열립니다. ▸수노(Suno)에 다시 넣으실 프롬프트도 그 안에 있습니다."),
 ("찬양","song-catalog","찬양 작품집","🏆",[("title","제목","",0)],"★이 카드는 자료를 바꾸지 않고 문서만 만듭니다. 직접 지으신 곡 전체를 ★발표순으로 정리한 작품집을 만들어 드립니다. ▸유튜브·앨범·저작권 정보까지 함께 실려, 사역의 ★열매를 한 권으로 남기실 수 있습니다. ▸★되돌리실 것이 없습니다. 내용이 빠져 보이면 「찬양곡·자작곡 등록」에서 그 곡의 정보를 채워 주세요."),
 ("영상·홍보","video-plan","행사 홍보영상 기획·대본 (만들 준비) 🎬","🎬",[("title","행사·영상 제목","여름성경학교",1),("purpose","목적·대상(예: 지역 어린이 초청)","",0),("message","핵심 메시지(자막)","올여름, 아이들이 예수님을 만납니다",0),("when","일시·장소(자막)","",0),("cta","신청·문의(자막)","",0),("length","길이(초·짧게 30초~3분)","30",0),("tone","톤·분위기(예: 활기찬/따뜻한)","따뜻하고 설레는",0),("aspect","화면(가로=유튜브 / 세로=릴스·밴드)","가로",0)],"★홍보영상을 만들기 위한 '작업지'를 만들어 드립니다 — 스토리보드 5장면 + 자막 대본 + 장면별 촬영 안내 + 영상AI 프롬프트 3종 + 무료 편집기 조립 순서까지 한 장에. 이 작업지대로 무료 편집기(Clipchamp·Canva·CapCut)로 만들면 완성됩니다(→ '무료 영상편집·영상 AI 완전 가이드' 카드 참고). 영상 다룰 줄 몰라도 순서만 따라오시면 됩니다. ※이 카드가 만들어 드리는 것은 ★작업지입니다 — 프로그램이 영상을 직접 만들어 드리지는 않습니다. 그 작업지대로 무료 편집기에 사진·영상 조각을 넣어 조립하시면 완성됩니다. ▸어떤 무료 도구를 어떤 순서로 쓰는지는 '무료 영상편집·영상 AI 완전 가이드' 카드에 적혀 있습니다."),
 ("영상·홍보","sermon-slides","설교 슬라이드(PPT) 만들기 📊","📊",[("title","설교 제목","주일 설교",1),("text","본문 성구(예: 요 3:16)","",0),("theme","주제","",0),("points","설교 대지(; 로 구분)","",0)],"설교 제목·본문 성경구절·대지를 넣으면 예배 프로젝터·화면공유용 슬라이드(PPT)를 자동으로 만들어 드립니다."),
 ("찬양","songbook","찬양집(악보집) 출판","📔",[("songs","곡목(;, 전체는 비움)","",0),("title","제목","",0)],"★이 카드는 자료를 바꾸지 않고 문서만 만듭니다. 등록된 곡으로 ★찬양집(악보집)을 표지·목차까지 갖춰 편집해 드립니다. ▸곡을 지정하시면 그 곡들로, 비워 두시면 전체로 엮습니다. 곡마다 제목·작곡·key·가사· 악보가 들어갑니다. ▸★되돌리실 것이 없습니다. 인쇄·제본해 성도님들께 나눠 드릴 수 있습니다."),
 ("찬양","worship-roster","찬양팀 배정표","🎹",[("date","날짜","2026-01-01",0),("leader","인도","",0),("keys","건반","",0),("guitar","기타","",0),("bass","베이스","",0),("drums","드럼","",0),("singers","싱어","",0)],"★이 카드는 자료를 바꾸지 않고 문서만 만듭니다. 찬양팀 ★파트별 배정표를 만들어 드립니다(인도·건반· 기타·베이스·드럼·싱어). ▸날짜와 파트별 이름을 넣으시면 배정표가 되고, ★카톡으로 보내실 리마인드 문구도 함께 만들어 드립니다. ▸★되돌리실 것이 없습니다. 배정이 바뀌면 다시 만드시면 됩니다."),
 ("찬양","production-add","뮤지컬·공연 등록","🎭",[("title","작품","",1),("date","공연일","",0),("place","장소","",0),("director","연출","",0),("music","음악감독","",0)],"찬양 뮤지컬·공연을 등록합니다(작품·공연일·연출·음악감독)."),
 ("찬양","casting","공연 배역(캐스팅)","🎬",[("title","작품","",1),("date","공연일","",0),("roles","배역(;로 구분)","",0)],"뮤지컬·공연의 배역(캐스팅)을 정리합니다."),
 ("사역","schedule-add","집회·외부 일정 (등록 & 목록)","📅",[("place","장소/교회 (비우면 일정 목록 보기)","",0),("date","날짜","",0),("type","유형(집회/외부설교/행사/찬양사역)","집회",0),("theme","주제","",0),("host","담당","",0),("fee","사례","",0),("upcoming","목록에서 다가오는것만(1)","1",0)],"장소·주제 등을 넣으면 집회·외부 일정을 등록하고, 비우면 일정 목록(D-day 표시)을 봅니다."),
 ("선교","mission-plan","선교 준비 (타임라인·체크리스트)","✈️",[("title","팀명","단기선교",1),("dday","출국일(예: 2026-08-04)","",0)],"팀명·출국일을 넣으면 D-day 준비 타임라인 + 준비 체크리스트(여권·비자·예방접종·짐·사역·안전)를 한 번에 만들어 드립니다."),
 ("사역","event-plan","대외행사 기획서","🎪",[("title","행사명","",1),("date","일시","",0),("place","장소","",0),("theme","주제","",0)],"지역을 초청하는 행사(바자회·음악회·나눔행사 등)의 기획서를 만들어 드립니다 — 행사명·일시·장소·주제를 넣으시면 목적, 진행 얼개, 준비물, 역할 분담, 예산 항목이 들어간 문서가 나옵니다. ▸위 '수련회·여름사역 기획서'와 ★같은 서식입니다."),
 ("사역","presbytery-add","노회 관련","⛪",[("kind","구분(회의/서류/노회비)","회의",0),("note","내용","",1),("role","담당직무","",0),("due","기한","",0)],"★이 카드는 문서를 만드는 카드가 아니라 ★자료를 저장하는 카드입니다. 노회 관련 일을 기록해 둡니다 — 회의·직무·제출 서류·노회비·시찰 등. ▸★바뀌는 것: 넣으신 기록이 ★남고, 기한이 있는 일은 기한 관리에 올라갑니다. ▸종류·내용·맡은 역할·기한·날짜를 넣으실 수 있습니다. ▸★되돌리시려면: 잘못 넣으신 기록은 다시 넣어 고치시거나, 크게 어긋났으면 「🔥 피닉스 복구」로 이전 시점으로 되살리실 수 있습니다."),
 ("선교","mission-field","선교 현지정보 시트","🗺️",[("title","선교 팀명","",1)],"선교사·숙소·식당·사역지 연락처와 일자별 장소 계획을 한 장으로 정리합니다."),
 ("재정","finance-add","재정 기록 & 요약 (수입/지출)","💵",[("kind","구분 — ★«수입» 또는 «지출» (반드시 둘 중 하나)","수입",1),("item","항목 — 수입:십일조·감사·선교·건축 / 지출:인건비·시설·공과금·행사","십일조",0),("name","교인(헌금자·선택)","",0),("dept","부서(선택·예: 선교부/교육부/찬양)","",0),("amount","금액(숫자만·비우면 요약 보기)","",0),("month","요약 볼 월(YYYY-MM·비우면 전체)","",0)],"금액을 넣으면 수입/지출을 기록하고(부서 넣으면 부서별 회계 집계), 금액을 비우면 재정 요약을 봅니다. ▸★'구분'은 «수입»·«지출» 둘 중 하나여야 합니다 — 다른 말이나 빈 칸이면 ★저장하지 않고 다시 여쭙습니다. ▸★비워 두셔도 «수입»으로 넣지 않습니다: 지출을 수입으로 잘못 적으면 결산이 통째로 틀어지기 때문입니다. ▸요약에 «수입도 지출도 아닌» 예전 기록이 있으면 몇 건·얼마인지 함께 알려 드립니다(조용히 빼지 않습니다)."),
 ("재정","finance-import","재정 엑셀 가져오기 (재정부 엑셀 그대로) 💰","💰",[("file","재정 엑셀·CSV 파일 (프로그램 폴더에 두고 파일 이름만 넣으셔도 됩니다)","2026재정.xlsx",1),("apply","실제로 반영 (확인 후 1 · 비워두면 미리보기)","",0),("year","연도 (월별 결산표일 때 · 예: 2026)","",0),("sheet","시트 이름 (여러 장일 때만)","",0),("shape","모양 지정 (보통 비워두세요 · A=거래목록 B=월별집계 C=주간헌금)","",0)],"재정부가 엑셀로 정리하신 수입·지출을 그대로 불러옵니다. 세 가지 모양을 알아서 인식합니다 — ①날짜·적요·수입·지출 형태의 거래 장부 ②항목별 1월~12월 연간 결산표(연도를 함께 넣어 주세요) ③날짜별 십일조·감사헌금 등 주간 헌금 집계표. ▸'합계·소계' 줄은 자동으로 걸러냅니다. ▸금액은 1,200,000 · ₩ · 원 표기 모두 인식합니다. ▸처음 실행하면 미리보기라 자료가 바뀌지 않습니다 — 화면에 나온 수입·지출 합계가 장부와 맞는지 먼저 확인하세요. ▸확인 후 '실제로 반영'에 1을 넣으면 반영되며 그 직전 자동 백업합니다. ▸같은 파일을 다시 넣어도 이미 들어간 내역은 건너뛰므로 매달 갱신해 넣으셔도 안전합니다. ▸반영 후에는 연간 재정 총결산·항목별 통계·기부금영수증을 그대로 뽑으실 수 있습니다."),
 ("재정","finance-chart","재정 그래프·통계 📊","📊",[],"★재정을 그래프로 한눈에 — 월별 수입·지출 추이(막대), 헌금 종류·지출 항목 비중(도넛), 예산 대비 집행률(게이지), 부서별 집계. 작은 교회의 월별 결산과 부서별 집계를 한눈에 보시도록 만든 시각화 대시보드입니다."),
 ("재정","giving-ledger","교인별 헌금대장","🧾",[("name","교인(전체는 비움)","",0),("year","연도","",0)],"★이 카드는 자료를 바꾸지 않고 문서만 만듭니다. 헌금 기록을 ★교인별 × 헌금 종류별로 모아 대장으로 만들어 드립니다. ▸이름을 비우시면 전체, 넣으시면 그 성도 한 분만 봅니다. 연도도 고르실 수 있습니다. ▸심방 준비나 영수증 발급의 ★근거 자료로 쓰시는 표입니다. ▸★되돌리실 것이 없습니다. ▸★교인의 헌금 내역은 민감한 자료입니다 — 만들어진 문서를 두시는 자리에 유의해 주세요."),
 ("재정","donation-receipt","기부금영수증","🧧",[("name","교인","",1),("year","연도","2026",0)],"★이 카드는 자료를 바꾸지 않고 문서만 만듭니다. 연말정산에 내실 ★기부금영수증을 교인의 한 해 헌금 합계로 만들어 드립니다. ▸이름과 연도를 넣으시면 그 해 합계로 한 장 발급됩니다. ▸★되돌리실 것이 없습니다. 금액이 잘못되었으면 ★재정 기록을 고치신 뒤 다시 발급하시면 됩니다 — 영수증 문서를 손으로 고치지 마세요. 다음에 또 어긋납니다."),
 ("재정","finance-report","주일 재정 결산서 (+연간 총결산)","🧮",[("date","결산 주일(YYYY-MM-DD·비우면 오늘)","",0),("year","연간 총결산 볼 연도(YYYY·넣으면 그 해 전체)","",0),("dfrom","기간시작","",0),("dto","기간끝","",0)],"주일(또는 기간) 재정 결산서. '연도'를 넣으면 그 해 연간 총결산(월별 합계·헌금종류·지출항목·부서별)을 만들어 드립니다."),
 ("재정","finance-ledger","재정 출납부(원장)","📒",[("month","월(YYYY-MM·비우면 이번달)","",0),("year","연도(YYYY·연간)","",0),("dfrom","기간시작","",0),("dto","기간끝","",0)],"★이 카드는 자료를 바꾸지 않고 ★문서만 만듭니다. 모든 수입과 지출을 날짜순으로, ★잔액이 한 줄씩 따라가는 재정부 장부로 만들어 드립니다. ▸재정 자료는 하나도 바뀌지 않습니다 — 읽어서 문서 한 부를 새로 만들 뿐이라 몇 번을 누르셔도 안전합니다. ▸기간을 비워 두시면 ★이번 달로 만듭니다. 월(2026-08) · 연도 · 시작~끝 날짜 중 편한 것으로 지정하실 수 있습니다. ▸«전기이월»은 그 기간 ★전까지의 잔액입니다 — 통장을 이어 보시듯 읽으시면 됩니다. ▸맨 아래 ★재정부장·회계·담임목사 날인란이 들어 있어 그대로 제직회에 올리실 수 있습니다. ▸★되돌리실 것이 없습니다: 문서만 새로 생깁니다. 마음에 안 드시면 그 문서를 지우시면 됩니다. ▸숫자가 비어 보이면 그 기간에 재정 기록이 아직 없는 것입니다 — 「재정 기록」 카드로 먼저 넣어 주세요."),
 ("재정","finance-items","헌금·지출 항목표","📋",[],"★이 카드는 자료를 바꾸지 않고 문서만 만듭니다. 재정 기록에 쓰실 ★표준 항목 이름표(헌금 종류 · 지출 항목)를 인쇄용 문서로 만들어 드립니다. ▸이 표의 이름 그대로 입력하시면 주일 결산서에 ★표준 순서로 자동 정리됩니다. ▸표에 없는 항목도 자유롭게 쓰실 수 있습니다(결산서 맨 아래에 따로 표시됩니다). ▸★되돌리실 것이 없습니다. 재정부 담당자께 한 장 인쇄해 드리면 서로 다른 이름으로 적히는 일이 줄어듭니다."),
 ("재정","offering-tally","주일 헌금 봉투 집계표 🧾","🧾",[("date","날짜(비우면 오늘)","",0),("rows","줄 수(기본 25)","25",0)],"헌금 세는 분들이 봉투별로 이름·금액을 적어 종류별로 합산하는 인쇄용 양식입니다. 합산한 종류별 합계를 '재정 기록'에 입력하면 출납부·결산서에 자동 반영됩니다."),
 ("재정","budget-plan","예산안 편성 양식 📋","🧾",[("year","편성 연도(YYYY·비우면 올해)","",0)],"작년 실적을 참고칸에 자동으로 채운 금년 예산안 표 — 제직회·공동의회 심의용. 이 표로 예산을 정한 뒤 '예산 편성' 카드에 입력하세요."),
 ("재정","budget-set","예산 편성 & 집행현황","🧮",[("year","연도(YYYY·비우면 올해)","",0),("kind","구분(수입/지출)","수입",0),("item","항목(비우면 집행현황 보기 · 예: 십일조/인건비)","",0),("amount","예산액(숫자만·0 삭제)","",0)],"항목을 넣으면 연간 예산을 항목별로 편성하고, 항목을 비우면 예산 대비 집행현황(항목별 집행률·잔액·초과)을 봅니다. 작은 교회 예산 관리에 맞춘 카드입니다."),
 ("출력·파일","ppt","🎼 찬양 가사 만들기","📽️",[("songs","곡목(;로 구분)","",1),("title","제목","",0),("form","형식 (비우면 PPT · 문서로 원하시면 «문서» 라고 적으세요)","",0)],"★이 카드는 자료를 바꾸지 않고 파일만 만듭니다. 예배 프로젝터에 띄우실 ★찬양 가사를 만들어 드립니다. ▸★예전에 따로 있던 「찬양 가사 PPT」와 「가사 스크린(문서)」 카드는 ★모두 이 안에 있습니다. ▸「형식」을 ★비워 두시면 예전 「찬양 가사 PPT」와 똑같이 ★파워포인트로 나옵니다(파일 이름도 그대로 [찬양PPT]). ▸「형식」에 ★«문서» 라고 적으시면 예전 「가사 스크린(문서)」과 똑같이 ★큰 글씨 문서로 나옵니다(파일 이름도 그대로 [가사스크린]). ▸가사를 ★한 소절씩 나눠 한 장에 하나씩 담습니다. ▸「찬양곡·자작곡 등록」에 가사가 들어 있어야 나옵니다. ▸★되돌리실 것이 없습니다."),
 # ★A23 2단계 — 카드 자리에 ★경고를 단다(기억 `church-code-text-sync`: 코드를 고치면 문장도 고친다).
 #   ★왜 필요했나: `hwp_convert` 는 실행 즉시 `taskkill /F /IM Hwp.exe` 를 했다.
 #     종전 배포판은 pywin32 가 없어 ★그 줄에 닿기 전에 멈췄다 — 없는 의존성이 ★우연히 안전장치였다.
 #     A23 2단계로 pywin32 를 넣으면서 ★그 줄에 닿게 됐다.
 #   ★2026-08-27 수리(master 판정 ⑦ 1번안): 이제 `hwp_convert` 가 ★먼저 여쭙는다 —
 #     한글이 열려 있으면 ★시작하지 않고 몇 개 열려 있는지 알려 드린 뒤 멈춘다(`_hwp_running()`).
 #     ⇒ 카드 문구도 «닫힙니다»에서 «열려 있으면 시작하지 않습니다»로 함께 고친다.
 ("출력·파일","hwp","한글(.hwp) 변환","📄",[("recent","최근 몇 개(기본10) ⚠ 한글(HWP)이 열려 있으면 변환을 시작하지 않습니다 — 저장하고 닫으신 뒤 눌러 주세요","10",0)],"★이 카드는 자료를 바꾸지 않고 ★파일을 새로 만듭니다. 이미 만들어진 문서(.docx)를 ★한글 파일(.hwp)로 바꿔 드립니다 — 원래 문서는 그대로 남습니다. ▸★먼저 확인해 주세요: .docx 는 한글 프로그램에서 ★그냥 열립니다. 관공서 제출처럼 ★.hwp 파일이 꼭 필요할 때만 쓰시면 됩니다. ▸이 카드는 ★한글 프로그램이 깔린 윈도우에서만 동작합니다 — 안 되면 그 이유를 화면에 알려 드립니다. ▸★되돌리실 것이 없습니다."),
 ("출력·파일","print-file","프린터 출력","🖨️",[("file","파일 경로","",1)],"파일을 사무실 컴퓨터의 기본 프린터로 바로 보냅니다. ▸★폰에서 누르시면 인쇄하지 않고 ★그 문서를 폰으로 받으십니다 — 폰 옆에는 프린터가 없고, 여기서 인쇄를 걸면 아무도 없는 사무실에서 종이만 나오기 때문입니다. 받으신 문서는 사무실에 오셔서 인쇄하시면 됩니다."),
 ("출력·파일","open-file","내 파일·작업물 찾아 열기","📁",[("name","파일 이름 검색 (비우면 종류별 목록)","",0),("kind","종류(설교/심방/주보/묵상/찬양/악보/증명서/재정/교안·비우면 전체)","",0)],"파일 이름을 넣으면 프로그램·D폴더·USB에서 찾아 열고, 비우면 종류별 내 작업물을 최근순 목록(눌러 열기)으로 보여줍니다. ▸★폰에서는 파일이 사무실 화면에서 열리는 대신 ★폰으로 바로 받아집니다(받기 단추가 뜹니다). ▸폴더나 인터넷 주소는 폰으로 받을 수 없어 위치만 알려 드립니다."),
 ("출력·파일","nlm-add","NotebookLM에 자료 올리기 (성경주석·찬양작곡 등)","☁️",[("file","올릴 파일 경로(주석·찬양곡·자료)","",1),("book","성경책(예: 로마서·롬·히브리서 — 자동 연결)","",0),("notebook","노트북ID(직접 지정할 때만)","",0)],"★이 카드는 교회 자료를 바꾸지 않습니다. 다만 ★이 프로그램에서 유일하게, 고르신 파일을 ★교회 밖(NotebookLM) 으로 올려보냅니다. ▸다른 카드들은 자료를 ★교회 안에만 둡니다. ★이 카드만 예외이니 무엇을 올리시는지 한 번 보아 주세요. ▸★올리셔도 되는 것: 성경주석·설교 원고·묵상 자료·주보·찬양 가사처럼 ★교인 개인정보가 들어 있지 않은 문서. 이런 자료는 마음껏 올려 두시고 검색에 쓰십시오 — 그러라고 있는 카드입니다. ▸★올리지 마시기를 권하는 것: 교인 명단·연락처·주소·헌금 내역·심방 기록처럼 ★한 분의 신상이 담긴 파일. ▸★바뀌는 것: 교회 자료는 그대로입니다. 다만 ★올라간 사본이 바깥에 하나 생깁니다. ▸★되돌리시려면: 이 프로그램에서는 지울 수 없고, ★올라간 곳에 직접 들어가 지우셔야 합니다. 그래서 올리기 전에 한 번만 더 확인해 주시면 좋습니다."),
 ("출력·파일","read-file","파일 읽기(TXT/DOCX)","📄",[("file","파일 경로","",1)],"컴퓨터에 있는 글 파일(TXT·DOCX)의 내용을 이 화면에서 바로 읽습니다. ▸다른 프로그램을 열지 않고 내용만 확인하실 때 쓰십니다. ▸★폰에서 여시면 화면에서 읽으실 수 있습니다."),
 # ── ★[자료 섹션 2026-08-29 · 오너 승인] 읽을거리는 여기 한 자리에 모은다 ──
 #   ★통합이 아니라 ★이동이다 — 카드도 이름도 그대로이고 명령·인자·산출물이 무변이다.
 #   ★업무 섹션들 뒤 · ★시스템 섹션 앞(master 재정) — 맨 뒤면 «있지만 안 보이는» 자리가 된다.
 ("📖 자료","ref-conflict","성도·당회 갈등 관리 📖","🕊️",[],"성도 사이의 갈등, 당회의 대립을 성경적으로 다루는 실전 지침서입니다. ▸갈등의 뿌리를 보는 법, 중재의 순서, 하지 말아야 할 말, 회복을 위한 절차까지. ▸정죄가 아니라 화해를 목표로 씌어졌습니다."),
 ("📖 자료","ref-ceremony","예식서(순서·기도문) 📖","📜",[],"결혼·장례·임직·입당 등 예식의 순서지와 기도문 모음입니다. ▸그대로 읽으셔도 되고, 우리 교회 상황에 맞게 고쳐 쓰셔도 됩니다. ▸갑작스러운 예식을 맡으셨을 때 먼저 펴 보세요."),
 ("📖 자료","ref-prayer","대표기도문·상황별 📖","🙏",[],"주일 대표기도·식사기도·심방기도 등 상황별 기도문 모음입니다. ▸대표기도를 맡은 성도께 드리면 부담을 크게 덜어 드릴 수 있습니다."),
 ("📖 자료","ref-bstudy","성경공부 인도 📖","📖",[],"성경공부를 ★인도하는 법에 관한 자료입니다 — 질문 만들기, 침묵 다루기, 빗나간 나눔 돌리기, 준비 시간 줄이기. ▸무엇을 가르칠까보다 ★어떻게 이끌까에 대한 자료입니다."),
 ("📖 자료","ref-spirit","목회자 영성·자기돌봄 📖","✝️",[],"목회자 자신의 영성과 자기 돌봄에 관한 자료입니다 — 소진(번아웃)의 신호, 안식의 실제, 홀로 있는 시간, 낙심할 때. ▸성도를 돌보시는 분을 돌보기 위한 자료입니다."),
 ("📖 자료","ref-bible","성경교육 자료 📖","📖",[],"성경을 어떻게 가르칠까 — 연령별 성경교육 원리·교수법·커리큘럼 참고자료(전 부서 공용)."),
 ("📖 자료","ref-wor","찬양·예배음악 📖","🎶",[],"찬양 인도와 예배 음악에 관한 자료입니다 — 콘티 짜는 원리, 회중이 따라 부르게 하는 법, 찬양팀 세우기, 저작권. ▸찬양팀이 없거나 작은 교회에서 쓸 수 있는 방법도 함께 담았습니다."),
 ("📖 자료","ref-ev","전도·새신자 📖","🌱",[],"전도와 새신자 정착에 관한 자료입니다 — 관계 전도, 첫 만남에서 할 말, 초청의 방법, 정착까지 동행하기. ▸문 밖의 사람보다 ★이미 오신 분을 붙드는 법에 더 무게를 두었습니다."),
 ("📖 자료","ref-dis","제직·제자훈련 📖","🎓",[],"제직(집사·권사·장로)을 세우고 제자훈련을 이끄는 자료입니다 — 직분의 뜻, 세우는 기준과 절차, 훈련 과정 설계, 위임과 점검. ▸혼자 다 하지 않으시도록 돕는 자료입니다."),
 ("📖 자료","ref-laity","평신도 사역·사역자 세우기 📖","🙋",[],"평신도를 사역자로 세우는 자료입니다 — 은사 찾기, 맡기는 법, 못 하실 때 거두는 법, 감사와 격려. ▸사람이 적은 교회일수록 더 필요한 내용입니다."),
 ("📖 자료","ref-fam","가정·결혼·상담 📖","💒",[],"가정·결혼·부모 상담에 관한 자료입니다 — 부부 갈등, 자녀 양육, 고부 관계, 이혼 위기. ▸상담 중에 하실 질문과 하지 마실 말이 함께 적혀 있습니다."),
 ("📖 자료","ref-counsel","성경적 상담 실전 가이드 📖","🕊️",[],"성경적 상담의 실전 안내서입니다 — 듣는 법, 죄와 상처를 나누어 보는 법, 말씀을 적용하는 법, 전문가에게 넘겨야 할 때. ▸★목회자가 감당할 선과 넘길 선을 분명히 적어 두었습니다."),
 ("📖 자료","ref-adm","교회행정·재정 📖","🗂️",[],"교회 행정과 재정 운영의 원칙을 담은 자료입니다 — 장부의 기본, 예산과 결산, 헌금 관리의 투명성, 제직회·공동의회 진행. ▸작은 교회에서 실제로 지킬 수 있는 수준으로 씌어졌습니다."),
 ("📖 자료","ref-newbeliever","새신자 교육 4주 프로그램 📖","🌱",[],"새가족을 4주간 양육하는 실전 교재 — 주차별 인도안·나눔질문·부록 양식 A~F."),
 ("📖 자료","ref-harvest","준비 가이드(태신자운동~후속) 📖","🌾",[],"태신자 운동~새생명 초청잔치까지 D-56~후속 타임라인·초청카드 서식·부록 12종 전체 가이드."),
 ("📖 자료","ref-season","교회 절기 사역 준비 📖","🕯️",[],"대강절·성탄·고난주간·부활절·맥추·추수감사 등 11절기 — 준비 타임라인·예배순서·기도문·행사 아이디어."),
 ("📖 자료","ref-cult","이단 분별·대처 (성도 보호) 📖","🛡️",[],"지능화된 이단 포교로부터 성도를 지키는 실전 분별서 — 판별 기준(삼위일체·성경권위·구원관)·주요 이단 교리·최신 포교수법(문화센터·SNS·추수꾼)·분별 체크리스트 24개·상담과 돌봄. 정죄가 아닌 분별과 긍휼."),
 ("📖 자료","ref-summer","여름성경학교·수련회 준비 📖","⛺",[],"여름 성경학교와 수련회를 준비하는 자료입니다 — 몇 주 전에 무엇을 할지, 교사 모집과 훈련, 안전과 보험, 예산, 비 오는 날 대비까지. ▸처음 맡으셨어도 순서대로 따라가실 수 있습니다."),
 ("📖 자료","ref-ss","주일학교 지도자료 📖","🧸",[],"주일학교 교사와 부장을 위한 지도 자료입니다 — 연령별 특징, 산만한 아이 다루기, 교사 세우기와 격려, 부모와의 소통. ▸교사 모임에서 함께 읽으셔도 좋습니다."),
 ("📖 자료","ref-vision","청소년 비전코칭(진로·소명) 📖","🧭",[],"진로가 막막한 청소년을 돕는 비전코칭 — 강점 발견·소명 세우기·1:1 진행안·상황별 코칭·부록 7종."),
 ("📖 자료","ref-worldview","기독교 세계관 교육 📖","🌍",[],"세속 문화 속 청소년을 위한 성경적 세계관 — 창조·타락·구속·완성, 주제 10개, 10주 커리큘럼, 미디어 분별 훈련."),
 ("📖 자료","ref-video","홍보영상 편집·영상 AI 완전 가이드 📖","📖",[],"홍보·행사 영상을 만드는 법 — Clipchamp·Canva·CapCut 등 무료 편집기와 Runway·Pika·Kling 등 영상 AI 사용법, 목적별 홍보영상 템플릿, 저작권 안전 음원까지 총정리."),
 ("📖 자료","ref-worshipvid","예배·설교 영상 — 녹화·유튜브 라이브 완전 가이드 📖","📡",[],"예배·설교를 영상으로 전하는 모든 것 — 1부 녹화·자막·유튜브 업로드·짧은 요약영상, 2부 실시간 방송(Prism Live·OBS 단계별)·유튜브 라이브 켜기·소리·온라인 성도 돌봄·CCLI 저작권까지. 영상·방송이 처음이어도 OK."),
 ("📖 자료","ref-mission","단기선교·비전트립 준비 📖","🌏",[],"8주 사전훈련·안전·서류·재정·현지사역·이주민선교까지 담은 단기선교 실전 참고자료입니다."),
 ("📖 자료","ref-me","선교지 선교영어 📖","🗣️",[],"선교지에서 바로 쓰는 상황별 선교 영어 — 인사·전도·기도·생활 표현."),
 ("📖 자료","ask-ai","🤖 AI에게 더 깊이 물어보기","🤖",[("topic","주제·궁금한 것 (예: 은혜 · 청지기의 삶 · 요한복음 3장)","",1)],"주제를 넣으면 그 주제를 깊이 공부·설교 준비할 좋은 질문 8가지 + 무료 AI 여는 링크를 만들어 드립니다. ▸질문을 복사해 AI에 붙여넣으면 자세한 답을 얻습니다(무료·API키 없음). ▸이 카드가 하는 일은 «질문지 만들기»이고, 답은 AI가 합니다. AI 답은 참고용, 최종 판단은 목사님이."),
 ("📖 자료","ref-visit","상황별 심방 지침 📖","🏠",[],"심방을 어떻게 할지에 관한 자료입니다 — 상황별로 무엇을 묻고 무엇을 삼갈지, 첫 심방과 오래 다니신 성도, 병상·초상집·갈등이 있는 가정에서의 태도까지. ▸★예전에는 「심방 센터」 카드를 실행하셔야 나오는 단추로만 여실 수 있었습니다 — 이제 ★다른 자료들과 같은 자리에서 찾으실 수 있습니다(그 단추도 ★그대로 있습니다). ▸읽고 나서 실제 심방 기록은 「심방 센터」 카드에 남기시면 됩니다."),
 ("시스템","why","✨ 이 프로그램의 강점","✨",[],"교인정보 보안·데이터 통합·작은 교회 재정 등, 이 프로그램만의 강점을 한눈에 봅니다. 작은 교회 목사님을 위한 정성입니다."),
 ("시스템","setup","⛪ 우리 교회 이름 설정 (맨 처음 한 번)","⛪",[("church","우리 교회 이름","예: 은혜교회",1),("pastor","담임 목사님 성함","예: 홍길동 목사",0)],"교회명·담임명만 넣으면 모든 문서·주보·증명서·축하 문자에 자동으로 들어갑니다. 어려운 설정 파일을 직접 여실 필요가 없어요."),
 ("시스템","phone-setup","📱 폰 접속 설정 (핸드폰으로 보기)","📱",[("pw","새 비밀번호 (6자 이상 · 안 바꾸시면 비워 두세요)","",0),("pw2","비밀번호 다시 한 번 (확인용)","",0),("on","폰 접속 (켜기 / 끄기)","",0),("way","접속 방식 (와이파이 / 사설망 · 안 바꾸시면 비워 두세요)","",0),("logoutall","폰을 잃어버리셨다면 1 (폰·바깥 기기 모두 로그아웃)","",0)],"핸드폰에서도 이 프로그램을 그대로 쓰실 수 있게 합니다. ▸다 비우고 실행하면 지금 상태와 '폰에서 칠 주소'를 보여 드립니다. ▸★그리고 «지금 이 컴퓨터가 폰을 받을 수 있는 상태인가»를 ★프로그램이 직접 읽어서 알려 드립니다 — (가)폰이 들어올 문(8899)이 ★어느 주소에 열려 있나 (나)윈도우 방화벽이 ★이 프로그램을 허용하고 있나 (다)지금 연결된 망의 종류와 ★그 허용이 이 망에서도 듣는가. ▸★막고 있는 것이 보이면 그것만 사실대로 적고, 함께 드리는 「폰에서 열리게 하기」 파일을 ★관리자 권한으로 한 번 실행하시라고 안내해 드립니다(그 파일은 ★허용만 더하고 다른 설정은 바꾸지 않습니다). ▸★프로그램이 대신 고치지는 못합니다 — 윈도우가 관리자 권한을 요구하기 때문입니다(다음 판에서 다룹니다). ▸★막는 것이 안 보여도 «폰에서 열립니다»라고는 말씀드리지 않습니다 — 공유기와 폰 쪽은 이 컴퓨터가 읽을 수 없습니다. ▸★읽지 못한 항목은 «확인 못 함»이라고 적습니다 — 못 잰 것을 «정상»이라고 하지 않습니다. ▸먼저 비밀번호를 하나 정하시고, 그 다음 '폰 접속'에 켜기를 넣으세요(비밀번호 없이는 열리지 않습니다 — 같은 와이파이의 누구나 교인 명부를 보게 되기 때문입니다). ▸켜신 뒤에는 프로그램을 한 번 껐다 켜 주세요. ▸폰에서는 처음 한 번만 비밀번호를 넣으시면 그 뒤로는 다시 묻지 않도록 만들어 두었습니다(「이 폰 기억하기」를 켜 두시면 약 30일 · 끄시면 브라우저를 닫을 때까지만 — 빌린 기기로 잠깐 보실 때 꺼 주세요). ▸비밀번호를 여러 번 틀리면 ★잠기는 것이 아니라 답이 점점 늦어집니다(최대 1분) — 맞는 비밀번호를 넣으시면 그대로 들어가집니다. ▸★이 비밀번호가 막아 주는 것은 '같은 와이파이의 다른 사람이 우연히 열어 보는 것'입니다. 지금 연결은 암호화(https)가 아니라서 작정하고 엿보면 비밀번호가 보일 수 있습니다 — ★카페·공항 같은 공용 와이파이에서는 쓰지 마세요. ▸사무실 컴퓨터에서 쓰실 때는 지금까지처럼 아무것도 묻지 않습니다. ▸「폰을 잃어버리셨다면 1」을 실행하시면 폰·바깥 기기가 모두 끊깁니다 — 지금 보고 계신 폰에서 누르셨다면 그 폰에서도 비밀번호를 다시 넣으셔야 합니다. 사무실 컴퓨터는 그대로 쓰실 수 있습니다."),
 ("시스템","set-backup","USB·D 백업 (설정 & 지금 저장)","📦",[("path","저장 폴더(예: E:\\교회백업 · 비우면 설정된 폴더로 지금 저장)","",0)],"저장 폴더를 넣으면 자동저장 폴더로 설정하고 즉시 전체 저장합니다. 비우면 이미 설정된 폴더로 지금 전체 저장. USB·D폴더에 안전 이중보관."),
 ("시스템","backup","자료 백업","💾",[],"★이 카드는 자료를 바꾸지 않고 ★사본만 만듭니다. 지금 이 순간의 모든 자료를 날짜·시각이 붙은 폴더에 통째로 복사해 둡니다. ▸몇 번을 누르셔도 안전하고, 누를 때마다 그 시각의 사본이 ★따로 쌓입니다(앞의 사본을 덮지 않습니다). ▸담기는 것: 교인·심방·설교·재정·예화·주석·찬양곡 전부와 «_내자료» 폴더. ▸★폰 접속 비밀번호와 로그인 기록은 ★일부러 넣지 않습니다 — 사본이 밖으로 나가더라도 안전하도록 한 것입니다. ★그래서 나중에 이 사본으로 되돌리시면 폰 접속은 ★닫힌 상태로 시작됩니다. 「📱 폰 접속 설정」 에서 비밀번호를 다시 정하시면 그때 열립니다. ▸★되돌릴 것이 없습니다: 만들기만 하므로 «되돌리기»가 필요 없습니다. 프로그램을 업데이트하시기 전이나 큰 작업 전에 한 번 눌러 두시면 마음이 놓입니다."),
 ("시스템","phoenix","🔥 피닉스 복구","🔥",[("last","최근으로 복구하려면 1","",0)],"지워지거나 잘못된 자료를 ★지난 시점으로 되살립니다. ▸★이 카드는 «복구 시점»을 고르셨을 때만 자료를 바꿉니다. ★복구 시점 칸을 ★비워 두고 누르시면 «되살릴 수 있는 시점 목록»만 보여 드리고 자료는 아무것도 바뀌지 않습니다. ▸★누르기 전에 그 칸이 ★비어 있는지 꼭 확인해 주세요 — 전에 적어 두셨다가 실행하지 않고 다른 카드로 가셨으면, 돌아오셨을 때 ★그 값이 칸에 그대로 남아 있습니다. 남아 있는 채로 누르시면 ★복구가 실행됩니다. (화면을 새로 여시면 칸은 비워집니다.) ▸★바뀌는 것: 복구를 실행하시면 지금의 교인·설교·재정 자료가 ★그 시점의 자료로 통째로 바뀌고, 그 시점 이후에 입력하신 내용은 화면에서 사라집니다. ▸★되돌릴 수 있습니다: 바꾸기 ★직전의 자료를 «church_db.json.before_restore_(날짜_시각)» 으로 먼저 보관한 뒤에 바꿉니다. 잘못 되돌리셨어도 그 파일이 그대로 있습니다. 보관에 실패하면 ★아예 진행하지 않습니다. ▸되살릴 시점의 자료가 깨져 있으면 ★손대지 않고 멈춥니다 — 멀쩡한 지금 자료가 깨질 일은 없습니다."),
 ("시스템","update-undo","↩️ 업데이트 되돌리기","↩️",[("stamp","되돌릴 시점 (비우면 가장 최근)","",0),("apply","실제로 되돌리기 (확인 후 1 · 비우면 보기만)","",0)],"업데이트한 뒤에 뭔가 이상해졌을 때 ★그 직전으로 되돌립니다. ▸★비우고 실행하시면 ★무엇을 언제로 되돌리는지 보여만 드리고 아무것도 바뀌지 않습니다 — 먼저 보십시오. ▸확인하신 뒤 「실제로 되돌리기」 칸에 1을 넣으시면 그때 되돌립니다. ▸★교인·심방·재정 자료와 설정은 그대로 둡니다 — 되돌리는 것은 ★프로그램 파일(코드·안내문)뿐입니다. ▸★되돌리기 직전에 지금 상태도 함께 보관하므로, 되돌린 뒤 마음이 바뀌시면 ★다시 새 판으로 오실 수 있습니다(「업데이트」를 누르시면 됩니다). ▸되돌린 뒤에는 ★프로그램을 껐다 다시 켜 주세요 — 그때부터 되돌린 판으로 돕니다. ▸「되돌릴 시점」은 ★비워 두시면 가장 최근 업데이트 직전으로 갑니다(그 칸에 다른 시점을 넣고 싶으시면, 비우고 한 번 실행해 목록을 보신 뒤 고르시면 됩니다)."),
 ("시스템","version","버전·업데이트 확인","🔔",[],"지금 쓰고 계신 프로그램의 판(버전)을 보여 드리고, 새 업데이트가 나왔는지 확인합니다. ▸새 것이 있으면 무엇이 좋아졌는지 알려 드립니다. ▸실제로 받으시려면 화면 위의 '업데이트' 단추를 누르세요(자료는 그대로 보존됩니다)."),
 ("시스템","manual","사용 설명서 만들기","📘",[],"★이 카드는 자료를 바꾸지 않고 문서만 만듭니다. 이 프로그램의 ★모든 기능 사용법을 담은 설명서를 만들어 드립니다. ▸처음 쓰시는 분께, 또는 부교역자·직원께 건네실 때 한 부 뽑아 드리십시오. ▸★되돌리실 것이 없습니다. ▸프로그램을 업데이트하신 뒤에 ★다시 한 번 만드시면 새 기능까지 들어간 설명서가 됩니다."),
 ("시스템","export-excel","엑셀 관리대장","📗",[],"★이 카드는 자료를 바꾸지 않고 파일만 만듭니다. 교인 명부를 비롯한 자료를 ★색깔이 입혀진 엑셀 관리대장으로 뽑아 드립니다. ▸★주의: 엑셀 파일을 고치셔도 프로그램 자료는 ★바뀌지 않습니다. 내보내기 전용이니, 자료를 고치실 때는 각 카드에서 고쳐 주세요. ▸★되돌리실 것이 없습니다. ▸혹시 «눌렀는데 아무 일도 없다»고 느껴지시면 바탕화면의 ★「교회행정 시작」 아이콘으로 켜 주세요 — 그렇게 켜야 엑셀을 만드는 부품이 함께 실행됩니다(그 경우 화면에 안내가 뜹니다)."),
]

PAGE = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__CHURCH__ 교회행정</title>
<!-- ★폰 홈 화면에 «앱처럼» 두기 위한 머리표. 안드로이드는 manifest 를, 아이폰은 apple- 머리표를 본다.
     ★아이폰은 SVG 아이콘을 못 읽는다 — 그래서 아이콘은 PNG 로 그려 내보낸다(_app_icon). -->
<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">
<meta name="theme-color" content="#1F6E5A">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="__CHURCH__ 행정">
<link rel="apple-touch-icon" href="/appicon?s=180">
<link rel="icon" href="/appicon?s=192">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  :root{
    --paper:#F4F2EC; --surface:#FFFFFF; --surface-2:#FBFAF6;
    --ink:#14171C; --muted:#6A7078; --faint:#9AA0A6;
    --line:#E7E3D8; --line-2:#EFECE3;
    --brand:#1E3A34; --brand-soft:#EAF0EC; --brand-ink:#183029;
    --accent:#A9823C; --accent-soft:#F3EBDA;
    --good:#2F7D5B; --good-bg:#E8F2EC;
    --warn:#B07A1E; --warn-bg:#F6EED9;
    --crit:#B23B3B; --crit-bg:#F7E7E4;
    --shadow:0 1px 2px rgba(20,23,28,.05), 0 4px 12px rgba(20,23,28,.05), 0 18px 44px rgba(20,23,28,.08);
    --shadow-sm:0 1px 2px rgba(20,23,28,.05), 0 2px 7px rgba(20,23,28,.04);
    --r:16px; --r-sm:11px;
    --font:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",-apple-system,system-ui,sans-serif;
  }
  @media (prefers-color-scheme:dark){
    :root{
      --paper:#0E1115; --surface:#161A20; --surface-2:#12161B;
      --ink:#ECEEF1; --muted:#98A0AA; --faint:#6C747E;
      --line:#252B33; --line-2:#1E242B;
      --brand:#6FA898; --brand-soft:#17231F; --brand-ink:#B7D6CB;
      --accent:#CFA65E; --accent-soft:#241E12;
      --good:#5FB489; --good-bg:#132018; --warn:#D6A64E; --warn-bg:#211B0F;
      --crit:#D97C7C; --crit-bg:#241615;
      --shadow:0 1px 2px rgba(0,0,0,.32), 0 6px 18px rgba(0,0,0,.34), 0 22px 52px rgba(0,0,0,.42);
      --shadow-sm:0 1px 2px rgba(0,0,0,.35), 0 2px 8px rgba(0,0,0,.3);
    }
  }
  :root[data-theme="light"]{
    --paper:#F4F2EC; --surface:#FFFFFF; --surface-2:#FBFAF6; --ink:#14171C; --muted:#6A7078; --faint:#9AA0A6;
    --line:#E7E3D8; --line-2:#EFECE3; --brand:#1E3A34; --brand-soft:#EAF0EC; --brand-ink:#183029;
    --accent:#A9823C; --accent-soft:#F3EBDA; --good:#2F7D5B; --good-bg:#E8F2EC; --warn:#B07A1E; --warn-bg:#F6EED9; --crit:#B23B3B; --crit-bg:#F7E7E4;
    --shadow:0 1px 2px rgba(20,23,28,.05), 0 4px 12px rgba(20,23,28,.05), 0 18px 44px rgba(20,23,28,.08); --shadow-sm:0 1px 2px rgba(20,23,28,.05), 0 2px 7px rgba(20,23,28,.04);
  }
  :root[data-theme="dark"]{
    --paper:#0E1115; --surface:#161A20; --surface-2:#12161B; --ink:#ECEEF1; --muted:#98A0AA; --faint:#6C747E;
    --line:#252B33; --line-2:#1E242B; --brand:#6FA898; --brand-soft:#17231F; --brand-ink:#B7D6CB;
    --accent:#CFA65E; --accent-soft:#241E12; --good:#5FB489; --good-bg:#132018; --warn:#D6A64E; --warn-bg:#211B0F; --crit:#D97C7C; --crit-bg:#241615;
    --shadow:0 1px 2px rgba(0,0,0,.32), 0 6px 18px rgba(0,0,0,.34), 0 22px 52px rgba(0,0,0,.42); --shadow-sm:0 1px 2px rgba(0,0,0,.35), 0 2px 8px rgba(0,0,0,.3);
  }
  /* ── 색 테마(포인트 색 바꾸기) ── */
  :root[data-color="blue"]{--brand:#1E4E6E;--brand-soft:#E6F0F7;--brand-ink:#163b54;--accent:#2E7DA9;--accent-soft:#E1EFF6}
  :root[data-color="rose"]{--brand:#8E3B5A;--brand-soft:#F7E9EF;--brand-ink:#6b2842;--accent:#C05575;--accent-soft:#F8E5EC}
  :root[data-color="purple"]{--brand:#493B7C;--brand-soft:#ECE8F7;--brand-ink:#342a5c;--accent:#7C5FC0;--accent-soft:#EDE6F9}
  :root[data-color="orange"]{--brand:#9A5A24;--brand-soft:#F8ECDF;--brand-ink:#733f18;--accent:#D07C2E;--accent-soft:#F8E9D7}
  :root[data-color="mint"]{--brand:#1F6E5A;--brand-soft:#E3F3ED;--brand-ink:#154d3f;--accent:#2FA98A;--accent-soft:#E0F3EC}
  /* ── 계절 배경 — 여백에 확실히 비치도록 채도를 높임(라이트) ── */
  :root[data-season="spring"] body{background:linear-gradient(160deg,#FBD9E6 0%,#F1E2EF 40%,#DDEFD4 100%) fixed}
  :root[data-season="summer"] body{background:linear-gradient(160deg,#C7E8F3 0%,#D6E4F8 45%,#C6E4EE 100%) fixed}
  :root[data-season="autumn"] body{background:linear-gradient(160deg,#FBDDB4 0%,#F4CBA9 45%,#EDDBBB 100%) fixed}
  :root[data-season="winter"] body{background:linear-gradient(160deg,#D5E2F3 0%,#E1E8F5 45%,#CDDCEF 100%) fixed}
  /* ── 계절 배경(다크 모드) — 어둡되 계절 색 한 방울 ── */
  @media (prefers-color-scheme:dark){
    :root[data-season="spring"] body{background:linear-gradient(160deg,#1C1319 0%,#141017 55%,#0E1115 100%) fixed}
    :root[data-season="summer"] body{background:linear-gradient(160deg,#0F1A20 0%,#0F141C 55%,#0E1115 100%) fixed}
    :root[data-season="autumn"] body{background:linear-gradient(160deg,#1D160D 0%,#15110A 55%,#0E1115 100%) fixed}
    :root[data-season="winter"] body{background:linear-gradient(160deg,#111826 0%,#0F1319 55%,#0E1115 100%) fixed}
  }
  :root[data-theme="light"][data-season="spring"] body{background:linear-gradient(160deg,#FBD9E6 0%,#F1E2EF 40%,#DDEFD4 100%) fixed}
  :root[data-theme="light"][data-season="summer"] body{background:linear-gradient(160deg,#C7E8F3 0%,#D6E4F8 45%,#C6E4EE 100%) fixed}
  :root[data-theme="light"][data-season="autumn"] body{background:linear-gradient(160deg,#FBDDB4 0%,#F4CBA9 45%,#EDDBBB 100%) fixed}
  :root[data-theme="light"][data-season="winter"] body{background:linear-gradient(160deg,#D5E2F3 0%,#E1E8F5 45%,#CDDCEF 100%) fixed}
  :root[data-theme="dark"][data-season="spring"] body{background:linear-gradient(160deg,#1C1319 0%,#141017 55%,#0E1115 100%) fixed}
  :root[data-theme="dark"][data-season="summer"] body{background:linear-gradient(160deg,#0F1A20 0%,#0F141C 55%,#0E1115 100%) fixed}
  :root[data-theme="dark"][data-season="autumn"] body{background:linear-gradient(160deg,#1D160D 0%,#15110A 55%,#0E1115 100%) fixed}
  :root[data-theme="dark"][data-season="winter"] body{background:linear-gradient(160deg,#111826 0%,#0F1319 55%,#0E1115 100%) fixed}
  /* ── 내 사진 배경(목사님 사진) — 글자 가독성 위해 은은한 스크림 겹침, 계절 배경보다 우선 ── */
  :root[data-bg="photo"] body,:root[data-theme="light"][data-bg="photo"] body{background:linear-gradient(rgba(248,246,241,.83),rgba(248,246,241,.9)),var(--bgphoto) center center/cover fixed !important}
  @media (prefers-color-scheme:dark){:root[data-bg="photo"] body{background:linear-gradient(rgba(18,20,26,.85),rgba(18,20,26,.91)),var(--bgphoto) center center/cover fixed !important}}
  :root[data-theme="dark"][data-bg="photo"] body{background:linear-gradient(rgba(18,20,26,.85),rgba(18,20,26,.91)),var(--bgphoto) center center/cover fixed !important}
  .tp-photos{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:2px 0 4px}
  .tp-thumb{aspect-ratio:1/1;border-radius:8px;background-size:cover;background-position:center;cursor:pointer;border:2px solid transparent;transition:.12s;display:grid;place-items:center;font-size:13px;color:var(--muted)}
  .tp-thumb:hover{transform:scale(1.06)}
  .tp-thumb.tp-none{background:var(--surface-2)}
  .tp-thumb.sel{border-color:var(--brand);box-shadow:0 0 0 2px var(--brand-soft)}
  .tp-empty{font-size:11.5px;color:var(--muted);line-height:1.45;display:block;padding:2px 0 3px}
  .tp-add{display:block;text-align:center;margin-top:7px;padding:8px;border:1px dashed var(--line);border-radius:9px;color:var(--muted);font-size:12.5px;font-weight:700;cursor:pointer;transition:.12s}
  .tp-add:hover{border-color:var(--brand);color:var(--brand);background:var(--brand-soft)}
  .tp-hint{font-size:10.5px;color:var(--faint);line-height:1.4;margin-top:5px}
  body{background:var(--paper);color:var(--ink);font-family:var(--font);-webkit-font-smoothing:antialiased;font-size:15px;line-height:1.58}
  .app{display:grid;grid-template-columns:260px 1fr;min-height:100vh}
  .tnum{font-variant-numeric:tabular-nums}

  /* ── Sidebar ── */
  .side{background:var(--surface);border-right:1px solid var(--line);display:flex;flex-direction:column;position:sticky;top:0;height:100vh}
  .brand{display:flex;align-items:center;gap:12px;padding:24px 22px 20px;cursor:pointer}
  .brand:hover .mark{filter:brightness(1.08)}
  .mark{width:38px;height:38px;border-radius:10px;background:var(--brand);display:grid;place-items:center;flex:none;box-shadow:inset 0 0 0 1px rgba(255,255,255,.06)}
  .mark svg{width:20px;height:20px}
  .brand b{font-size:16.5px;font-weight:800;letter-spacing:-.2px;display:block;line-height:1.2}
  .brand span{font-size:11.5px;color:var(--muted);letter-spacing:.3px}
  .nav{padding:8px 14px;overflow-y:auto;flex:1}
  .nav .grp{font-size:11px;font-weight:700;letter-spacing:.9px;text-transform:uppercase;color:var(--faint);padding:18px 12px 8px}
  .nav a{display:flex;align-items:center;gap:11px;padding:10.5px 13px;border-radius:10px;color:var(--muted);text-decoration:none;font-size:14.5px;font-weight:500;transition:.13s;cursor:pointer}
  .nav a .i{width:19px;height:18px;flex:none;opacity:.9;display:inline-grid;place-items:center;font-size:15px}
  .nav a:hover{background:var(--surface-2);color:var(--ink)}
  .nav a.on{background:var(--brand-soft);color:var(--brand-ink);font-weight:700}
  .nav a.on .i{opacity:1}
  .nav a .tag{margin-left:auto;font-size:10px;font-weight:800;color:var(--accent);background:var(--accent-soft);padding:2px 6px;border-radius:20px;letter-spacing:.2px}
  .side-foot{border-top:1px solid var(--line);padding:15px 18px;display:flex;align-items:center;gap:11px}
  .side-foot .ava{width:34px;height:34px;border-radius:9px;background:var(--brand);color:#fff;display:grid;place-items:center;font-weight:800;font-size:13px;flex:none}
  .side-foot small{color:var(--muted);font-size:11.5px;display:block}
  .side-foot b{font-size:13.5px;font-weight:700}

  /* ── Main ── */
  .main{min-width:0}
  .top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--paper) 82%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:18px;padding:16px 34px}
  .top::before{content:"";position:absolute;left:0;right:0;top:0;height:2px;background:linear-gradient(90deg,var(--brand),var(--accent) 60%,transparent);opacity:.85}
  .top h1{font-size:19px;font-weight:800;letter-spacing:-.3px}
  .top .date{font-size:13px;color:var(--muted);font-weight:500}
  .search{margin-left:auto;display:flex;align-items:center;gap:10px;background:var(--surface);border:1px solid var(--line);border-radius:11px;padding:11px 15px;width:310px;color:var(--faint);box-shadow:var(--shadow-sm)}
  .search input{border:0;background:none;outline:0;font-family:inherit;font-size:14px;color:var(--ink);width:100%}
  .kbd{font-size:10.5px;color:var(--faint);border:1px solid var(--line);border-radius:5px;padding:1.5px 6px;font-weight:600}
  .icobtn{width:40px;height:40px;border:1px solid var(--line);background:var(--surface);border-radius:11px;display:grid;place-items:center;cursor:pointer;color:var(--muted);transition:.13s;position:relative;box-shadow:var(--shadow-sm)}
  .icobtn:hover{color:var(--ink);border-color:var(--muted)}
  .dot{position:absolute;top:8px;right:9px;width:7px;height:7px;border-radius:50%;background:var(--accent);border:2px solid var(--surface)}
  .upd{display:inline-flex;align-items:center;gap:8px;background:var(--accent-soft);color:var(--accent);border:1px solid color-mix(in srgb,var(--accent) 34%,var(--line));border-radius:11px;padding:11px 15px;font-family:inherit;font-size:14px;font-weight:700;cursor:pointer;transition:.14s;letter-spacing:-.1px}
  .upd:hover{border-color:var(--accent);transform:translateY(-1px)}
  .upd svg{width:16px;height:16px}
  .upd.has-new{background:var(--accent);color:#fff;border-color:var(--accent);animation:updpulse 1.7s ease-in-out infinite}
  .upd.has-new:hover{transform:translateY(-1px);filter:brightness(1.06)}
  @keyframes updpulse{0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--accent) 55%,transparent)}50%{box-shadow:0 0 0 7px transparent}}
  .updbadge{margin-left:2px;font-size:10px;font-weight:800;background:#fff;color:var(--accent);padding:1.5px 6px;border-radius:20px;letter-spacing:.4px}

  .wrap{padding:34px 40px 56px;max-width:1320px}
  .lede{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:26px}
  .lede h2{font-size:26px;font-weight:800;letter-spacing:-.5px;line-height:1.25}
  .lede p{color:var(--muted);font-size:14.5px;margin-top:6px}

  /* stat tiles */
  .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin-bottom:34px}
  .stat{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:21px 22px;box-shadow:var(--shadow-sm);position:relative;overflow:hidden}
  .stat::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent);opacity:.55}
  .stat .lbl{font-size:12px;font-weight:700;letter-spacing:.4px;color:var(--muted);text-transform:uppercase;display:flex;align-items:center;gap:8px}
  .stat .lbl .si{width:15px;height:15px;color:var(--accent)}
  .stat .num{font-size:35px;font-weight:800;letter-spacing:-1px;margin-top:11px;line-height:1}
  .stat .num small{font-size:15px;font-weight:600;color:var(--muted);letter-spacing:0}
  .stat .sub{margin-top:10px;font-size:13px;color:var(--muted);display:flex;align-items:center;gap:6px}
  .stat{transition:transform .18s cubic-bezier(.2,.7,.3,1),box-shadow .18s,border-color .18s}
  .stat:hover{transform:translateY(-3px);box-shadow:var(--shadow);border-color:color-mix(in srgb,var(--brand) 26%,var(--line))}
  .stat::after{content:"";position:absolute;right:-30px;top:-30px;width:96px;height:96px;border-radius:50%;background:radial-gradient(circle at 30% 30%,color-mix(in srgb,var(--accent) 12%,transparent),transparent 70%);pointer-events:none}
  .stats .stat:nth-child(1)::before{background:var(--brand);opacity:.75}
  .stats .stat:nth-child(2)::before{background:var(--good);opacity:.75}
  .stats .stat:nth-child(3)::before{background:var(--accent);opacity:.75}
  .stats .stat:nth-child(4)::before{background:var(--warn);opacity:.75}
  .stats .stat:nth-child(1) .lbl .si,.stats .stat:nth-child(1) .num{color:inherit}
  #card_bday:hover{border-color:color-mix(in srgb,var(--warn) 45%,var(--line))}

  /* 오늘의 목회 브리핑 */
  .brief{background:linear-gradient(168deg,var(--surface),var(--surface-2));border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow-sm);padding:7px 8px 10px;margin-bottom:34px}
  .brief-h{display:flex;align-items:center;gap:10px;padding:16px 16px 11px}
  .brief-h .dotm{width:9px;height:9px;border-radius:2px;background:var(--accent);flex:none}
  .brief-h .t{font-size:15.5px;font-weight:800;letter-spacing:-.2px}
  .brief-h .d{margin-left:auto;font-size:12.5px;color:var(--faint);font-weight:700;letter-spacing:.2px}
  .brow{display:flex;align-items:center;gap:13px;padding:13px 16px;border-radius:12px;cursor:pointer;transition:.13s;border:1px solid transparent}
  .brow:hover{background:var(--surface);border-color:var(--line);box-shadow:var(--shadow-sm)}
  .brow .ic{width:36px;height:36px;border-radius:11px;display:grid;place-items:center;flex:none;font-size:17px}
  .brow .tx{flex:1;min-width:0}
  .brow .tx b{font-size:14.5px;font-weight:700;display:block;letter-spacing:-.1px}
  .brow .tx s{text-decoration:none;font-size:12.5px;color:var(--muted);display:block;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .brow .bdg{font-size:12px;font-weight:800;padding:5px 12px;border-radius:20px;white-space:nowrap;letter-spacing:-.1px}
  .brow .go2{color:var(--faint);font-weight:800;font-size:15px;opacity:0;transition:.14s;flex:none}
  .brow:hover .go2{opacity:1;color:var(--accent);transform:translateX(2px)}
  .ic.bd,.bdg.bd{background:var(--warn-bg);color:var(--warn)}
  .ic.cr,.bdg.cr{background:var(--crit-bg);color:var(--crit)}
  .ic.nw,.bdg.nw{background:var(--good-bg);color:var(--good)}
  .ic.vs,.bdg.vs{background:var(--brand-soft);color:var(--brand)}
  .brief-empty{padding:16px 18px 20px;color:var(--muted);font-size:14px}

  /* section */
  .sec-h{display:flex;align-items:center;gap:11px;margin:12px 2px 18px;scroll-margin-top:84px}
  .sec-h .dotm{width:9px;height:9px;border-radius:2px;background:var(--accent)}
  .sec-h h3{font-size:17px;font-weight:800;letter-spacing:-.2px}
  .sec-h .cnt{font-size:13px;color:var(--faint);font-weight:600}
  .sec-h .rule{flex:1;height:1px;background:var(--line-2)}

  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(246px,1fr));gap:18px;margin-bottom:38px}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:20px 20px 19px;cursor:pointer;transition:transform .18s cubic-bezier(.2,.7,.3,1),box-shadow .18s,border-color .18s;position:relative}
  .sub-div{grid-column:1/-1;display:flex;align-items:center;gap:12px;margin:20px 2px 8px}
  .sub-div b{font-size:15.5px;font-weight:800;color:#fff;letter-spacing:.2px;white-space:nowrap;background:var(--sc);padding:6px 15px;border-radius:999px;box-shadow:0 2px 8px color-mix(in srgb,var(--sc) 40%,transparent)}
  .sub-div span{flex:1;height:2px;border-radius:2px;background:color-mix(in srgb,var(--sc) 40%,transparent)}
  .card.subc{border-top:4px solid var(--sc);background:color-mix(in srgb,var(--sc) 5%,var(--surface))}
  .card:hover{transform:translateY(-4px);box-shadow:var(--shadow);border-color:color-mix(in srgb,var(--brand) 40%,var(--line))}
  .card .ci{width:46px;height:46px;border-radius:12px;background:var(--brand-soft);color:var(--brand);display:grid;place-items:center;margin-bottom:15px;font-size:24px;line-height:1}
  .card h4{font-size:16.5px;font-weight:700;letter-spacing:-.2px;line-height:1.3}
  .card p{font-size:13.5px;color:var(--muted);margin-top:5px;line-height:1.55}
  .card .go{position:absolute;top:18px;right:17px;color:var(--faint);opacity:0;transition:.15s;font-weight:800;font-size:15px}
  .card:hover .go{opacity:1;color:var(--accent)}
  .card.feat{background:linear-gradient(155deg,var(--surface),var(--brand-soft))}
  .card.feat .badge{position:absolute;top:16px;right:16px;font-size:10.5px;font-weight:800;letter-spacing:.5px;color:var(--accent);background:var(--accent-soft);padding:4px 9px;border-radius:20px;text-transform:uppercase}

  .theme-tgl{cursor:pointer}
  .themewrap{position:relative}
  .themepanel{position:absolute;top:48px;right:0;background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:13px 14px 15px;width:246px;z-index:30;display:none}
  .themepanel.on{display:block}
  .tp-h{font-size:10.5px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;color:var(--faint);margin:9px 2px 7px}
  .tp-h:first-child{margin-top:2px}
  .tp-row{display:flex;gap:7px;flex-wrap:wrap}
  .tp-row button{flex:1;min-width:42px;padding:8px 5px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);border-radius:9px;font-family:inherit;font-size:12.5px;font-weight:700;cursor:pointer;transition:.13s}
  .tp-row button:hover{border-color:var(--accent);color:var(--accent)}
  .tp-sw{display:flex;gap:10px;padding:2px 2px 3px}
  .tp-sw .sw{width:30px;height:30px;border-radius:50%;cursor:pointer;box-shadow:inset 0 0 0 2px var(--surface),0 0 0 1px var(--line);transition:.14s}
  .tp-sw .sw:hover{transform:scale(1.13)}
  /* ── 알림 패널 ── */
  .notifwrap{position:relative}
  .notifpanel{position:absolute;top:48px;right:0;background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:8px;width:296px;z-index:30;display:none;max-height:420px;overflow:auto}
  .notifpanel.on{display:block}
  .np-h{font-size:10.5px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;color:var(--faint);padding:8px 8px 7px}
  .notif-item{display:flex;gap:11px;align-items:center;padding:10px 9px;border-radius:10px;cursor:pointer;transition:.12s}
  .notif-item:hover{background:var(--surface-2)}
  .notif-item .ni-ic{width:32px;height:32px;border-radius:9px;display:grid;place-items:center;flex:none;font-size:15px}
  .notif-item .ni-tx{min-width:0}
  .notif-item .ni-tx b{font-size:13.5px;font-weight:700;display:block;letter-spacing:-.1px}
  .notif-item .ni-tx s{text-decoration:none;font-size:12px;color:var(--muted);display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .ni-ic.bd{background:var(--warn-bg);color:var(--warn)}.ni-ic.cr{background:var(--crit-bg);color:var(--crit)}.ni-ic.nw{background:var(--good-bg);color:var(--good)}.ni-ic.vs{background:var(--brand-soft);color:var(--brand)}
  .notif-empty{padding:14px 10px 20px;color:var(--muted);font-size:13.5px;text-align:center}
  

  /* ── 실행 모달·입력폼·결과 (기존 JS 기능 유지 · 프리미엄 토큰 적용) ── */
  .modal{position:fixed;inset:0;background:rgba(10,12,20,.55);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;padding:18px;z-index:20}
  .modal.on{display:flex}
  .sheet{background:var(--surface);border:1px solid var(--line);border-radius:18px;max-width:540px;width:100%;max-height:88vh;overflow:auto;padding:30px;box-shadow:var(--shadow)}
  /* ── 📱 폰으로 보기 (QR) ── ★QR 두 장을 나란히. 좁은 화면에서는 저절로 한 줄씩 내려간다. */
  .qrwrap{display:flex;gap:14px;flex-wrap:wrap;justify-content:center}
  .qrcard{flex:1 1 215px;min-width:195px;border:1px solid var(--line);border-radius:14px;
    padding:14px;text-align:center;background:var(--surface)}
  .qrt{font-weight:800;font-size:16px;color:var(--ink)}
  /* ★«무엇이 필요한지»를 적는 자리. 두 줄 높이를 미리 잡아 둔다 — 글자 길이가 달라도
     QR 두 장의 높이가 어긋나지 않게(어긋나면 잘못 고르시기 쉽다). */
  .qrn{font-size:12.5px;color:var(--muted);margin:4px 0 10px;line-height:1.5;min-height:3.8em}
  .qrimg svg{width:100%;height:auto;max-width:225px;border-radius:8px;background:#fff}
  .qra{font-family:ui-monospace,Consolas,monospace;font-size:13px;margin-top:9px;
    word-break:break-all;color:var(--ink)}
  .qrx{font-size:12px;color:var(--muted);margin-top:5px}
  .qrpw{background:var(--brand-soft);border:1px solid var(--line);border-radius:12px;
    padding:12px 14px;margin-bottom:13px;font-size:14px;line-height:1.65;color:var(--ink)}
  .qrpw b{font-family:ui-monospace,Consolas,monospace;font-size:21px;letter-spacing:2px}
  /* ★경고는 «읽히게» 둔다 — 회색 잔글씨로 두면 안 읽으시고, 그러면 없는 것과 같다. */
  .qrwarn{margin-top:13px;padding:12px 14px;border-radius:12px;font-size:13.5px;line-height:1.7;
    background:rgba(200,120,20,.10);border:1px solid rgba(200,120,20,.35);color:var(--ink)}
  .qrcount{margin-top:8px;font-size:12.5px;color:var(--muted);text-align:center}
  .devrow{display:flex;align-items:center;gap:12px;padding:12px 4px;border-bottom:1px solid var(--line-2)}
  .devi{flex:1;min-width:0;font-size:14.5px;color:var(--ink)}
  .devs{font-size:12.5px;color:var(--muted);margin-top:3px;line-height:1.5}
  .devme{font-size:11.5px;color:var(--muted);border:1px solid var(--line);border-radius:999px;
    padding:2px 8px;margin-left:6px;white-space:nowrap}
  .sheet h2{font-size:24px;font-weight:800;letter-spacing:-.4px;line-height:1.28}
  .sheet .sub{color:var(--muted);font-size:14px;margin:5px 0 18px}
  .sheet p{font-size:14.5px;color:var(--muted);line-height:1.7}
  label{display:block;font-size:13.5px;font-weight:700;color:var(--muted);margin:17px 0 7px}
  .f{width:100%;padding:13px 15px;border-radius:11px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);font-size:15px;font-family:inherit}
  .f:focus{outline:0;border-color:var(--brand)}
  textarea.f{min-height:82px;resize:vertical}
  .row{display:flex;gap:12px;margin-top:24px}
  .b{flex:1;padding:14px;border:0;border-radius:11px;font-size:15px;font-weight:800;cursor:pointer;font-family:inherit}
  .b.go{background:var(--brand);color:#fff}
  .b.go:hover{filter:brightness(1.08)}
  .b.cancel{background:var(--surface-2);color:var(--muted);border:1px solid var(--line)}
  .out{white-space:pre-wrap;margin-top:18px;padding:17px;border-radius:11px;background:var(--surface-2);border:1px solid var(--line);font-family:Consolas,"Malgun Gothic",monospace;font-size:14px;line-height:1.72;display:none;color:var(--ink)}
  .out.on{display:block}
  .out.ok{border-color:var(--good)}
  .fileopen{display:block;width:100%;text-align:left;margin:8px 0;padding:14px 16px;background:var(--surface);border:1px solid var(--line);border-radius:11px;cursor:pointer;color:var(--ink);font-size:14.5px;font-weight:700;font-family:inherit;transition:.14s}
/* 결과 속 전화·주소 — 눌러서 바로 걸고 바로 길찾기 */
.lk{display:inline-flex;align-items:center;min-height:34px;padding:3px 10px;margin:2px 1px;border-radius:9px;
 text-decoration:none;font-weight:700;border:1px solid var(--line);background:var(--surface)}
.lk.tel{color:var(--brand)}.lk.map{color:var(--accent)}.lk.sms{color:var(--brand)}
.rnote{color:var(--muted);padding:2px 0}
a.fileopen.getlink{text-decoration:none;color:var(--brand)}
.only-phone{display:none}   /* 폰 전용 문구 — 폰 규칙에서 다시 켠다 */
@media (max-width:900px){.lk{min-height:44px;padding:6px 13px;font-size:15px}}
  .fileopen:hover{border-color:var(--brand);background:var(--surface-2);transform:translateX(3px)}
  .foot{text-align:center;color:var(--muted);font-size:13.5px;margin:44px 0 14px;line-height:1.9}
  .foot b{color:var(--ink);font-weight:700}
  .quit{margin-top:14px;padding:10px 24px;background:var(--crit-bg);color:var(--crit);border:1px solid color-mix(in srgb,var(--crit) 30%,var(--line));border-radius:11px;cursor:pointer;font-weight:800;font-size:14px;font-family:inherit}
  .quit:hover{background:var(--crit);color:#fff}
  .home{position:fixed;right:24px;bottom:24px;background:var(--brand);color:#fff;border:0;border-radius:50px;padding:14px 24px;font-size:15px;font-weight:800;cursor:pointer;box-shadow:var(--shadow);z-index:18;display:none;font-family:inherit}
  .home.on{display:block}
  .home:hover{transform:translateY(-2px);filter:brightness(1.06)}
  /* ── 일정 캘린더 팝업 ── */
  .calsheet{max-width:700px}
  /* ── 재정 그래프 팝업 ── */
  .finsheet{max-width:820px;max-height:88vh;overflow-y:auto}
  .fin-empty{padding:44px 20px;text-align:center;color:var(--muted);font-size:14px;line-height:1.6}
  .fin-empty2{padding:22px;text-align:center;color:var(--faint);font-size:12.5px}
  .fin-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:6px 0 16px}
  .fk{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:var(--surface-2)}
  .fk small{font-size:12px;color:var(--muted);font-weight:600}
  .fk b{display:block;font-size:20px;font-weight:800;margin-top:4px;letter-spacing:-.3px;font-variant-numeric:tabular-nums}
  .fk.in b{color:#10b981}.fk.out b{color:#ef4444}.fk.bal b{color:var(--brand)}
  .fin-card{border:1px solid var(--line);border-radius:14px;padding:15px 16px 16px;margin-bottom:14px;background:var(--surface)}
  .fin-card h5{font-size:13px;font-weight:800;color:var(--ink);margin-bottom:12px;letter-spacing:-.2px}
  .fin-2col{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  @media (max-width:640px){.fin-2col{grid-template-columns:1fr}.fin-kpis{grid-template-columns:1fr}}
  .fin-svg{width:100%;height:auto;display:block}
  .fin-legend{text-align:center;font-size:12px;color:var(--muted);margin-top:6px}
  .fin-legend .lg{display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:-1px;margin-right:3px}
  .fin-donwrap{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
  .fin-donut{width:120px;height:120px;flex:none}
  .fin-donleg{flex:1;min-width:120px;display:flex;flex-direction:column;gap:5px}
  .dl{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px}
  .dl span{width:10px;height:10px;border-radius:3px;flex:none}
  .dl b{color:var(--ink);font-weight:700;margin-left:auto;font-variant-numeric:tabular-nums}
  .fin-gauge{margin-bottom:12px}
  .gg-lab{display:flex;justify-content:space-between;font-size:12.5px;color:var(--muted);margin-bottom:5px}
  .gg-bar{height:12px;border-radius:7px;background:var(--surface-2);overflow:hidden}
  .gg-fill{height:100%;border-radius:7px;transition:width .5s}
  .gg-over{font-size:11.5px;color:#ef4444;font-weight:700;margin-top:3px}
  .fin-tbl{width:100%;border-collapse:collapse;font-size:12.5px}
  .fin-tbl th{text-align:left;color:var(--faint);font-weight:700;padding:6px 8px;border-bottom:1px solid var(--line)}
  .fin-tbl td{padding:6px 8px;border-bottom:1px solid var(--line);color:var(--ink)}
  .fin-tbl td.ri{text-align:right;font-variant-numeric:tabular-nums}
  .cal-top{display:flex;align-items:center;justify-content:center;gap:18px;margin-bottom:16px}
  .cal-top h2{font-size:21px;min-width:160px;text-align:center;font-weight:800}
  .cal-nav{width:38px;height:38px;border:1px solid var(--line);background:var(--surface-2);border-radius:10px;font-size:22px;line-height:1;cursor:pointer;color:var(--ink)}
  .cal-nav:hover{border-color:var(--accent);color:var(--accent)}
  .cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:5px}
  .cal-dow{text-align:center;font-size:12px;font-weight:800;color:var(--faint);padding:3px 0 6px}
  .cal-dow.sun{color:var(--crit)}
  .cal-cell{min-height:72px;border:1px solid var(--line);border-radius:10px;padding:5px 6px;cursor:pointer;background:var(--surface);transition:.12s;overflow:hidden}
  .cal-cell:hover{border-color:var(--accent);background:var(--surface-2)}
  .cal-cell.empty{border:0;background:transparent;cursor:default}
  .cal-cell.today{border-color:var(--accent);box-shadow:inset 0 0 0 1.5px var(--accent)}
  .cal-cell .dnum{font-size:12.5px;font-weight:700;color:var(--muted)}
  .cal-cell .dnum.sun{color:var(--crit)}
  .cal-ev{font-size:11px;margin-top:2px;padding:1.5px 5px;border-radius:6px;background:var(--brand-soft);color:var(--brand-ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .cal-ev.imp{background:var(--accent-soft);color:var(--accent);font-weight:700}
  .cal-litur{font-size:10px;font-weight:700;margin-top:2px;padding:1.5px 5px;border-radius:6px;background:var(--accent-soft);color:var(--accent);white-space:normal;line-height:1.3}
  .cal-hint{font-size:12px;color:var(--muted);margin-top:13px;text-align:center;line-height:1.6}
/* ★이 폰 블록은 ★스타일 맨 끝에 둔다 — 앞에 두면 뒤에 나오는 기본 규칙(.f·.row 등)이
   같은 우선순위로 덮어써서 ★조용히 안 먹는다. 실제로 첫 판에서 입력창 16px 과
   단추 간격이 그렇게 무시됐다(실험대가 잡았다). 새 폰 규칙은 ★여기 아래에 더한다. */
/* ── 폰 화면 ──────────────────────────────────────────────────────────
   ★재는 자(尺): 손가락 44px · 입력 글자 16px(그보다 작으면 아이폰이 화면을 확대한다) ·
     가로 스크롤 0 · 주요 조작은 ★엄지가 닿는 아래쪽.
   ★머리줄이 한 줄에 다 못 들어가면 ★줄바꿈한다 — 안 그러면 사파리에서 화면이 옆으로 밀린다
     (크롬에서는 안 보이고 아이폰에서만 보이던 결함이라, 두 엔진으로 재서 잡았다). */
@media (max-width:900px){
 .app{grid-template-columns:1fr}.side{display:none}
 .stats{grid-template-columns:repeat(2,1fr)}
 .top{padding:11px 14px;gap:9px;flex-wrap:wrap}
 .top>div:first-child{flex:0 0 auto}
 .top h1{font-size:19px}
 .date{display:none}                        /* 자리를 크게 먹는 장식 — 폰에서는 접는다 */
 .search{order:10;flex:1 0 100%;width:auto;margin-left:0;padding:12px 14px}
 .kbd{display:none}                         /* 폰에는 Ctrl 키가 없다 — 없는 것을 가리키지 않는다 */
 .icobtn{width:44px;height:44px}
 .upd{padding:12px 14px;min-height:44px}
 .quit{min-height:44px;padding:12px 24px}
 .wrap{padding:22px 16px 108px}             /* 아래쪽 이동바에 마지막 카드가 가리지 않게 */
 .grid{grid-template-columns:1fr;gap:13px;margin-bottom:26px}
 .card{padding:17px 17px 16px}
 .card p{font-size:14px;line-height:1.6}    /* 폰에서 읽히는 크기 */
 .sec-h{scroll-margin-top:66px}
 .modal{padding:0;align-items:flex-end}
 .sheet{max-width:none;border-radius:18px 18px 0 0;max-height:92vh;padding:22px 18px calc(20px + env(safe-area-inset-bottom))}
 .f{font-size:16px;padding:14px 15px}       /* ★16px 미만이면 아이폰이 확대한다 */
 .search{padding:6px 14px}
 #search{font-size:16px;min-height:44px}    /* 검색칸도 같은 자(尺)로 — 손가락 44px · 글자 16px */
 .out{font-size:14.5px}
 /* ★[닫기]와 [실행]을 손가락 하나 거리에 두지 않는다 — 잘못 눌러 쓰던 내용이 날아가면 안 된다 */
 .row{flex-direction:column;gap:26px;margin-top:22px}
 .row .b{width:100%;min-height:52px;font-size:16px}
 /* ★엄지가 닿는 ★아래쪽에 오는 것은 [실행]이어야 한다. 처음에 순서를 거꾸로 넣었더니
    [닫기]가 제일 누르기 쉬운 자리에 앉았다 — 하려던 것과 정확히 반대였다(실험대가 잡았다). */
 .row .b.cancel{order:1;min-height:46px;font-size:15px;opacity:.9}
 .row .b.go{order:2}
 /* ★[실행]을 창 바닥에 붙여 둔다 — 칸이 많은 카드(교우 등록은 칸이 스무 개 가까이다)에서는
    단추가 화면 두 배 아래에 있어 ★한참 굴려야 나왔다. 심방지에서 그 한 번이 번거롭다.
    ★자판이 올라와도 가려지지 않는다. [닫기]와의 26px 간격과 순서(실행이 아래)는 그대로 둔다. */
 /* ★간격은 26px 을 지킨다 — 바닥에 붙이면서 촘촘하게 만들고 싶은 마음이 들지만,
    [닫기]와 [실행]이 손가락 하나 거리에 붙으면 안 된다는 쪽이 우선이다.
    (처음에 14px 로 줄였다가 회귀 시험이 잡았다 — 붙여 놓고 잘못 누르시면 쓰던 내용이 날아간다.) */
 #mact{position:sticky;bottom:0;z-index:3;margin-top:16px;padding:12px 0 6px;
   background:var(--surface);border-top:1px solid var(--line-2);gap:26px}
 #mact .b.cancel{min-height:44px;opacity:.85}
 .home{display:none!important}              /* 아래 이동바가 그 일을 대신한다 */
}
/* ★★[접기 2026-08-29 · master 승인 ㉮㉯] — 폰 첫 화면에 카드가 보이게 한다 ★★
   ★왜: 폰 세로(390x844)에서 ★카드 앞이 652px(화면의 77%)이라 첫 화면에 카드가
     ★한 장도 온전히 보이지 않았다(실측). 카드를 33장 합쳐도 그대로 0장이었다 —
     막고 있던 것은 ★장수가 아니라 ★카드 앞 여백과 ★카드 한 장의 키였다.
   ★되돌리기(한 자리): 이 블록(★[접기…] 시작~끝)과 아래 JS 의 ★[접기] 표시 3곳만 지우면 원래대로. */
.card .more{display:none}            /* PC 에서는 안 낸다 — 세로가 길어 접을 이유가 없다 */
@media (max-width:900px){
 /* ㉯ 머리블록 — 인사말은 접고, ★통계는 지우지 않고 «한 줄»로 줄인다.
    ★통계를 없애지 않는 이유: 그 숫자는 ★실제 자료다(교인·이번주 심방·이달 헌금·다가오는 생일 —
      화면이 열릴 때 대시보드가 채운다). 주인님이 폰에서 매일 보시는 것을 조용히 없애면
      «줄이기»가 아니라 ★«빼앗기»가 된다. 그래서 ★지우지 않고 작게 만든다. */
 #ledewrap{display:none}
 .stats{grid-template-columns:repeat(4,1fr);gap:7px;margin-bottom:16px}
 .stat{padding:9px 6px;border-radius:12px}
 .stat .lbl{font-size:10px;letter-spacing:0;gap:3px}
 .stat .lbl .si{display:none}
 .stat .num{font-size:18px;margin-top:5px;letter-spacing:-.5px}
 .stat .sub{display:none}
 /* ㉮ 설명문 3줄 접기 — ★반드시 [더보기]로 펼 수 있어야 한다.
    ★왜 단추가 없으면 안 되나: 카드 설명은 ★카드 격자에만 나온다. 카드를 눌러 열리는 창에는
      ★설명이 없다(그 창은 제목과 입력칸만 그린다). 그래서 그냥 자르면
      «★프로그램이 문자를 보내지 않습니다» 같은 ★안내가 폰에서 ★영영 안 보이게 된다.
      안 되는 것을 안 된다고 적어 둔 문장이 사라지면 그건 줄이기가 아니라 ★거짓이 된다. */
 .card p:not(.open){display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
 .card .more{display:inline-block;margin-top:6px;font-size:13.5px;font-weight:700;
   color:var(--accent);background:none;border:0;padding:4px 0;font-family:inherit;cursor:pointer}
 /* ★검색 중에는 ★접지 않는다 — 찾으신 낱말이 ★접힌 아래에 있으면
    «찾았습니다»라고 써 놓고 ★무엇이 걸렸는지 안 보인다(되는데 된 줄 모른다). */
 #app.searching .card p{-webkit-line-clamp:unset;display:block;overflow:visible}
 #app.searching .card .more{display:none}
}
/* ★★[접기 2026-08-29] 끝 ★★ */
/* 아래쪽 이동바 — 엄지가 닿는 자리. 폰에서만 나온다. */
.tabbar{display:none}
@media (max-width:900px){
 .tabbar{display:grid;grid-template-columns:repeat(3,1fr);position:fixed;left:0;right:0;bottom:0;z-index:19;
   background:color-mix(in srgb,var(--paper) 94%,transparent);backdrop-filter:blur(10px);
   border-top:1px solid var(--line);padding-bottom:env(safe-area-inset-bottom)}
 .tabbar button{background:none;border:0;font-family:inherit;color:var(--muted);cursor:pointer;
   min-height:56px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;
   font-size:12px;font-weight:700;padding:6px 4px}
 .tabbar button b{font-size:19px;font-weight:400;line-height:1}
 .tabbar button.on{color:var(--brand)}
 .gsheet{position:fixed;inset:0;z-index:21;display:none;background:rgba(10,12,20,.5);backdrop-filter:blur(5px)}
 .gsheet.on{display:block}
 .gsheet .gs-in{position:absolute;left:0;right:0;bottom:0;max-height:78vh;overflow:auto;
   background:var(--surface);border-top:1px solid var(--line);border-radius:18px 18px 0 0;
   padding:16px 14px calc(18px + env(safe-area-inset-bottom))}
 .gsheet h3{font-size:16px;margin:2px 4px 12px;color:var(--ink)}
 .gsheet a{display:flex;align-items:center;gap:11px;min-height:52px;padding:8px 12px;border-radius:12px;
   color:var(--ink);text-decoration:none;font-size:15.5px;font-weight:700;border:1px solid var(--line-2);margin-bottom:8px}
 .gsheet a .gi{font-size:19px}
 .gsheet a .gc{margin-left:auto;font-size:12.5px;color:var(--muted);font-weight:600}
 /* ★화면 문구가 화면과 어긋나지 않게 — 폰에는 왼쪽 메뉴가 없다.
    없는 것을 가리키면 목사님은 그 없는 것을 찾으신다. */
 .only-pc{display:none}
 .only-phone{display:inline}
 /* ★열리는 판(테마·알림)이 화면 밖으로 잘려나가지 않게 — 오른쪽 끝 단추에 붙어 열리므로
    좁은 화면에서는 판의 오른쪽이 통째로 잘렸다(요소 22~24개가 화면 밖이었다). */
 .themepanel,.notifpanel{position:fixed;top:auto;bottom:calc(58px + env(safe-area-inset-bottom));
   left:10px;right:10px;width:auto;max-height:62vh;overflow:auto}
 .themepanel .tp-row{flex-wrap:wrap}
 .themepanel button,.notifpanel button{min-height:44px}
 /* ★큰 표는 가로로 스크롤되게 담는다 — 담는 그릇이 없으면 표가 화면을 밀거나 잘린다 */
 .calsheet,.finsheet{max-width:none}
 .cal-grid{min-width:322px}
 #fin_body{overflow-x:auto;-webkit-overflow-scrolling:touch}
 #fin_body table,.finsheet table{min-width:520px}
}
/* ★아이폰 사파리는 주소창 때문에 100vh 가 ★실제로 보이는 높이보다 크다 —
   그 차이만큼 화면 아래가 잘린다. 특히 ★로그인 화면이 잘리면 심방지에서 못 들어가신다.
   dvh(실제로 보이는 높이)를 쓰되, 모르는 브라우저를 위해 100vh 를 먼저 적어 둔다. */
@supports (height:100dvh){
 .app{min-height:100dvh}
 .side{height:100dvh}
 .loginwrap{min-height:100dvh}
}
</style></head><body>
<div class="app">
  <aside class="side">
    <div class="brand" onclick="goHome()" title="전체 메뉴로 돌아가기">
      <div class="mark"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.9" stroke-linecap="round"><path d="M12 3v18M7 8h10M4 21h16M6 21v-9l6-4 6 4v9"/></svg></div>
      <div><b>__CHURCH__</b><span>종합행정 · Pro</span></div>
    </div>
    <nav class="nav" id="nav"></nav>
    <div class="side-foot">
      <div class="ava" id="avatarInit">·</div>
      <div><b id="pastorName">__PASTOR__</b><small>담임 · __CHURCH__</small></div>
    </div>
    <div class="credit" style="padding:11px 14px 14px;font-size:11.5px;line-height:1.6;color:var(--muted);border-top:1px solid var(--line-2)"><b style="color:var(--ink)">제작 · 저작권 ⓒ 2026 김용원(세움교회)</b><br>목회 목적 사용 자유 · 무단 복제 · 재판매 금지</div>
  </aside>

  <div class="main">
    <header class="top">
      <div><h1>대시보드</h1></div>
      <div class="date" id="today"></div>
      <div class="search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="search" placeholder="교인·설교·재정·서식 검색"><span class="kbd">Ctrl K</span></div>
      <button class="upd" onclick="updateApp()" title="최신 버전으로 안전 업데이트 (자료 보존)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v11M8 10l4 4 4-4M5 21h14"/></svg>업데이트</button>
      <button class="upd" onclick="toggleEdit()" id="tidybtn" title="안 쓰는 카드를 숨겨 화면을 깔끔하게 — 각 카드의 숨기기/복원 버튼으로. 설정에 저장되고 자료와는 무관합니다.">🧹 화면 정리</button>
      <button class="upd" onclick="openPhone()" id="phonebtn" title="폰으로 보기 — 화면에 QR 을 띄웁니다. 폰 카메라로 비추면 비밀번호 없이 열립니다.">📱 폰으로 보기</button>
      <!-- ★「나가기」 — 폰·빌린 기기에서만 나온다 (2026-08-27 · reviewer R2-N2 · master 재정).
           ★왜 없으면 안 되나: 로그인 화면의 «다른 분 폰이나 빌린 기기로 잠깐 보실 때 꺼 주세요»는
             ★끄는 방법을 함께 주지 않으면 지킬 수 없는 권유다. 나가는 문이 화면에 없었다.
           ★사무실 컴퓨터에는 «내지» 않는다 — 거기서 나가시면 열쇠로 다시 들어오셔야 해서 번거롭다.
           ★★정확히 적는다(reviewer R3 §5): 이것은 ★보이고 안 보이는 축이지 ★권한 축이 아니다.
             사무실 화면의 HTML 에도 이 단추는 ★들어 있고 스타일로만 숨긴다. 즉 «폰만 나갈 수 있다»가
             아니라 «폰에만 보여 드린다»가 참이다.
             ★그리고 서버에 local 거부를 넣지 ★않는다 — 넣으면 사무실에서 나갈 길이 아예 없어진다. -->
      <button class="upd" onclick="doLogout()" id="logoutbtn" style="display:none"
        title="이 폰에서 나갑니다 — 빌린 기기나 다른 분 폰으로 보셨을 때 꼭 눌러 주세요.">🚪 나가기</button>
      <div class="themewrap">
        <div class="icobtn theme-tgl" onclick="toggleThemePanel(event)" title="테마·색상·계절 배경"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5.2 5.2l1.7 1.7M17.1 17.1l1.7 1.7M18.8 5.2l-1.7 1.7M6.9 17.1l-1.7 1.7"/></svg></div>
        <div class="themepanel" id="themepanel" onclick="event.stopPropagation()">
          <div class="tp-h">화면 밝기</div>
          <div class="tp-row"><button onclick="setMode('light')">밝게</button><button onclick="setMode('dark')">어둡게</button></div>
          <div class="tp-h">포인트 색</div>
          <div class="tp-sw">
            <span class="sw" style="background:#1F6E5A" onclick="setColor('')" title="기본(초록)"></span>
            <span class="sw" style="background:#2E7DA9" onclick="setColor('blue')" title="바다"></span>
            <span class="sw" style="background:#C05575" onclick="setColor('rose')" title="로즈"></span>
            <span class="sw" style="background:#7C5FC0" onclick="setColor('purple')" title="보라"></span>
            <span class="sw" style="background:#D07C2E" onclick="setColor('orange')" title="주황"></span>
          </div>
          <div class="tp-h">계절 배경</div>
          <div class="tp-row"><button onclick="setSeason('')">없음</button><button onclick="setSeason('spring')">봄</button><button onclick="setSeason('summer')">여름</button><button onclick="setSeason('autumn')">가을</button><button onclick="setSeason('winter')">겨울</button></div>
          <div class="tp-h">내 사진 배경</div>
          <div class="tp-photos" id="tp_photos"></div>
          <label class="tp-add"><input type="file" accept="image/*" onchange="uploadBg(this)" hidden>＋ 사진 추가</label>
          <div class="tp-hint">가족·자녀 사진, 교회 사진, 좋아하는 풍경을 배경으로 — ＋ 버튼으로 바로 올리거나, _내자료 › 배경 폴더에 넣어도 됩니다.</div>
        </div>
      </div>
      <div class="notifwrap">
        <div class="icobtn" onclick="toggleNotif(event)" title="알림"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg><span class="dot" id="notif_dot" style="display:none"></span></div>
        <div class="notifpanel" id="notifpanel" onclick="event.stopPropagation()">
          <div class="np-h">오늘의 알림</div>
          <div id="notif_list"></div>
        </div>
      </div>
    </header>

    <div class="wrap">
      <div class="lede" id="ledewrap">
        <div>
          <h2>평안하세요, 목사님 🙏</h2>
          <p>필요한 기능을 바로 실행하세요. <span class="only-pc">왼쪽 메뉴에서 분류로 이동할 수 있습니다.</span><span class="only-phone">아래 「☰ 분류」를 누르면 분류로 바로 이동합니다.</span></p>
        </div>
      </div>

      <!-- 요약 대시보드 — 여기 마크업은 «—» 자리만 잡고, ★값은 loadStats() 가 /stats 에서 실측으로 채운다
           (/stats → church.py dashboard 실행 → 출력의 DASH 마커 줄이 JSON).
           ★숫자를 이 마크업에 직접 적지 마라 — 적는 순간 그 숫자는 거짓이 된다.
           ★2026-08-29: 종전 주석이 «정적 플레이스홀더(실측 데이터 아님)»이라고 말해 코드가 고쳐진 뒤에도
             읽는 사람이 «가짜 숫자»로 오판했다. 낡은 기록은 지우는 것보다 ★출처를 가리키게 고친다. -->
      <div class="stats" id="statwrap">
        <div class="stat">
          <div class="lbl"><svg class="si" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="3.4"/><path d="M5 20c0-3.3 3-5 7-5s7 1.7 7 5"/></svg>등록 교인</div>
          <div class="num tnum" id="st_mem">—</div>
          <div class="sub" id="sb_mem">명부에서 집계</div>
        </div>
        <div class="stat">
          <div class="lbl"><svg class="si" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 21s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.5-7 10-7 10z"/></svg>이번 주 심방</div>
          <div class="num tnum" id="st_visit">—</div>
          <div class="sub" id="sb_visit">이번 주 심방 기록</div>
        </div>
        <div class="stat">
          <div class="lbl"><svg class="si" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v10M9.5 9.5h4a1.5 1.5 0 0 1 0 3h-3a1.5 1.5 0 0 0 0 3h4"/></svg>이달 헌금</div>
          <div class="num tnum" id="st_off">—</div>
          <div class="sub" id="sb_off">이번 달 수입 합계</div>
        </div>
        <div class="stat" id="card_bday" style="cursor:pointer" title="눌러서 오늘·다가오는 생일 축하 카톡 만들기">
          <div class="lbl"><svg class="si" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 4h18v4H3zM4 8v12h16V8"/></svg>다가오는 생일</div>
          <div class="num tnum" id="st_bday">—</div>
          <div class="sub" id="sb_bday">앞으로 7일 이내</div>
        </div>
      </div>

      <div class="brief" id="brief" style="display:none">
        <div class="brief-h"><span class="dotm"></span><span class="t">오늘의 목회 브리핑</span><span class="d" id="brief_date"></span></div>
        <div id="brief_rows"></div>
      </div>

      <div id="app"></div>

      <!-- ★«(재정 출납부·원장)» 은 옛 판에서 새로 생긴 기능을 적어 둔 꼬리표였다.
           판이 바뀌어도 그 글자만 남아 ★낡은 말이 화면에 붙어 있었다(기억 church-code-text-sync).
           버전 옆에는 ★버전만 적는다 — 무엇이 새로운지는 업데이트 안내가 말한다. -->
      <div class="foot">자료는 내 컴퓨터에 안전 저장 · <b>버전 v__VERSION__</b><br>
        <button class="quit" onclick="quitApp()">⏻ 프로그램 종료</button></div>
    </div>
  </div>
</div>
<!-- 폰 아래쪽 이동바 — 사이드바가 접히는 폭에서 그 자리를 대신한다.
     ★엄지가 닿는 아래쪽에 둔다(차에서 내리며 한 손으로 쓰신다). -->
<nav class="tabbar" id="tabbar">
  <button onclick="goHome()" title="처음 화면"><b>🏠</b>처음</button>
  <button onclick="focusSearch()" title="검색"><b>🔎</b>검색</button>
  <button onclick="openGroups()" id="tab_g" title="분류로 이동"><b>☰</b>분류</button>
</nav>
<div class="gsheet" id="gsheet" onclick="if(event.target.id==='gsheet')closeGroups()">
  <div class="gs-in"><h3>어디로 갈까요</h3><div id="gs_list"></div></div>
</div>
<div class="modal" id="welcome"><div class="sheet">
 <h2>👋 환영합니다, 목사님!</h2><div class="sub">__CHURCH__ 교회 종합행정</div>
 <p>위쪽 <b>카드</b>를 누르면 바로 사용됩니다. 만든 문서는 번호 폴더에 자동 정리되고, 입력한 자료는 <b>영구 보존</b>됩니다. 처음이시면 아래 <b>사용 설명서</b>를 먼저 만들어 읽어보세요.</p>
 <div class="row"><button class="b cancel" onclick=closeW()>바로 시작</button><button class="b go" onclick="openWhy()">✨ 이 프로그램의 강점</button><button class="b go" onclick=makeManual()>📘 사용 설명서 만들기</button></div>
 <div class="out" id="wout"></div>
</div></div>
<div class="modal" id="modal"><div class="sheet">
 <h2 id="mt"></h2><div class="sub" id="ms"></div><div id="mf"></div>
 <div class="row" id="mact"><button class="b cancel" onclick=closeM()>닫기</button><button class="b go" id="mgo">실행</button></div>
 <div class="row" style="margin-top:6px"><button class="b cancel" id="mprev" onclick="browsePrev(this)" style="flex:1;font-size:.92em">📂 지난 자료 찾기 — 내 PC(C·D·USB)에서 예전 작업 열기</button></div>
 <div class="out" id="mo"></div>
</div></div>
<div class="modal" id="calmodal"><div class="sheet calsheet">
 <div class="cal-top"><button class="cal-nav" onclick="calNav(-1)">‹</button><h2 id="cal_title"></h2><button class="cal-nav" onclick="calNav(1)">›</button></div>
 <div class="cal-grid" id="cal_grid"></div>
 <div class="cal-hint">날짜를 누르면 그 날 일정을 추가합니다(제목 앞에 ★를 붙이면 중요 일정). 일정을 누르면 삭제됩니다.</div>
 <div class="row"><button class="b cancel" onclick="closeCal()">닫기</button><button class="b go" onclick="calPrint()">이 달 달력 인쇄</button></div>
</div></div>
<div class="modal" id="finmodal"><div class="sheet finsheet">
 <div class="cal-top"><button class="cal-nav" onclick="finNav(-1)">‹</button><h2 id="fin_title"></h2><button class="cal-nav" onclick="finNav(1)">›</button></div>
 <div id="fin_body"></div>
 <div class="row"><button class="b cancel" onclick="closeFin()">닫기</button><button class="b go" onclick="window.print()">인쇄</button></div>
</div></div>
<!-- ── 📱 폰으로 보기 ─────────────────────────────────────────────────────
     ★목사님이 하실 일은 «📱 누르기 → QR 비추기 → 홈 화면에 추가» 세 번이다.
       그 이상 하시게 만들면 이 화면은 실패다. 그래서 여기서 ★설정 카드로 내보내지 않는다 —
       폰 접속이 꺼져 있으면 이 자리에서 켜 드린다. -->
<div class="modal" id="qrmodal" onclick="if(event.target.id==='qrmodal')closeQR()"><div class="sheet">
 <h2>📱 폰으로 보기</h2>
 <div class="sub">폰 카메라로 QR 을 비추기만 하면 됩니다 — 비밀번호를 넣지 않으셔도 열립니다</div>
 <div id="qr_body">준비 중…</div>
 <div class="row"><button class="b cancel" onclick="closeQR()">닫기</button>
   <button class="b go" id="qr_again" onclick="openPhone()">🔄 새 QR 만들기</button>
   <button class="b cancel" onclick="openDevices()">🖥 지금 들어와 있는 기기</button></div>
</div></div>
<!-- ── 🖥 지금 들어와 있는 기기 ─────────────────────────────────────────────
     ★왜 있나: QR 을 주운 기기가 있어도 목사님이 ★알 방법이 없었다(reviewer 지적).
       열쇠는 3분이지만 그것이 만드는 ★열람권은 30일이라, «본다 · 끊는다»가 있어야 한다. -->
<div class="modal" id="devmodal" onclick="if(event.target.id==='devmodal')closeDevices()"><div class="sheet">
 <h2>🖥 지금 들어와 있는 기기</h2>
 <div class="sub">모르는 기기가 있으면 그 기기만 끊으실 수 있습니다</div>
 <div id="dev_body">불러오는 중…</div>
 <div class="row"><button class="b cancel" onclick="closeDevices()">닫기</button>
   <button class="b go" onclick="openDevices()">🔄 새로고침</button></div>
</div></div>
<!-- ── 🏠 홈 화면에 추가 (폰에서 처음 들어오셨을 때 한 번) ──────────────────
     ★크롬의 «설치» 알림은 http 주소에서는 안 뜰 수 있다. 그래서 ★손 안내를 항상 띄우고,
       알림이 뜨는 경우에만 «설치» 단추가 ★덧붙는다. 「되겠지」로 비워 두지 않는다. -->
<!-- ── ✅ QR 로 들어오신 직후 (한 번) ─────────────────────────────────────────
     ★기억은 예전에도 했다. 안 한 것은 ★그 사실을 말하는 것이었다.
     ★그래서 이 자리에 «껐다 켜는 길»을 같이 둔다 — 끊을 수 없는 기억은 뒷문이다. -->
<div class="modal" id="qrok"><div class="sheet">
 <h2>✅ 이 폰을 기억했습니다</h2>
 <div class="sub">다음부터는 <b>비밀번호를 묻지 않습니다</b> — 홈 화면 아이콘만 누르시면 바로 열립니다</div>
 <div class="note" id="qrok_note"></div>
 <div class="row">
   <button class="b go" onclick="closeQrOk(true)">좋습니다</button>
   <button class="b cancel" onclick="qrForget(this)">이 폰은 기억하지 않기</button></div>
 <div class="note" style="margin-top:10px"><b>이 기억을 끊고 싶으실 때</b><br>
  ① <b>이 폰에서</b> — 위의 <b>「이 폰은 기억하지 않기」</b>를 누르시면 12시간 뒤부터 다시 여쭙습니다.<br>
  ② <b>사무실 컴퓨터에서</b> — 프로그램 화면의 <b>「📱 폰 접속 설정」</b> 카드를 여시면
     <b>지금 들어와 있는 기기</b> 목록이 나옵니다. 거기서 이 폰 옆의 <b>「끊기」</b>를 누르세요.<br>
  ③ <b>폰을 잃어버리셨다면</b> — 같은 카드의 <b>「폰을 잃어버리셨다면 1」</b>에 <b>1</b>을 넣고 실행하시면
     <b>모든 폰이 한 번에</b> 끊깁니다(사무실 컴퓨터는 그대로 쓰십니다).</div>
</div></div>
<div class="modal" id="a2hs"><div class="sheet">
 <h2>🏠 홈 화면에 두시면 더 편합니다</h2>
 <div class="sub">다음부터는 아이콘 한 번으로 바로 열립니다 — 주소를 다시 치실 필요가 없습니다</div>
 <div class="note" id="a2hs_how"></div>
 <div class="row">
   <button class="b go" id="a2hs_btn" style="display:none" onclick="a2hsInstall()">📲 홈 화면에 추가</button>
   <button class="b cancel" onclick="closeA2HS()">알겠습니다</button></div>
</div></div>
<div class="modal" id="whymodal"><div class="sheet">
 <h2>✨ 이 프로그램의 강점</h2><div class="sub">작은 교회 목회, 이 한 곳에서</div>
 <div style="background:var(--brand-soft);border:1px solid var(--line);border-radius:12px;padding:13px 15px;margin:12px 0;font-size:14px;line-height:1.65;color:var(--ink)">🔒 <b>교인 정보는 목사님 컴퓨터 안에서만.</b> 교인 명단·심방기록·헌금내역 같은 소중한 정보를 외부 온라인 서비스에 올리지 않고, 목사님 PC 안에서 안전하게 관리하고 활용합니다.</div>
 <div style="font-size:14px;line-height:1.65;color:var(--ink)">
  <div style="padding:9px 4px;border-bottom:1px solid var(--line-2)">📇 <b>쌓이고 연결됩니다</b> — 교적·심방·생일·헌금·결산이 하나로 이어져, 쓸수록 브리핑과 통계가 정확해집니다.</div>
  <div style="padding:9px 4px;border-bottom:1px solid var(--line-2)">📝 <b>누르면 완성되는 서식</b> — 설교문·주보·증명서·결산서를 한글 문서로 클릭 한 번에.</div>
  <div style="padding:9px 4px;border-bottom:1px solid var(--line-2)">💰 <b>작은 교회 재정에 강합니다</b> — 월별 결산·부서별 집계·연간 총결산을 그래프와 함께.</div>
  <div style="padding:9px 4px">📚 <b>내 서재로 하는 설교연구</b> — 목사님이 모으신 주석·장서를 바탕으로 깊이 있게(NotebookLM 연동).</div>
 </div>
 <p style="font-size:14.5px;margin:14px 2px 2px;color:var(--ink)">흩어진 목회 실무를 <b>한 곳에서</b> — 작은 교회 목사님을 위한 정성입니다.</p>
 <div class="row"><button class="b go" onclick="closeWhy()">닫기</button></div>
</div></div>
<button class="home" id="homebtn" onclick="goHome()">⌂ 전체 메뉴</button>
<script>
var A=__ACTIONS__;
var REMOTE=__REMOTE__;   // 폰·바깥 기기에서 열었는가(사무실 컴퓨터면 false)
// ★폰에서는 '지난 자료 찾기(내 PC 열기)' 단추를 ★내지 않는다.
//   눌러도 사무실 컴퓨터의 탐색기가 열릴 뿐 폰에는 아무 일도 일어나지 않는다(서버가 막는다).
//   게다가 이 단추는 서버 응답을 보지 않고 언제나 '📂 내 PC 열림' 이라고 적어서
//   ★안 된 일을 됐다고 말했다(2026-08-17 적발). 안 되는 것은 보여 주지 않는다.
if(REMOTE){try{var _mp=document.getElementById('mprev');
 if(_mp)(_mp.parentNode||_mp).style.display='none';}catch(e){}
 /* ★폰에서는 「📱 폰으로 보기」를 내지 않는다 — 이미 폰으로 보고 계시고,
    QR 은 사무실 화면에서만 만들어진다(눌러도 안 되는 단추를 두지 않는다). */
 try{var _pb=document.getElementById('phonebtn'); if(_pb)_pb.style.display='none';}catch(e){}
 /* ★대신 「나가기」를 낸다 — 빌린 기기에서 스스로 나오실 수 있어야 한다. */
 try{var _lb=document.getElementById('logoutbtn'); if(_lb)_lb.style.display='';}catch(e){}}
function doLogout(){
 if(!confirm('이 폰에서 나가시겠습니까?'+String.fromCharCode(10)+String.fromCharCode(10)
   +'다시 보시려면 비밀번호를 넣으시거나,'+String.fromCharCode(10)
   +'사무실 컴퓨터에서 QR 을 다시 띄워 찍으시면 됩니다.'))return;
 fetch('/logout',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:'{}'})
  .then(function(){location.href='/';})
  .catch(function(){location.href='/';});   /* 실패해도 화면은 로그인으로 — 남겨 두지 않는다 */
}
var HIDDEN=__HIDDEN__;var editMode=false;
function toggleEdit(){editMode=!editMode;var b=document.getElementById('tidybtn');if(b)b.textContent=editMode?'✓ 정리 끝내기':'🧹 화면 정리';render((document.getElementById('q')||{}).value||'');}
function cardVis(cmd,hide){fetch('/run',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:JSON.stringify({cmd:'card-vis',args:{name:cmd,act:hide?'hide':'show'}})}).then(function(){if(hide){if(HIDDEN.indexOf(cmd)<0)HIDDEN.push(cmd);}else{HIDDEN=HIDDEN.filter(function(x){return x!==cmd;});}render((document.getElementById('q')||{}).value||'');});}
var NETERR='⚠ 프로그램 서버에 연결할 수 없습니다.'+String.fromCharCode(10)+'★ 교회행정 시작 파일을 다시 더블클릭(실행)한 뒤,'+String.fromCharCode(10)+'이 창을 새로고침(F5)하고 다시 눌러주세요.';
function isNet(e){var s=String(e);return s.indexOf('fetch')>=0||s.indexOf('Failed')>=0||s.indexOf('NetworkError')>=0;}
var COLORS={"📖 자료":"#0f766e","목양":"#10b981","예배·설교":"#f43f5e","성례":"#0ea5e9","성경자료":"#6366f1","목회 참고자료":"#8b5cf6","다음세대(주일학교)":"#ec4899","영성":"#7c3aed","찬양":"#8b5cf6","영상·홍보":"#c026d3","사역":"#f59e0b","전도":"#16a34a","선교":"#0d9488","재정":"#3b82f6","행정서식":"#0891b2","출력·파일":"#14b8a6","시스템":"#64748b"};
var GROUP_ICON={"📖 자료":"📖","목양":"🙌","예배·설교":"✝️","성례":"💧","성경자료":"📖","목회 참고자료":"📚","다음세대(주일학교)":"🎒","영성":"✝️","행정서식":"🗂️","찬양":"🎶","영상·홍보":"🎬","사역":"📅","전도":"🌾","선교":"🌏","재정":"💵","출력·파일":"📂","시스템":"⚙️"};
// 섹션 안의 소그룹 — 구분선 + 다른 색조로 시각 구분 (전도 섹션 안 새생명축제)
var SUBGROUPS={"전도":{cmds:["vip-add","ref-harvest","harvest-plan","harvest-checklist"],label:"🌾 새생명축제 (태신자 초청잔치)",color:"#d97706"}};
var app=document.getElementById('app');
var GROUPS=[];A.forEach(function(a){if(GROUPS.indexOf(a[0])<0)GROUPS.push(a[0]);});
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');}
function setNav(i){var links=document.querySelectorAll('.nav a');for(var k=0;k<links.length;k++)links[k].className=(k===i)?'on':'';}
function buildNav(){var nav=document.getElementById('nav');if(!nav)return;nav.innerHTML='';
 GROUPS.forEach(function(g,i){var a=document.createElement('a');a.className=(i===0)?'on':'';
  a.innerHTML='<span class="i">'+(GROUP_ICON[g]||'•')+'</span>'+esc(g);
  a.onclick=function(){navGo(i);};nav.appendChild(a);});
}
function navGo(i){var s=document.getElementById('search');if(s)s.value='';render('');setNav(i);
 var el=document.getElementById('sec'+i);if(el)el.scrollIntoView({behavior:'smooth',block:'start'});_toggleHome();}
// ── 폰 아래쪽 이동바 ──────────────────────────────────────────────
// 사이드바가 접히면 분류로 갈 길이 없어진다. 카드가 116개라 처음부터 훑으면
// 화면을 25,000px 넘게 내리셔야 한다 — 그래서 아래쪽에 분류 시트를 둔다.
function buildGroupSheet(){var w=document.getElementById('gs_list');if(!w)return;w.innerHTML='';
 GROUPS.forEach(function(g,i){
  var n=A.filter(function(a){return a[0]===g && HIDDEN.indexOf(a[1])<0;}).length;
  if(!n)return;
  var a=document.createElement('a');a.href='javascript:void(0)';
  a.innerHTML='<span class="gi">'+(GROUP_ICON[g]||'•')+'</span><span>'+esc(g)+'</span><span class="gc">'+n+'개</span>';
  a.onclick=function(){closeGroups();navGo(i);};
  w.appendChild(a);});
}
function openGroups(){buildGroupSheet();document.getElementById('gsheet').classList.add('on');_pushStep();
 var t=document.getElementById('tab_g');if(t)t.className='on';}
function closeGroups(){document.getElementById('gsheet').classList.remove('on');
 var t=document.getElementById('tab_g');if(t)t.className='';}
function focusSearch(){var s=document.getElementById('search');if(!s)return;
 window.scrollTo({top:0,behavior:'smooth'});setTimeout(function(){s.focus();},250);}
/* ★검색 중에는 ★위 블록을 접는다 (주인님 발견 2026-08-29 · master 지시)
   ★왜: 검색은 타이핑마다 ★이미 실행되고 있었다. 그런데 다시 그리는 것은 #app 뿐이라
     ★통계 카드와 ★브리핑이 그대로 남아, ★폰 세로 화면에서는 결과가 ★접힌 아래로 밀렸다.
     ⇒ 주인님은 «검색이 안 된다»고 보셨지만 ★되고 있었고 결과가 ★화면 밖에 있었다.
     ★PC 는 세로가 길어 같이 보인다 — 그래서 아무도 몰랐다.
   ★지우지 않고 ★접는다(display:none) — 비우면 되돌리기가 어렵다.
   ★폰·PC ★둘 다 접는다(내 판단): 검색 중에는 통계·브리핑이 ★결과와 무관하고,
     화면 폭으로 나누면 ★경계에서 다르게 동작해 «왜 어떤 때는 접히지»가 생긴다. ★한 가지로 둔다.
   ★«오늘의 브리핑»은 ★내용이 있을 때만 보이는 블록이라, ★접기 전 상태를 기억했다가 그대로 되돌린다. */
var _foldPrev=null;
function _searchFold(on){
 /* ★접는 것 셋: 인사말·통계·브리핑 (master 확정 2026-08-29 03:4x)
    ★앞 회차엔 인사말을 뺐는데 ★지시 범위에 들어왔다 — 폰 세로에서 그 칸도 자리를 차지한다. */
 var ld=document.getElementById('ledewrap'),st=document.getElementById('statwrap'),bf=document.getElementById('brief');
 if(on){
  if(_foldPrev===null)_foldPrev={ld:(ld?ld.style.display:''),st:(st?st.style.display:''),bf:(bf?bf.style.display:'')};
  if(ld)ld.style.display='none';
  if(st)st.style.display='none';
  if(bf)bf.style.display='none';
 }else if(_foldPrev!==null){
  if(ld)ld.style.display=_foldPrev.ld;
  if(st)st.style.display=_foldPrev.st;
  if(bf)bf.style.display=_foldPrev.bf;
  _foldPrev=null;
 }
}
/* ★[접기 2026-08-29] 설명문 펼치기·접기.
   ★카드 열기(openM)와 겹치지 않게 이벤트를 여기서 멈춘다 — 안 멈추면 더보기를 누를 때 카드가 열린다. */
function moreT(e,el){e.stopPropagation();
 var p=el.parentNode.querySelector('p'); if(!p)return;
 var open=p.classList.toggle('open');
 el.textContent=open?'접기':'… 더보기';}
function render(q){
 app.innerHTML='';q=(q||'').toLowerCase();
 /* ★[접기 2026-08-29] 검색 중에는 설명문을 ★펴 둔다 — 걸린 낱말이 접힌 아래 있으면
    «찾았습니다»만 뜨고 ★무엇이 걸렸는지 안 보인다(되는데 된 줄 모르는 상태). */
 try{app.classList.toggle('searching',!!q);}catch(e){}
 var _found=0;
 GROUPS.forEach(function(g){
  var items=A.filter(function(a){return a[0]===g && (editMode||HIDDEN.indexOf(a[1])<0) && (!q || (a[1]+a[2]+(a[5]||'')+JSON.stringify(a[4]||'')).toLowerCase().indexOf(q)>=0);});
  if(!items.length)return;
  _found+=items.length;
  var col=COLORS[g]||'#6366f1';var gi=GROUPS.indexOf(g);
  var h=document.createElement('div');h.className='sec-h';h.id='sec'+gi;
  h.innerHTML='<span class="dotm" style="background:'+col+'"></span><h3>'+esc(g)+'</h3><span class="cnt">'+items.length+'개 기능</span><span class="rule"></span>';
  app.appendChild(h);
  var grid=document.createElement('div');grid.className='grid';
  var SUB=SUBGROUPS[g],_lastSub=null;
  items.forEach(function(a){
   var insub=(SUB && SUB.cmds.indexOf(a[1])>=0);
   if(SUB && a[1]===SUB.cmds[0]){   // 소그룹 첫 카드 앞에 구분선(라벨)
    var sd=document.createElement('div');sd.className='sub-div';sd.style.setProperty('--sc',SUB.color);
    sd.innerHTML='<span></span><b>'+esc(SUB.label)+'</b><span></span>';grid.appendChild(sd);
   }
   var cc=insub?SUB.color:col;
   var feat=(a[1]==='nlm-add');
   var d=document.createElement('div');d.className=(feat?'card feat':'card')+(insub?' subc':'');
   if(insub)d.style.setProperty('--sc',SUB.color);
   /* ★[접기 2026-08-29] 긴 설명에만 [더보기]를 단다 — 짧은 설명에 단추가 붙으면 그게 더 어수선하다 */
   d.innerHTML=(feat?'<span class="badge">추천</span>':'')+'<div class="ci" style="color:'+cc+';background:color-mix(in srgb,'+cc+' 15%,transparent)">'+a[3]+'</div><h4>'+esc(a[2])+'</h4><p>'+esc(a[5]||a[1])+'</p>'+((a[5]||'').length>90?'<button class="more" onclick="moreT(event,this)">… 더보기</button>':'')+'<span class="go">→</span>';
   d.onclick=function(){openM(a);};
   if(editMode){var hd=(HIDDEN.indexOf(a[1])>=0);if(hd)d.style.opacity='0.45';d.style.position='relative';var vb=document.createElement('button');vb.className='fileopen';vb.style.cssText='position:absolute;top:6px;right:6px;padding:2px 8px;font-size:12px;z-index:2';vb.textContent=hd?'↩️ 복원':'🙈 숨기기';vb.onclick=function(e){e.stopPropagation();cardVis(a[1],!hd);};d.appendChild(vb);}
   if(insub)_lastSub=d;
   grid.appendChild(d);
  });
  /* ★소그룹 목록(SUBGROUPS)에 적혀 있는데 ★그 카드가 다른 섹션으로 옮겨 간 경우 —
     ★조용히 한 장이 빠진다. 안 터지니 눈에 띄지도 않는다(2026-08-29 · 리뷰어1 발견).
     ★목사님은 «새생명축제»를 준비하실 때 ★이 묶음을 보시므로, 없애지 말고 ★여기서 바로 열어 드린다.
     ★카드로 만들지 않고 ★한 줄 안내로 둔다 — 카드로 두면 같은 기능이 두 자리에 있게 되고
       카드 장수·검색 결과가 ★두 번 세어진다. ★검색 중에는 내지 않는다(자료 섹션 카드가 이미 걸린다). */
  if(SUB&&!q){
   SUB.cmds.forEach(function(c){
    if(items.some(function(a){return a[1]===c;}))return;          // 이 섹션에 그대로 있으면 할 일 없음
    if(!editMode&&HIDDEN.indexOf(c)>=0)return;                    // 숨긴 카드는 안내도 하지 않는다
    var t=null;for(var i=0;i<A.length;i++){if(A[i][1]===c){t=A[i];break;}}
    if(!t)return;                                                 // ★정말 없는 카드면 조용히 넘긴다
    var x=document.createElement('div');
    x.style.cssText='grid-column:1/-1;display:flex;align-items:center;gap:8px;cursor:pointer;'
      +'padding:11px 14px;border:1px dashed '+SUB.color+';border-radius:12px;'
      +'background:color-mix(in srgb,'+SUB.color+' 7%,transparent);font-size:14.5px';
    x.innerHTML='<span>'+t[3]+'</span><span><b>'+esc(t[2])+'</b> — 「'+esc(t[0])
      +'」 섹션에 있습니다 · 눌러서 바로 여십니다</span><span style="margin-left:auto">→</span>';
    x.onclick=function(){openM(t);};
    if(_lastSub&&_lastSub.nextSibling)grid.insertBefore(x,_lastSub.nextSibling);
    else grid.appendChild(x);
   });
  }
  app.appendChild(grid);
 });
 /* ★찾은 개수를 ★검색창 바로 아래(=결과 맨 위)에 적는다.
    ★0개면 ★«찾은 것이 없습니다»를 ★반드시 말한다 — ★조용한 0 은 «안 됐다»로 읽힌다. */
 _searchFold(!!q);
 if(q){
  var cnt=document.createElement('div');
  cnt.id='srchcnt';
  cnt.style.cssText='padding:10px 4px 2px;font-size:15px;color:var(--ink-2,#555)';
  /* ★문구는 master 확정안 그대로 — ★«뭔가 일어났다»는 유일한 신호라 ★타이핑 즉시 뜬다.
     ★0개는 ★조용히 넘기지 않는다(조용한 0 은 «고장»으로 읽힌다). */
  cnt.textContent=(_found?('🔍 '+_found+'개 찾았습니다'):'🔍 찾은 것이 없습니다 — 다른 낱말로 해 보세요');
  cnt.style.fontWeight='700';
  app.insertBefore(cnt,app.firstChild);
 }
}
buildNav();render('');
function _setTx(id,v){var e=document.getElementById(id);if(e)e.textContent=v;}
function _fmt(n){try{return (Number(n)||0).toLocaleString('ko-KR');}catch(e){return n;}}
function briefBday(){runQuick('birthday',{days:'0'},'🌅 오늘 생일·기념일 축하');}
function briefCare(){runQuick('care',{},'🧭 돌봄 필요 성도');}
function goBackup(){runQuick('backup',{},'💾 자료 백업');}
function goBackupSet(){
 for(var i=0;i<A.length;i++){ if(A[i][1]==='set-backup'){ openM(A[i]); return; } }
 runQuick('set-backup',{},'📦 USB 자동저장 설정');
}
function briefNew(){runQuick('newcomer',{},'🌱 새가족 정착 현황');}
function brow(ic,cls,title,sub,badge,bcls,fn){
 return '<div class="brow" onclick="'+fn+'()"><div class="ic '+cls+'">'+ic+'</div><div class="tx"><b>'+esc(title)+'</b><s>'+esc(sub)+'</s></div><span class="bdg '+bcls+'">'+esc(badge)+'</span><span class="go2">→</span></div>';
}
function setupBanner(){
 if(document.getElementById('setupbanner'))return;
 var d=document.createElement('div'); d.id='setupbanner';
 d.style.cssText='position:fixed;left:0;right:0;bottom:0;z-index:99998;background:#0f7b6c;color:#fff;padding:13px 18px;font-size:15px;box-shadow:0 -3px 12px rgba(0,0,0,.2);display:flex;align-items:center;gap:12px;flex-wrap:wrap';
 var t=document.createElement('span');
 t.innerHTML='<b>처음 오셨군요.</b> 우리 교회 이름만 넣으시면 준비가 끝납니다 — 주보·증명서에 자동으로 들어갑니다.';
 d.appendChild(t);
 var go=document.createElement('button');
 go.textContent='교회 이름 넣기';
 go.style.cssText='margin-left:auto;background:#fff;color:#0f7b6c;border:0;border-radius:8px;padding:9px 18px;font-weight:700;font-size:15px;cursor:pointer';
 go.onclick=function(){ for(var i=0;i<A.length;i++){ if(A[i][1]==='setup'){ openM(A[i]); return; } } };
 d.appendChild(go);
 var later=document.createElement('button');
 later.textContent='나중에';
 later.style.cssText='background:transparent;color:#fff;border:1px solid rgba(255,255,255,.6);border-radius:8px;padding:9px 14px;font-size:14px;cursor:pointer';
 later.onclick=function(){d.parentNode.removeChild(d);};
 d.appendChild(later);
 document.body.appendChild(d);
}
/* ★[2026-08-29] 숫자를 ★못 불러온 것과 ★«정말 0»을 다른 모양으로 말한다.
   ★종전 문제 둘: ①빈 catch 라 실패가 조용했고(«—»가 영구히 남는다)
     ②401 본문이 ★유효 JSON 이라 r.json() 이 성공해 ★«0명»으로 보였다 —
     ★로그인이 풀린 폰이 «교인 0명»이라고 자신 있게 말했다. ★침묵보다 나쁘다. */
var _STAT_NUMS=['st_mem','st_visit','st_off','st_bday'];
/* ★숫자 자리는 ★«—» 그대로 둔다 (master 16:5x). ★0 으로도 다른 기호로도 바꾸지 않는다 —
   ★못 불러온 것을 숫자처럼 보이게 하는 순간 그것이 거짓이 된다. «—» 는 원래 «아직 모른다»의 자리다.
   ★말은 ★그 아래 작은 글씨(.sub)에 넣는다(master 지정 자리).
   ★단 그 자리는 ★폰에서 숨는다 — 900px 이하에서 `.stat .sub{display:none}` (실측 2026-08-29).
   ⇒ ★거기 넣되, ★실제로 안 보이면 그때만 통계줄 아래 전폭 한 줄을 낸다.
   ★폭(900)을 코드에 다시 적지 않고 ★«지금 보이는가»로 판단한다 — CSS 가 바뀌어도 이 판단은 안 낡는다. */
function _statsSay(msg,retry){
 for(var i=0;i<_STAT_NUMS.length;i++)_setTx(_STAT_NUMS[i],'—');
 var sb=document.getElementById('sb_mem');
 if(sb){
  sb.textContent=msg; sb.style.cursor=retry?'pointer':''; sb.title=retry?'눌러서 다시 불러오기':'';
  sb.onclick=retry?function(){loadStats();}:null;
 }
 var box=document.getElementById('stats_msg');
 if(sb&&sb.getBoundingClientRect().height>0){     /* ★작은 글씨가 보이는 화면(컴퓨터) — 거기서 끝낸다 */
  if(box&&box.parentNode)box.parentNode.removeChild(box);
  return;
 }
 if(!box){
  var st=document.querySelector('.stats'); if(!st)return;
  box=document.createElement('div'); box.id='stats_msg';
  st.parentNode.insertBefore(box,st.nextSibling);
 }
 box.style.cssText='margin:-22px 0 26px;padding:11px 14px;border-radius:12px;font-size:14.5px;'
   +'line-height:1.5;border:1px solid var(--line);background:var(--surface);color:var(--muted);'
   +'display:flex;align-items:center;gap:8px'+(retry?';cursor:pointer':'');
 box.textContent=(retry?'⚠ ':'⏳ ')+msg;
 box.title=retry?'눌러서 다시 불러오기':'';
 box.onclick=retry?function(){loadStats();}:null;
}
function _statsQuiet(){    /* 불러왔으니 그 줄과 «눌러서 다시»를 함께 거둔다 */
 var box=document.getElementById('stats_msg');
 if(box&&box.parentNode)box.parentNode.removeChild(box);
 var sb=document.getElementById('sb_mem');
 if(sb){sb.style.cursor='';sb.onclick=null;sb.title='';}
}
function loadStats(){
 _statsSay('불러오는 중…',false);   /* ★/stats 는 5~8초 걸린다 — 조용하면 «멈췄다»로 보인다 */
 fetch('/stats').then(function(r){
  /* ★401 을 «0명»으로 접지 않는다 — 본문이 유효 JSON 이라 여기서 막지 않으면 그대로 숫자가 된다 */
  if(!r.ok){var er=new Error('http '+r.status);er.code=r.status;throw er;}
  return r.json();
 }).then(function(s){
  /* ★빈 응답({})도 실패다 — church.py 가 못 답하면 «{}» 를 준다. 그걸 0 으로 읽으면 또 거짓말이 된다 */
  if(!s||typeof s.교인==='undefined'){var er2=new Error('empty');er2.code=0;throw er2;}
  _statsQuiet();
  if(s['첫설정필요'])setupBanner();
  _setTx('st_mem',_fmt(s.교인)+'명');
  /* ★«0명»일 때 그것이 ★진짜 0 임을 말한다 — 실패와 모양이 달라야 한다 */
  _setTx('sb_mem',(Number(s.교인)>0?'명부에서 집계':'아직 등록된 교인이 없습니다'));
  _setTx('st_visit',_fmt(s.이번주심방)+'회');
  _setTx('sb_visit',(s.돌봄필요?('돌봄 필요 '+s.돌봄필요+'명'):'이번 주 심방 기록'));
  _setTx('st_off',_fmt(s.이번달헌금)+'원');
  _setTx('sb_off',(s.연월||'')+' 수입 합계');
  _setTx('st_bday',(s.생일수||0)+'명');
  if(s.생일&&s.생일.length){_setTx('sb_bday',s.생일.map(function(b){return b.이름+(b.d===0?'(오늘)':'(D-'+b.d+')');}).join(', '));}
  else{_setTx('sb_bday','7일 내 없음');}
  // 오늘의 목회 브리핑
  _setTx('brief_date',(s.오늘||'')+(s.요일?('  ('+s.요일+')'):''));
  var H='';
  var tb=s.오늘생일||[];
  if(tb.length){H+=brow('🎂','bd','오늘 생일 '+tb.length+'명',tb.join(', ')+' — 눌러서 축하 카톡 만들기','오늘','bd','briefBday');}
  var up=(s.생일||[]).filter(function(b){return b.d>0;});
  if(up.length){H+=brow('📅','vs','다가오는 생일·기념일 '+up.length+'명',up.map(function(b){return b.이름+'(D-'+b.d+')';}).join(', '),'7일 내','vs','briefBday');}
  if(s.돌봄필요){H+=brow('🧭','cr','돌봄 필요 '+s.돌봄필요+'명',((s.돌봄명단||[]).join(', ')||'오래 심방 못한 성도')+' — 심방 챙기기','심방','cr','briefCare');}
  /* ★설명이 세는 자를 그대로 말해야 한다 — 종전 «최근 90일 등록»은 ★틀린 자를 설명하고 있었다.
     이제 «새가족 등록 카드로 넣으신 분»만 센다(church.py _is_newfamily). 문구도 그렇게 고친다. */
  if(s.새가족){H+=brow('🌱','nw','정착 중 새가족 '+s.새가족+'명','새가족으로 등록하신 분 — 정착까지 함께','새가족','nw','briefNew');}
  var bp=document.getElementById('brief'),br=document.getElementById('brief_rows');
  if(br&&bp){br.innerHTML=H||'<div class="brief-empty">오늘은 특별히 챙길 목양 알림이 없습니다. 평안한 하루 되세요 🙏</div>';bp.style.display='';}
 }).catch(function(e){
  /* ★실패를 삼키지 않는다. ★로그인 풀림과 그 밖의 실패를 ★갈라 말한다 —
     둘은 목사님이 하실 일이 다르다(다시 들어오기 vs 다시 누르기). */
  var c=(e&&e.code);
  if(c===401||c===403)_statsSay('로그인이 풀렸습니다 — 「📱 폰 접속」에서 다시 들어와 주세요',true);
  else _statsSay('숫자를 못 불러왔습니다 · 눌러서 다시 불러오기',true);
 });
}
function runQuick(cmd,args,title){
 cur=['',cmd,title||cmd,'▶',[]];
 _setTx('mt',title||cmd);_setTx('ms','');document.getElementById('mf').innerHTML='';
 var o=document.getElementById('mo');o.className='out on';o.textContent='실행 중...';
 document.getElementById('modal').classList.add('on');
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:JSON.stringify({cmd:cmd,args:args})})
  .then(function(r){return r.text();}).then(function(t){o.className='out on ok';renderOut(o,t);loadStats();})
  .catch(function(e){o.className='out on';o.textContent=isNet(e)?NETERR:'오류: '+e;});
}
loadStats();
function updChime(){
 try{
  var C=window.AudioContext||window.webkitAudioContext; if(!C)return;
  var a=new C(); var o=a.createOscillator(); var g=a.createGain();
  o.connect(g); g.connect(a.destination); o.type='sine';
  o.frequency.value=880; g.gain.value=0.04; o.start();
  setTimeout(function(){try{o.frequency.value=1175;}catch(e){}},170);
  setTimeout(function(){try{o.stop();a.close();}catch(e){}},400);
 }catch(e){}
}
function updBanner(u){
 if(document.getElementById('updbanner'))return;
 var d=document.createElement('div'); d.id='updbanner';
 d.style.cssText='position:fixed;left:0;right:0;top:0;z-index:99999;background:#1f6feb;color:#fff;padding:13px 18px;font-size:16px;font-weight:700;box-shadow:0 3px 12px rgba(0,0,0,.25);display:flex;align-items:center;gap:12px;flex-wrap:wrap';
 var t=document.createElement('span');
 t.textContent='🔔 새 업데이트가 나왔습니다'+(u&&u.version?(' (v'+String(u.version).split(' ')[0]+')'):'');
 d.appendChild(t);
 if(u&&u.notes){
  var n=document.createElement('span');
  n.style.cssText='font-weight:400;font-size:14px;opacity:.95';
  n.textContent=String(u.notes).slice(0,90);
  d.appendChild(n);
 }
 var s=document.createElement('span');
 s.style.cssText='font-weight:400;font-size:13px;opacity:.9';
 s.textContent='교인·심방·재정 자료는 그대로 보존됩니다';
 d.appendChild(s);
 var go=document.createElement('button');
 go.textContent='지금 업데이트';
 go.style.cssText='margin-left:auto;background:#fff;color:#1f6feb;border:0;border-radius:8px;padding:9px 18px;font-weight:700;font-size:15px;cursor:pointer';
 go.onclick=function(){updateApp();};
 d.appendChild(go);
 var later=document.createElement('button');
 later.textContent='나중에';
 later.style.cssText='background:transparent;color:#fff;border:1px solid rgba(255,255,255,.6);border-radius:8px;padding:9px 14px;font-size:14px;cursor:pointer';
 later.onclick=function(){d.parentNode.removeChild(d);document.body.style.paddingTop='';};
 d.appendChild(later);
 document.body.appendChild(d);
 document.body.style.paddingTop='62px';
}
function checkUpdate(){
 fetch('/updatecheck').then(function(r){return r.json();}).then(function(u){
  var b=document.querySelector('.upd');if(!b)return;
  if(u&&u['new']){
   b.classList.add('has-new');
   if(!b.querySelector('.updbadge')){var s=document.createElement('span');s.className='updbadge';s.textContent='NEW';b.appendChild(s);}
   b.title='새 업데이트'+(u.version?(' '+u.version.split(' ')[0]):'')+' 있음 — 눌러서 업데이트하세요'+(u.notes?(String.fromCharCode(10)+u.notes):'');
   updBanner(u); updChime();
  }
 }).catch(function(){});
}
checkUpdate();
function toggleNotif(e){if(e)e.stopPropagation();var p=document.getElementById('notifpanel');if(!p)return;if(!p.classList.contains('on'))loadNotif();p.classList.toggle('on');}
function notifGo(fn){var p=document.getElementById('notifpanel');if(p)p.classList.remove('on');if(fn==='cal'){openCal();return;}if(typeof window[fn]==='function')window[fn]();}
function loadNotif(){
 Promise.all([
  fetch('/stats').then(function(r){return r.json();}).catch(function(){return {};}),
  fetch('/events').then(function(r){return r.json();}).catch(function(){return [];}),
  fetch('/updatecheck').then(function(r){return r.json();}).catch(function(){return {};})
 ]).then(function(res){
  var s=res[0]||{},evs=res[1]||[],up=res[2]||{},items=[];
  var td=new Date(),t0=td.getFullYear()+'-'+('0'+(td.getMonth()+1)).slice(-2)+'-'+('0'+td.getDate()).slice(-2);
  var t7=new Date(td.getTime()+7*86400000);
  if(s.오늘생일&&s.오늘생일.length)items.push(['🎂','bd','오늘 생일 '+s.오늘생일.length+'명',s.오늘생일.join(', ')+' — 축하 카톡','briefBday']);
  var upb=(s.생일||[]).filter(function(b){return b.d>0;});
  if(upb.length)items.push(['📅','vs','다가오는 생일·기념일 '+upb.length+'명',upb.map(function(b){return b.이름+'(D-'+b.d+')';}).join(', '),'briefBday']);
  if(s.돌봄필요)items.push(['🧭','cr','돌봄 필요 '+s.돌봄필요+'명',(s.돌봄명단||[]).join(', ')||'오래 심방 못한 성도','briefCare']);
  evs.filter(function(e){var d=String(e['날짜']);return d>=t0&&new Date(d)<=t7;}).sort(function(a,b){return String(a['날짜'])<String(b['날짜'])?-1:1;}).forEach(function(e){
   items.push([e['중요']?'⭐':'🗓️',e['중요']?'bd':'vs',(e['날짜']===t0?'오늘 · ':(String(e['날짜']).slice(5)+' · '))+e['제목'],'일정 — 캘린더 보기','cal']);
  });
  if(up&&up['new'])items.push(['🔄','nw','새 업데이트 있음',(up.notes||'눌러서 업데이트'),'updateApp']);
  var bkd=s['백업경과일'];
  if(bkd===null||typeof bkd==='undefined'){
   items.push(['💾','cr','자료 백업을 한 번도 안 하셨습니다','컴퓨터가 고장 나면 교적이 사라집니다 — 지금 한 번만 눌러 두세요','goBackup']);
  }else if(bkd>=30){
   items.push(['💾','cr','백업한 지 '+bkd+'일 지났습니다','1분이면 끝납니다 — 눌러서 지금 백업','goBackup']);
  }
  if(s['백업폴더없음']){
   items.push(['⚠️','cr','USB 자동저장 폴더를 찾을 수 없습니다','USB가 빠졌거나 폴더가 없습니다 — 지금은 이중 보관이 안 되고 있습니다','goBackupSet']);
  }
  if(s['백업폴더설정']===false){
   items.push(['🧷','vs','USB 자동저장이 설정되지 않았습니다','한 번 지정해 두시면 저장할 때마다 자동으로 이중 보관됩니다','goBackupSet']);
  }
  var box=document.getElementById('notif_list'),dot=document.getElementById('notif_dot');if(!box)return;
  if(items.length){var Q=String.fromCharCode(39);box.innerHTML=items.map(function(it){return '<div class="notif-item" onclick="notifGo('+Q+it[4]+Q+')"><div class="ni-ic '+it[1]+'">'+it[0]+'</div><div class="ni-tx"><b>'+esc(it[2])+'</b><s>'+esc(it[3])+'</s></div></div>';}).join('');if(dot)dot.style.display='';}
  else{box.innerHTML='<div class="notif-empty">오늘은 새 알림이 없습니다. 평안한 하루 되세요.</div>';if(dot)dot.style.display='none';}
 }).catch(function(){});
}
loadNotif();
document.addEventListener('click',function(){var p=document.getElementById('notifpanel');if(p)p.classList.remove('on');});
var _cb=document.getElementById('card_bday');if(_cb)_cb.onclick=function(){runQuick('birthday',{days:'0'},'🌅 오늘 생일 축하');};
var sb=document.getElementById('search');if(sb)sb.oninput=function(){render(sb.value);_toggleHome();};
function goHome(){var s=document.getElementById('search');if(s)s.value='';render('');setNav(0);closeM();window.scrollTo(0,0);_toggleHome();}
function _toggleHome(){var h=document.getElementById('homebtn');if(!h)return;var s=document.getElementById('search');h.className=((window.pageYOffset>240)||(s&&s.value.trim()!==''))?'home on':'home';}
window.addEventListener('scroll',_toggleHome);
var cur=null;
var DRAFT={};      // {명령: {칸이름: 쓰시던 값}} — 화면 안에서만 산다(저장 파일 아님)
// ★폰의 뒤로가기 — 눌러도 프로그램에서 나가지 않고 열린 창만 닫는다.
//   폰에서는 뒤로가기가 곧 취소 단추라, 그대로 두면 심방 중에 쓰시던 내용이 통째로 날아간다.
window.addEventListener('popstate',function(){
 var g=document.getElementById('gsheet');
 if(g&&g.classList.contains('on')){closeGroups();return;}
 var ids=['modal','calmodal','finmodal','whymodal','welcome'];
 for(var i=0;i<ids.length;i++){var m=document.getElementById(ids[i]);
  if(m&&m.classList.contains('on')){m.classList.remove('on');return;}}
});
function _pushStep(){try{history.pushState({step:1},'');}catch(e){}}
/* ★자료를 바꾸는(되돌리기 어려운) 카드 — 여기 있는 카드는 설명을 ★접지 않고 펴서 보여 준다.
   ★새 카드가 자료를 바꾸게 되면 ★여기에 이름을 더해라. 빠뜨리면 그 카드만 조용히 접힌다. */
var DESC_ALWAYS_OPEN=['phoenix','member-restore','member-import','finance-import','update','member-transfer','newfamily-graduate','phone-setup','nlm-add'];
/* ★[2026-08-29 · worker 요청] phone-setup·nlm-add 추가 — 이 둘은 ★설명을 안 읽으시면 곤란해지는 카드다:
   phone-setup 은 «공용 와이파이에서 쓰지 마세요»가, nlm-add 는 «이 카드만 교회 밖으로 나갑니다»가
   설명문 안쪽에 있다. ★접혀 있으면 그 경고가 3줄 밖으로 밀린다. */
function mkDesc(mf,a){
 var d=(a[5]||'').trim(); if(!d)return;
 var box=document.createElement('div'); box.className='note'; box.style.marginBottom='12px';
 var html=_esc(d).split('▸').join('<br>▸');
 var always=DESC_ALWAYS_OPEN.indexOf(a[1])>=0;
 if(always||d.length<=150){
   box.innerHTML=(always?'<b>이 카드가 하는 일</b><br>':'')+html;
   mf.appendChild(box); return;
 }
 /* ★긴 설명은 첫 마디만 보이고 [더보기] — 다 펴 놓으면 입력칸이 화면 밖으로 밀린다 */
 var head=_esc(d.split('▸')[0].trim());
 var sp=document.createElement('span'); sp.innerHTML=head+' ';
 var btn=document.createElement('button');
 btn.type='button'; btn.className='b cancel'; btn.textContent='더보기';
 btn.style.cssText='padding:2px 10px;min-width:0;font-size:13px;margin-left:4px';
 btn.onclick=function(){ box.innerHTML=html; };
 box.appendChild(sp); box.appendChild(btn); mf.appendChild(box);
}
function openM(a){if(a[1]==='why'){openWhy();return;}if(a[1]==='cal-open'){openCal();return;}if(a[1]==='finance-chart'){openFinance();return;}cur=a;document.getElementById('mt').textContent=a[3]+' '+a[2];
 document.getElementById('ms').textContent=a[1];
 var mf=document.getElementById('mf');mf.innerHTML='';
 /* ★카드 설명을 ★실행 창에도 보인다.
    ★왜: 종전에는 설명이 ★격자에만 있었다. 카드를 누르면 사라져서, «이 카드는 자료를 바꾸지 않습니다»
      같은 ★안전 고지가 ★실행 단추를 누르시기 직전에 없어졌다. 읽어야 할 자리에서 안 보이는 안내는
      ★없는 것과 같다.
    ★자료를 바꾸는 카드는 ★접지 않는다 — 접어 두면 안 읽히고, 그 카드들이 하필 되돌리기 어려운 것들이다. */
 mkDesc(mf,a);
 a[4].forEach(function(f,fi){var n=f[0],label=f[1],ph=f[2],req=f[3];
  var l=document.createElement('label');l.textContent=label+(req?' *':'');mf.appendChild(l);
  var big=(n==='lyrics'||n==='note'||n==='body'||n==='notice'||n==='week'||n==='goal'||n==='purpose'||n==='verses');
  var inp=document.createElement(big?'textarea':'input');inp.className='f';inp.id='fld_'+n;inp.placeholder=ph;
  /* ★폰 자판에 «실행하는 키»를 띄운다 (주인님 발견 2026-08-29 · master 지시)
     ★왜: 폰 자판에는 PC 의 엔터가 없다. 카드 입력칸에 form 도 keydown 도 없어서
       ★타이핑한 뒤 «무엇을 눌러야 검색되는지» 알 수 없었다. [실행] 버튼을 찾아 누르는 길뿐이었다.
       PC 는 엔터가 있어 아무도 몰랐다 — ★폰에서 실제로 쳐 봐야 나오는 결함이었다.
     ★키만 더한다 — [실행] 버튼은 ★그대로 둔다(대체가 아니라 추가).
     ★여러 칸 카드: 마지막 칸이 아니면 ★다음 칸으로 옮긴다(엉뚱하게 실행되는 것이 더 나쁘다).
     ★글상자(textarea)는 ★건드리지 않는다 — 거기서 엔터는 ★줄바꿈이어야 한다. */
  if(!big){
   /* ★«마지막»은 ★전체 칸이 아니라 ★엔터가 듣는 칸(글상자 제외) 기준이다.
      ★안 그러면 뒤에 글상자만 남은 칸에 «다음»이 뜨는데 ★실제로는 실행된다 —
      ★자판 글자와 실제 동작이 어긋나는 것이 ★이 수리가 없애려던 바로 그 종류다. */
   var isBig=function(nm){return (nm==='lyrics'||nm==='note'||nm==='body'||nm==='notice'||nm==='week'||nm==='goal'||nm==='purpose'||nm==='verses');};
   var lastIdx=-1;
   for(var li=0;li<a[4].length;li++){ if(!isBig(a[4][li][0])) lastIdx=li; }
   var wantSearch=(label.indexOf('검색')>=0||label.indexOf('찾')>=0||n==='query'||n==='ref');
   inp.setAttribute('enterkeyhint', fi<lastIdx ? 'next' : (wantSearch?'search':'go'));
   inp.onkeydown=function(ev){
    if(ev.key!=='Enter'&&ev.keyCode!==13)return;
    ev.preventDefault();
    var boxes=mf.querySelectorAll('.f');
    for(var bi=0;bi<boxes.length;bi++){
     if(boxes[bi]===inp){
      for(var nx=bi+1;nx<boxes.length;nx++){
       if(boxes[nx].tagName!=='TEXTAREA'){boxes[nx].focus();return;}
      }
      break;
     }
    }
    document.getElementById('mgo').click();   /* ★[실행]과 ★같은 경로 — 새 제출 경로를 만들지 않는다 */
   };
  }
  // ★쓰시던 내용을 기억한다 — 폰에서 뒤로가기를 누르거나 실수로 닫아도 날아가면 안 된다.
  //   (남의 집 문 앞에서 다시 타이핑하시게 만들지 않는다. 실행에 성공하면 지운다.)
  if(DRAFT[a[1]]&&DRAFT[a[1]][n])inp.value=DRAFT[a[1]][n];
  inp.oninput=function(){if(!DRAFT[a[1]])DRAFT[a[1]]={};DRAFT[a[1]][n]=inp.value;};
  mf.appendChild(inp);
 });
 var o=document.getElementById('mo');o.className='out';o.textContent='';
 document.getElementById('modal').classList.add('on');_pushStep();
}
function closeM(){document.getElementById('modal').classList.remove('on');}
var calY,calM;
function openCal(){var d=new Date();calY=d.getFullYear();calM=d.getMonth()+1;renderCal();document.getElementById('calmodal').classList.add('on');}
function closeCal(){document.getElementById('calmodal').classList.remove('on');}
var finYear=new Date().getFullYear();
function openFinance(){finYear=new Date().getFullYear();loadFin();document.getElementById('finmodal').classList.add('on');}
function closeFin(){document.getElementById('finmodal').classList.remove('on');}
function openWhy(){document.getElementById('whymodal').classList.add('on');}
function closeWhy(){document.getElementById('whymodal').classList.remove('on');}
/* ── 📱 폰으로 보기 ───────────────────────────────────────────────────────
   ★이 안에는 역슬래시를 쓰지 않는다. 이 화면 전체가 파이썬 삼중따옴표 문자열 안이라
     역슬래시가 파이썬에게 ★먼저 먹혀 버린다(줄바꿈은 String.fromCharCode(10) 으로). */
var _NEWPW='';
function _qrDrop(){
 /* ★화면에서 치우는 것과 ★열쇠를 죽이는 것은 다른 일이다 — 둘 다 한다.
    서버에 «거둬 달라»고 알려야 실제로 죽는다(권위는 화면이 아니라 서버에 있다). */
 try{fetch('/qrdrop',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:'{}'});}catch(e){}
}
function closeQR(){
 /* ★닫을 때 ★내용을 지우고 ★열쇠도 죽인다 (2026-08-27 · reviewer R2-N1 · master 재정).
    종전에는 감추기만 해서 ①QR 그림(SVG)·주소가 화면 구조에 남았고 ②옛 열쇠가 3분을 마저 살았다.
    감추는 것과 지우는 것은 다르고, 지우는 것과 죽이는 것도 다르다 — 셋 다 한다. */
 document.getElementById('qrmodal').classList.remove('on');
 if(_qrTimer){clearInterval(_qrTimer);_qrTimer=null;}
 var b=document.getElementById('qr_body'); if(b)b.innerHTML='';
 _NEWPW=''; _qrDrop();
}
function _esc(s){var d=document.createElement('div');d.textContent=(s==null?'':String(s));return d.innerHTML;}
function openPhone(){
 var b=document.getElementById('qr_body');
 document.getElementById('qrmodal').classList.add('on');
 b.textContent='QR 을 만드는 중…';
 fetch('/qrinfo',{headers:{'X-Church-App':'1'}})
  .then(function(r){if(!r.ok)throw new Error('불가');return r.json();})
  .then(function(d){renderQR(d);})
  .catch(function(e){b.textContent=isNet(e)?NETERR:'폰 접속 정보를 가져오지 못했습니다. ('+e+')';});
}
function renderQR(d){
 var b=document.getElementById('qr_body'); b.innerHTML='';
 if(_NEWPW){
   var pw=document.createElement('div'); pw.className='qrpw';
   pw.innerHTML='🔑 폰 접속 비밀번호를 새로 만들어 드렸습니다 — <b>'+_esc(_NEWPW)+'</b><br>'
     +'QR 로 들어가시면 <b>넣지 않으셔도 됩니다.</b> QR 이 안 될 때만 쓰이니 한 번 적어 두세요.'
     +'<br>(나중에 「📱 폰 접속 설정」 카드에서 원하시는 것으로 바꾸실 수 있습니다)';
   b.appendChild(pw);
 }
 if(!d.on||!d.haspw){
   var n=document.createElement('div'); n.className='note';
   n.innerHTML='폰 접속이 아직 꺼져 있습니다.<br>아래 단추를 누르시면 <b>지금 이 자리에서</b> 켜 드리고 바로 QR 이 나옵니다.'
     +'<br>(프로그램을 껐다 켜지 않으셔도 됩니다)';
   b.appendChild(n);
   var btn=document.createElement('button'); btn.className='b go'; btn.style.marginTop='13px';
   btn.textContent='📱 지금 켜기'; btn.onclick=function(){turnPhoneOn(btn);};
   b.appendChild(btn); return;
 }
 if(!d.ways||!d.ways.length){
   /* ★이 자리를 문장이 설명해야 한다 (reviewer R3 §5 등재).
      서버는 새 QR 을 ★만들기 전에 옛 열쇠를 지운다. 그래서 주소를 못 찾는 상황에서
      「🔄 새 QR 만들기」를 누르시면 ★없애기만 하고 새것은 안 나온다.
      안전한 방향(fail-closed)이지만, 말해 주지 않으면 «눌렀는데 아무 일도 안 난다»가 된다. */
   var w=document.createElement('div'); w.className='note';
   w.innerHTML='폰에서 들어오실 주소를 아직 찾지 못해 <b>새 QR 을 만들지 못했습니다.</b><br>'
     +_esc(d.why||'')
     +'<br><br>※ 아까 띄워 두셨던 QR 이 있었다면 <b>그것도 함께 거두었습니다</b> — 다시 만들어 주세요.';
   b.appendChild(w); return;
 }
 var wrap=document.createElement('div'); wrap.className='qrwrap';
 d.ways.forEach(function(w){
   var c=document.createElement('div'); c.className='qrcard';
   /* ★라벨에 «무엇이 필요한지»를 반드시 적는다 — 잘못 고르시면 안 열리고 원인을 모르신다. */
   c.innerHTML='<div class="qrt">'+_esc(w.title)+'</div>'
     +'<div class="qrn">'+_esc(w.need)+'</div>'
     +'<div class="qrimg">'+w.svg+'</div>'
     +'<div class="qra">'+_esc(w.url)+'</div>'
     +'<div class="qrx">'+_esc(w.extra)+'</div>';
   wrap.appendChild(c);
 });
 b.appendChild(wrap);
 var t=document.createElement('div'); t.className='note'; t.style.marginTop='13px';
 t.innerHTML='① 폰 카메라를 QR 에 비추시고, 뜨는 알림을 누르세요 — <b>비밀번호 없이 바로 열립니다.</b><br>'
  +'② 열리면 <b>홈 화면에 추가</b> 안내가 나옵니다. 그대로 하시면 다음부터는 아이콘 한 번입니다.<br>'
  +'③ QR 이 잘 안 읽히면, 위에 적힌 주소를 폰 인터넷 창에 직접 치셔도 됩니다(그때는 비밀번호를 넣으십니다).';
 b.appendChild(t);
 /* ★위험을 «열쇠 수명»이 아니라 «그 열쇠가 만드는 권한»으로 적는다 (2026-08-27 · master 재정).
    «3분·1회용»만 적으면 짧고 안전한 것처럼 읽히는데, 그 3분 안에 찍은 기기는 ★30일 동안 열린다.
    무엇이 열리는지 말하고, 판단은 목사님께 남긴다. «안전합니다»로 끝내지 않는다. */
 var wcap=document.createElement('div'); wcap.className='qrwarn';
 wcap.innerHTML='⚠ <b>이 QR 을 3분 안에 찍은 기기는 약 30일 동안 열람할 수 있습니다</b>(쓸 때마다 연장됩니다).<br>'
  +'교인 명부·심방 기록·재정과 <b>만드신 문서 내려받기</b>까지 그 기기에서 열립니다.<br>'
  +'<b>이 화면을 다른 사람이 보지 않게 해 주세요.</b><br>'
  /* ★«찍고 나면 닫기»가 아니다 (R3-N1 · 리뷰어 지적 · master 재정).
     QR 을 찍는 것과 ★폰이 실제로 들어가는 것 사이에는 시간이 있다. 그 사이에 닫으면
     열쇠가 죽어 ★폰에 로그인 화면이 뜬다 — 목사님이 ★화면이 시킨 대로 하셨는데 안 되는 것이다.
     ★등급은 «보안 아님·기능 회귀»가 맞지만, 오너 기준으로는 이것이 더 아프다:
       «안 되는 걸 된다고 해 놓으면 그 순간 신뢰가 무너진다». 그래서 ★기준을 «열린 것을 보신 뒤»로 옮긴다. */
  +'<b>폰에서 화면이 열린 것을 보신 뒤</b> <b>「닫기」</b>를 눌러 주세요 — 그 순간 이 QR 은 <b>못 쓰게 됩니다.</b> '
  +'남이 본 것 같으시면 <b>「🔄 새 QR 만들기」</b>를 누르시면 아까 QR 이 <b>바로 죽습니다.</b><br>'
  +'모르는 기기가 들어와 있는지는 아래 <b>「🖥 지금 들어와 있는 기기」</b>에서 보시고 그 기기만 끊으실 수 있습니다.';
 b.appendChild(wcap);
 var cd=document.createElement('div'); cd.className='qrcount'; cd.id='qr_count'; b.appendChild(cd);
 _qrArm();
}
/* ── C. 자리를 비우시면 ★스스로 가린다 ────────────────────────────────────
   ★열어 둔 채 나가시면 화면에 QR 이 계속 떠 있다. 열쇠 수명과 ★같게(3분) 가린다.
     «가린다»이지 «닫는다»가 아니다 — 다시 보기를 누르시면 ★새 열쇠로 다시 그린다
     (같은 열쇠를 다시 보여 주면 3분 제한이 뜻을 잃는다). */
/* ★열쇠 수명은 ★서버가 정한다 — 화면은 그 값을 ★받아 쓴다 (2026-08-27 · 문장검증 게이트가 잡았다).
   종전에는 화면이 180 을 ★따로 적어 두었다. 지금은 서버 QR_TTL 도 180 이라 «맞아» 보였지만,
   ★두 벌이라 언젠가 갈라진다 — 서버 수명을 바꾸는 순간 화면이 ★거짓말을 시작한다.
   ⇒ 문장을 고치는 대신 ★진실의 출처를 하나로 만든다. 이게 이 게이트가 있는 이유다. */
var QRTTL=__QRTTL__;
var _qrTimer=null, _qrLeft=0;
function _qrArm(){
 if(_qrTimer){clearInterval(_qrTimer);_qrTimer=null;}
 _qrLeft=QRTTL;
 _qrTimer=setInterval(function(){
   _qrLeft--;
   var c=document.getElementById('qr_count');
   /* ★«가려집니다»는 거짓이 됐다 (R3-N2) — 이제 가리는 것이 아니라 ★죽인다.
      «다시 보실 수 있습니다»도 틀렸다: 그 QR 이 다시 보이는 게 아니라 ★새 QR 을 만드는 것이다. */
   if(c)c.textContent='이 QR 은 '+_qrLeft+'초 뒤 못 쓰게 됩니다 (그때 새로 만드실 수 있습니다)';
   if(_qrLeft<=0)_qrVeil();
 },1000);
}
function _qrVeil(){
 if(_qrTimer){clearInterval(_qrTimer);_qrTimer=null;}
 var b=document.getElementById('qr_body'); if(!b)return;
 b.innerHTML=''; _qrDrop();          /* ★가리는 김에 ★열쇠도 죽인다 */
 var n=document.createElement('div'); n.className='note';
 n.innerHTML='🔒 시간이 지나 QR 을 거두었습니다 — <b>이 QR 은 이제 못 씁니다.</b><br>'
   +'아직 안 찍으셨으면 아래 <b>「🔄 새 QR 만들기」</b>를 눌러 주세요 — 새 QR 이 나옵니다.';
 b.appendChild(n);
}
/* ── B. 지금 들어와 있는 기기 ───────────────────────────────────────────── */
function closeDevices(){document.getElementById('devmodal').classList.remove('on');}
function _ago(sec){
 if(sec<60)return '방금';
 if(sec<3600)return Math.floor(sec/60)+'분 전';
 if(sec<86400)return Math.floor(sec/3600)+'시간 전';
 return Math.floor(sec/86400)+'일 전';
}
function openDevices(){
 var b=document.getElementById('dev_body');
 document.getElementById('devmodal').classList.add('on');
 b.textContent='불러오는 중…';
 fetch('/devices',{headers:{'X-Church-App':'1'}})
  .then(function(r){return r.json();})
  .then(function(d){renderDevices(d);})
  .catch(function(e){b.textContent=isNet(e)?NETERR:('기기 목록을 가져오지 못했습니다. ('+e+')');});
}
function renderDevices(d){
 var b=document.getElementById('dev_body'); b.innerHTML='';
 var list=(d&&d.devices)||[];
 if(!list.length){b.innerHTML='<div class="note">들어와 있는 기기가 없습니다.</div>';return;}
 list.forEach(function(x){
   var row=document.createElement('div'); row.className='devrow';
   var mine=x['이것이지금화면'];
   row.innerHTML='<div class="devi"><b>'+_esc(x['기기'])+'</b>'
     +(mine?' <span class="devme">지금 보고 계신 화면</span>':'')
     +'<div class="devs">'+_esc(x['종류'])+' · 마지막 접속 '+_ago(d.now-x['마지막'])
     +' · 처음 들어온 때 '+_ago(d.now-x['처음'])+'</div></div>';
   var btn=document.createElement('button');
   btn.className='b cancel'; btn.style.minWidth='96px';
   if(mine){btn.textContent='—'; btn.disabled=true;}
   else{btn.textContent='끊기'; btn.onclick=function(){dropDevice(x.id,btn);};}
   row.appendChild(btn); b.appendChild(row);
 });
 var n=document.createElement('div'); n.className='note'; n.style.marginTop='12px';
 n.innerHTML='기기 이름은 브라우저가 스스로 밝힌 것이라 ★정확한 신원은 아닙니다 — '
  +'<b>«내 것이 아닌 것»을 알아보시는 용도</b>로 보세요.<br>'
  +'폰을 잃어버리셨다면 「📱 폰 접속 설정」 카드의 <b>모든 기기 로그아웃</b>이 한 번에 전부 끊습니다.';
 b.appendChild(n);
}
function dropDevice(id,btn){
 btn.disabled=true; btn.textContent='끊는 중…';
 fetch('/devicedrop',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},
   body:JSON.stringify({id:id})})
  .then(function(r){return r.json();})
  .then(function(x){ if(x.ok){openDevices();} else {btn.disabled=false;btn.textContent='끊기';} })
  .catch(function(e){btn.disabled=false;btn.textContent='끊기';});
}
function turnPhoneOn(btn){
 btn.disabled=true; btn.textContent='켜는 중…';
 fetch('/phoneon',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:'{}'})
  .then(function(r){return r.json();})
  .then(function(x){
    if(!x.ok){btn.disabled=false; btn.textContent='📱 지금 켜기';
      var e=document.createElement('div'); e.className='note'; e.style.marginTop='11px';
      e.textContent='켜지 못했습니다 — '+(x.error||'사유를 알 수 없습니다.');
      btn.parentNode.appendChild(e); return;}
    _NEWPW=x.pw||''; openPhone();
  })
  .catch(function(e){btn.disabled=false; btn.textContent='📱 지금 켜기';
    var m=document.createElement('div'); m.className='note'; m.style.marginTop='11px';
    m.textContent=isNet(e)?NETERR:('오류: '+e); btn.parentNode.appendChild(m);});
}
/* ── 🏠 홈 화면에 추가 ────────────────────────────────────────────────────
   ★크롬의 자동 «설치» 알림(beforeinstallprompt)은 ★안전한 주소(https·localhost)에서만 뜬다.
     우리 폰 주소는 http 라 ★안 뜨는 것이 정상이다 — 그래서 손 안내를 ★기본으로 띄우고,
     알림이 뜨는 경우에만 단추가 덧붙는다. 「되겠지」로 비워 두지 않는다. */
var _installEvt=null;
window.addEventListener('beforeinstallprompt',function(e){
  e.preventDefault(); _installEvt=e;
  var b=document.getElementById('a2hs_btn'); if(b)b.style.display='';});
function _standalone(){try{return window.matchMedia('(display-mode: standalone)').matches
  ||navigator.standalone===true;}catch(e){return false;}}
function _isIOS(){var u=navigator.userAgent||'';
  return /iPad|iPhone|iPod/.test(u)||(/Macintosh/.test(u)&&navigator.maxTouchPoints>1);}
function showA2HS(){
 if(!REMOTE||_standalone())return;           /* 사무실 컴퓨터에는 띄우지 않는다 */
 try{if(localStorage.getItem('a2hs2'))return;}catch(e){}
 var d=document.getElementById('a2hs'); if(!d)return;
 var s=document.getElementById('a2hs_how'); if(!s)return;
 s.innerHTML=_a2hsHow();
 d.classList.add('on');
}
/* ★브라우저마다 메뉴가 있는 자리가 다르다. 종전에는 아이폰이 아니면 전부 «오른쪽 위 점 세 개»라고
   말했는데, ★삼성 인터넷은 메뉴가 «오른쪽 아래»다 — 목사님이 못 찾으셨다(2026-08-29 실증).
   ★한 줄로 뭉뚱그리면 그 안내는 쓰는 사람의 절반에게 틀린 말이 된다. */
function _browserKind(){var u=navigator.userAgent||'';
 if(_isIOS())return 'ios';
 if(/SamsungBrowser/i.test(u))return 'samsung';   /* ★크롬보다 먼저 본다 — 삼성 UA 에도 Chrome 이 들어 있다 */
 /* ★정규식 안에서 슬래시를 역슬래시로 감싸면 파이썬이 PAGE 문자열을 읽을 때
    «알 수 없는 이스케이프» 경고를 낸다(이 주석 자체도 그랬다 — 게이트가 잡았다).
    지금은 동작하지만 경고를 남기는 코드는 두지 않는다. 같은 판정을 indexOf 로 한다. */
 if(u.indexOf('Chrome/')>=0&&/Android/i.test(u))return 'chrome';
 return 'other';}
function _a2hsHow(){var k=_browserKind();
 if(k==='ios')return '화면 <b>아래 가운데</b>의 공유 단추(네모에 화살표 ↑)를 누르시고 →'
   +' 목록을 조금 내려 <b>홈 화면에 추가</b> 를 누르신 뒤 <b>추가</b> 를 누르세요.';
 if(k==='samsung')return '<b>삼성 인터넷</b>을 쓰고 계십니다. 화면 <b>오른쪽 아래</b>의 <b>더보기(≡)</b> 를 누르시고 →'
   +' <b>현재 페이지 추가</b> → <b>홈 화면</b> 을 고르신 뒤 <b>추가</b> 를 누르세요.'
   +'<br><span style="opacity:.75">※ 크롬과 달리 메뉴가 <b>화면 아래</b>에 있습니다.</span>';
 if(k==='chrome')return '화면 <b>오른쪽 위</b>의 점 세 개(⋮)를 누르시고 →'
   +' <b>홈 화면에 추가</b>(또는 <b>앱 설치</b>) 를 누르세요.';
 /* ★모르는 브라우저에 위치를 지어내지 않는다 — 틀린 위치를 알려 드리는 것이 «모른다»보다 나쁘다 */
 return '쓰고 계신 브라우저는 저희가 확인하지 못했습니다 — 메뉴(<b>⋮</b> 또는 <b>≡</b>)를 열어'
   +' <b>홈 화면에 추가</b> 또는 <b>현재 페이지 추가</b> 를 찾아 주세요.'
   +'<br><span style="opacity:.75">※ 메뉴는 크롬이면 <b>화면 위</b>, 삼성 인터넷이면 <b>화면 아래</b>에 있습니다.</span>';
}
function a2hsInstall(){
 if(!_installEvt){closeA2HS();return;}
 try{_installEvt.prompt();}catch(e){}
 _installEvt=null;
 var b=document.getElementById('a2hs_btn'); if(b)b.style.display='none';
 closeA2HS();
}
function closeA2HS(){document.getElementById('a2hs').classList.remove('on');
 try{localStorage.setItem('a2hs2','1');}catch(e){}}
/* ── ✅ QR 직후 «기억했습니다» ──────────────────────────────────────────────
   ★«?qr=1» 은 방금 QR 로 들어오셨다는 표시(서버 _do_qr 이 붙인다).
   ★한 번 보여 드리고 주소에서 지운다 — 새로고침할 때마다 다시 뜨면 그건 잔소리다. */
function showQrOk(){
 if(location.search.indexOf('qr=1')<0)return;
 var d=document.getElementById('qrok'); if(!d)return;
 var n=document.getElementById('qrok_note');
 if(n)n.innerHTML='이 폰의 열쇠는 <b>약 __DAYS__일</b> 동안 살아 있고, 쓰실 때마다 <b>다시 __DAYS__일로 늘어납니다</b>'
  +' — 계속 쓰시는 한 끊기지 않습니다.<br>'
  +'★열쇠가 오가는 길은 <b>암호화(https)가 아닙니다</b>. 비밀번호 때와 같은 조건입니다 —'
  +' 카페·공항 같은 공용 와이파이에서는 쓰지 마세요.';
 d.classList.add('on');
 try{history.replaceState(null,'',location.pathname);}catch(e){}
}
function closeQrOk(next){
 var d=document.getElementById('qrok'); if(d)d.classList.remove('on');
 /* ★기억 안내를 닫으신 뒤에 홈 화면 안내를 띄운다 — 두 장이 겹쳐 뜨면 둘 다 안 읽히신다 */
 if(next)setTimeout(showA2HS,600);
}
function qrForget(btn){
 btn.disabled=true; btn.textContent='끊는 중…';
 fetch('/sessshort',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:'{}'})
  .then(function(r){return r.json();})
  .then(function(x){
    var n=document.getElementById('qrok_note');
    if(x&&x.ok){ if(n)n.innerHTML='<b>이 폰은 기억하지 않습니다.</b> 약 '+x.hours+'시간 뒤부터 다시 비밀번호를 여쭙습니다 —'
        +' 빌린 기기나 남의 폰으로 잠깐 보실 때 이렇게 쓰세요.';
      btn.textContent='알겠습니다'; btn.disabled=false;
      btn.onclick=function(){closeQrOk(true);}; }
    else { if(n)n.innerHTML='끊지 못했습니다'+((x&&x.error)?(' — '+_esc(x.error)):'')+'. 사무실 컴퓨터의 「📱 폰 접속 설정」에서 이 폰을 끊으실 수 있습니다.';
      btn.textContent='이 폰은 기억하지 않기'; btn.disabled=false; }
  })
  .catch(function(e){ btn.disabled=false; btn.textContent='이 폰은 기억하지 않기'; });
}
setTimeout(showQrOk,700);
setTimeout(function(){ if(location.search.indexOf('qr=1')<0) showA2HS(); },2200);
function finNav(d){finYear+=d;loadFin();}
function _won(n){try{return (Number(n)||0).toLocaleString('ko-KR')+'원';}catch(e){return n+'원';}}
function loadFin(){
 var t=document.getElementById('fin_title');if(t)t.textContent=finYear+'년 재정 통계·그래프';
 var b=document.getElementById('fin_body');if(b)b.innerHTML='<div class="fin-empty">불러오는 중…</div>';
 fetch('/finance-stats?year='+finYear).then(function(r){return r.json();}).then(renderFin).catch(function(){if(b)b.innerHTML='<div class="fin-empty">재정 자료를 불러오지 못했습니다.</div>';});
}
function _finArc(cx,cy,r,rr,a1,a2,col){
 function pt(rad,ang){var a=ang*Math.PI/180;return [cx+rad*Math.cos(a),cy+rad*Math.sin(a)];}
 var lg=(a2-a1)>180?1:0,p1=pt(r,a1),p2=pt(r,a2),p3=pt(rr,a2),p4=pt(rr,a1);
 return '<path d="M'+p1[0].toFixed(1)+' '+p1[1].toFixed(1)+' A'+r+' '+r+' 0 '+lg+' 1 '+p2[0].toFixed(1)+' '+p2[1].toFixed(1)+' L'+p3[0].toFixed(1)+' '+p3[1].toFixed(1)+' A'+rr+' '+rr+' 0 '+lg+' 0 '+p4[0].toFixed(1)+' '+p4[1].toFixed(1)+' Z" fill="'+col+'"/>';
}
var FINCOL=['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#64748b'];
function _finDonut(items){
 if(!items||!items.length)return '<div class="fin-empty2">기록 없음</div>';
 var tot=0;items.forEach(function(it){tot+=it[1];});if(tot<=0)return '<div class="fin-empty2">기록 없음</div>';
 var ang=-90,svg='<svg viewBox="0 0 120 120" class="fin-donut">',leg='';
 items.forEach(function(it,i){var fr=it[1]/tot,a2=ang+fr*360;if(fr>0.001)svg+=_finArc(60,60,52,30,ang,a2,FINCOL[i%8]);ang=a2;
  leg+='<div class="dl"><span style="background:'+FINCOL[i%8]+'"></span>'+esc(it[0])+' <b>'+Math.round(fr*100)+'%</b></div>';});
 svg+='</svg>';return '<div class="fin-donwrap">'+svg+'<div class="fin-donleg">'+leg+'</div></div>';
}
function _finBars(inc,exp){
 var mx=1,i;for(i=0;i<12;i++){mx=Math.max(mx,inc[i]||0,exp[i]||0);}
 var svg='<svg viewBox="0 0 660 140" class="fin-svg" preserveAspectRatio="xMidYMid meet">';
 for(i=0;i<12;i++){var x=18+i*53,ih=Math.round((inc[i]||0)/mx*98),eh=Math.round((exp[i]||0)/mx*98);
  svg+='<rect x="'+x+'" y="'+(108-ih)+'" width="18" height="'+ih+'" rx="2" fill="#10b981"/>';
  svg+='<rect x="'+(x+21)+'" y="'+(108-eh)+'" width="18" height="'+eh+'" rx="2" fill="#ef4444"/>';
  svg+='<text x="'+(x+19)+'" y="126" font-size="12" fill="#8a8f98" text-anchor="middle">'+(i+1)+'</text>';}
 svg+='</svg>';return svg+'<div class="fin-legend"><span class="lg" style="background:#10b981"></span>수입 &nbsp;<span class="lg" style="background:#ef4444"></span>지출</div>';
}
function _finGauge(label,act,bud,col){
 var pct=bud>0?Math.round(act/bud*100):0,w=Math.min(100,pct),over=act>bud;
 return '<div class="fin-gauge"><div class="gg-lab"><span>'+label+'</span><span>'+_won(act)+' / '+_won(bud)+' <b style="color:'+(over?"#ef4444":col)+'">'+pct+'%</b></div><div class="gg-bar"><div class="gg-fill" style="width:'+w+'%;background:'+(over?'#ef4444':col)+'"></div></div>'+(over?'<div class="gg-over">⚠ 예산 초과</div>':'')+'</div>';
}
function renderFin(s){
 var b=document.getElementById('fin_body');if(!b)return;
 if(!s||!s.total||(!s.total.수입&&!s.total.지출)){b.innerHTML='<div class="fin-empty">'+finYear+'년 재정 기록이 없습니다. ‘재정 기록’ 카드로 헌금·지출을 입력하면 여기에 그래프가 나타납니다.</div>';return;}
 var t=s.total,H='';
 H+='<div class="fin-kpis"><div class="fk in"><small>수입</small><b>'+_won(t.수입)+'</b></div>'
   +'<div class="fk out"><small>지출</small><b>'+_won(t.지출)+'</b></div>'
   +'<div class="fk bal"><small>잔액</small><b>'+_won(t.잔액)+'</b></div></div>';
 H+='<div class="fin-card"><h5>월별 수입·지출 추이</h5>'+_finBars(s.months||[],s.mexp||[])+'</div>';
 H+='<div class="fin-2col"><div class="fin-card"><h5>헌금 종류 비중</h5>'+_finDonut(s.inc)+'</div>'
   +'<div class="fin-card"><h5>지출 항목 비중</h5>'+_finDonut(s.exp)+'</div></div>';
 if(s.budget&&(s.budget.in_bud||s.budget.out_bud)){
  H+='<div class="fin-card"><h5>예산 대비 집행</h5>'+_finGauge('수입 달성',s.budget.in_act,s.budget.in_bud,'#10b981')+_finGauge('지출 집행',s.budget.out_act,s.budget.out_bud,'#3b82f6')+'</div>';
 }
 if(s.dept&&s.dept.length){
  var dh='<div class="fin-card"><h5>부서별 수입·지출</h5><table class="fin-tbl"><tr><th>부서</th><th>수입</th><th>지출</th></tr>';
  s.dept.forEach(function(d){dh+='<tr><td>'+esc(d[0])+'</td><td class="ri">'+_won(d[1].수입)+'</td><td class="ri">'+_won(d[1].지출)+'</td></tr>';});
  dh+='</table></div>';H+=dh;
 }
 b.innerHTML=H;
}
function calNav(dv){calM+=dv;if(calM<1){calM=12;calY--;}if(calM>12){calM=1;calY++;}renderCal();}
function _easter(y){var a=y%19,b=Math.floor(y/100),c=y%100,d=Math.floor(b/4),e=b%4,f=Math.floor((b+8)/25),g=Math.floor((b-f+1)/3);var h=(19*a+b-d-g+15)%30,i=Math.floor(c/4),k=c%4,l=(32+2*e+2*i-h-k)%7,m=Math.floor((a+11*h+22*l)/451);var mo=Math.floor((h+l-7*m+114)/31),da=((h+l-7*m+114)%31)+1;return new Date(y,mo-1,da);}
function _churchCal(y,mon){var E=_easter(y),D=function(base,off){var x=new Date(base);x.setDate(x.getDate()+off);return x;};var firstSun=function(m){var d=new Date(y,m-1,1);d.setDate(1+((7-d.getDay())%7));return d;};var xmas=new Date(y,11,25),sun4=D(xmas,-xmas.getDay()),adv1=D(sun4,-21);var L=[[D(E,-46),'재의 수요일 (사순절 시작)'],[D(E,-7),'종려주일 · 고난주간'],[D(E,-2),'성금요일'],[E,'부활절'],[D(E,49),'성령강림절'],[firstSun(7),'맥추감사주일'],[D(firstSun(11),14),'추수감사주일'],[adv1,'대림절 첫 주일'],[xmas,'성탄절'],[new Date(y,0,1),'신정']];var map={};L.forEach(function(it){var dt=it[0];if(dt.getFullYear()===y&&dt.getMonth()+1===mon)map[dt.getDate()]=it[1];});return map;}
function renderCal(){
 var ym=calY+'-'+('0'+calM).slice(-2);
 document.getElementById('cal_title').textContent=calY+'년 '+calM+'월';
 fetch('/events?month='+ym).then(function(r){return r.json();}).then(function(evs){
  var byday={};evs.forEach(function(e){var dd=parseInt(String(e['날짜']).slice(8,10),10);(byday[dd]=byday[dd]||[]).push(e);});
  var dows=['일','월','화','수','목','금','토'],h='';
  dows.forEach(function(dw,i){h+='<div class="cal-dow'+(i===0?' sun':'')+'">'+dw+'</div>';});
  var first=new Date(calY,calM-1,1).getDay(),days=new Date(calY,calM,0).getDate();
  var td=new Date(),thisM=(td.getFullYear()===calY&&td.getMonth()+1===calM);
  var litur=_churchCal(calY,calM);
  for(var i=0;i<first;i++)h+='<div class="cal-cell empty"></div>';
  for(var d=1;d<=days;d++){
   var dow=(first+d-1)%7,evh='';
   if(litur[d])evh+='<div class="cal-litur" title="교회력">✝ '+esc(litur[d])+'</div>';
   (byday[d]||[]).forEach(function(e){var Q=String.fromCharCode(39);evh+='<div class="cal-ev'+(e['중요']?' imp':'')+'" onclick="delEvent(event,'+e.id+','+Q+String(e['제목']).split(Q).join('')+Q+')">'+(e['중요']?'★':'')+esc(String(e['제목']))+'</div>';});
   h+='<div class="cal-cell'+(thisM&&d===td.getDate()?' today':'')+'" onclick="addEvent('+d+')"><div class="dnum'+(dow===0?' sun':'')+'">'+d+'</div>'+evh+'</div>';
  }
  document.getElementById('cal_grid').innerHTML=h;
 }).catch(function(){});
}
function addEvent(d){
 var ym=calY+'-'+('0'+calM).slice(-2)+'-'+('0'+d).slice(-2);
 var t=prompt(ym+' — 일정 제목을 적으세요 (중요한 날은 앞에 ★):');
 if(!t)return;var imp='';if(t.indexOf('★')===0){imp='1';t=t.replace('★','').replace(/^ +/,'');}
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:JSON.stringify({cmd:'event-add',args:{date:ym,title:t,important:imp}})}).then(function(){renderCal();if(typeof loadStats==='function')loadStats();});
}
function delEvent(e,id,title){
 e.stopPropagation();if(!confirm('"'+title+'" 일정을 삭제할까요?'))return;
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:JSON.stringify({cmd:'event-del',args:{id:id}})}).then(function(){renderCal();if(typeof loadStats==='function')loadStats();});
}
function calPrint(){var ym=calY+'-'+('0'+calM).slice(-2);closeCal();runQuick('cal-print',{month:ym},calY+'년 '+calM+'월 일정 달력 인쇄');}
document.getElementById('mgo').onclick=function(){
 var args={},miss=null;cur[4].forEach(function(f){var v=document.getElementById('fld_'+f[0]).value.trim();if(v)args[f[0]]=v;else if(f[3]&&!miss)miss=f[1];});
 var o=document.getElementById('mo');
 if(miss){o.className='out on';o.textContent='⚠ "'+miss+'" 칸을 먼저 입력해 주세요.';return;}
 o.className='out on';o.textContent='실행 중...';
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:JSON.stringify({cmd:cur[1],args:args})})
  .then(function(r){return r.text();}).then(function(t){o.className='out on ok';DRAFT[cur[1]]=null;renderOut(o,t);loadStats();})
  .catch(function(e){o.className='out on';o.textContent=isNet(e)?NETERR:'오류: '+e;});
};
function baseName(p){var a=p.split('/');p=a[a.length-1];var b=p.split(String.fromCharCode(92));return b[b.length-1];}
function findPath(line){var low=line.toLowerCase();var exts=['.docx','.hwp','.hwpx','.xlsx','.pptx','.pdf','.txt'];var end=-1,el=0;
 // ★같은 자리면 ★긴 확장자가 이긴다(.hwp 가 .hwpx 의 x 를 잘라먹지 않게) — 서버쪽 _srv_findpath 와 한 쌍이다
 for(var i=0;i<exts.length;i++){var p=low.lastIndexOf(exts[i]);
  if(p>=0&&(p>end||(p===end&&exts[i].length>el))){end=p;el=exts[i].length;}}
 if(end<0)return null;end+=el;var start=-1;
 for(var j=end-1;j>0;j--){var c=line.charAt(j),pv=line.charAt(j-1);if(c===':'&&((pv>='A'&&pv<='Z')||(pv>='a'&&pv<='z'))){start=j-1;break;}}
 if(start<0)return null;return line.substring(start,end);}
function parentDir(p){var i=Math.max(p.lastIndexOf('/'),p.lastIndexOf(String.fromCharCode(92)));return i>0?p.substring(0,i):p;}
function addOpen(o,path,label,icon,tail){var b=document.createElement('button');b.className='fileopen';b.textContent=(icon||'📂')+' '+(label||baseName(path))+(tail||' — 눌러서 열기');b.onclick=function(){openPath(path,b);};o.appendChild(b);}
function addRun(o,cmd,args,label){var b=document.createElement('button');b.className='fileopen';b.textContent=label||cmd;b.onclick=function(){runQuick(cmd,args,label||cmd);};o.appendChild(b);}
// ★문자 단추 — ★프로그램이 문자를 ★보내지 않는다. 폰의 ★문자 앱을 «열어» 줄 뿐이고,
//   보내기는 목사님이 그 앱에서 직접 누르신다. 그래서 ★발송 요금 대행업체를 쓰지 않는다.
// ★iOS 와 안드로이드가 ★구분자가 다르다(iOS 는 &, 안드로이드는 ?). 화면에 이미 있는 _isIOS() 로 가른다.
function addSms(o,num,body,label){
 var n=(num||'').replace(/[^0-9+]/g,'');
 if(!n){var w=document.createElement('div');w.className='rnote';
  w.textContent='⚠ '+(label||'')+' — 연락처가 없어 문자 앱을 열 수 없습니다.';o.appendChild(w);return;}
 // ★★사무실 컴퓨터에서는 ★단추를 ★아예 만들지 않는다 (master G3 관문 F · 2026-08-28).
 //   종전엔 단추를 만들고 그 옆에 «폰에서 누르세요»라고 ★적기만 했다.
 //   그러면 ★눌리는데 아무 일이 없는 단추가 된다 — 오너 규율
 //   「안 되는 걸 된다고 해 놓으면 그 순간 신뢰가 무너진다」에 정면으로 걸린다.
 //   ⇒ ★안 되는 자리에서는 ★단추를 감추고 ★왜 없는지를 대신 적는다.
 if(!REMOTE){var t=document.createElement('div');t.className='rnote';
  t.textContent='💬 '+(label||n)+' — 문자 앱은 ★폰에서만 열 수 있어 이 컴퓨터에서는 단추를 만들지 않았습니다. 아래 문구를 복사해 쓰십시오.';
  o.appendChild(t);return;}
 // ★안드로이드 기준 · 표준형 물음표 body (오너 결정 2026-08-28).
 //   ★아이폰 전용 변형(&body=)은 ★넣지 않는다 — 확인하지 못한 것을 코드로 단정하지 않는다.
 var a=document.createElement('a');a.className='lk sms';
 a.href='sms:'+n+(body?'?body='+encodeURIComponent(body):'');
 a.textContent='💬 '+(label||n);
 o.appendChild(a);
}
// ★전화번호와 주소는 ★눌러서 바로 되게 한다.
//   폰이 PC 와 다른 가장 큰 이유가 이것이다. 번호를 눈으로 읽고 손으로 옮겨 적게 하면
//   그건 PC 화면을 줄여 놓은 것일 뿐이다. (전화 = 한 번 누르면 걸린다 / 주소 = 지도앱이 열린다)
// ★역슬래시 기호를 쓰지 않는다 — 이 화면 글은 파이썬 따옴표 안에 살아서,
//   파이썬이 그것을 자기 탈출문자로 읽고 경고를 낸다(앞으로는 오류가 될 수 있다).
//   그래서 같은 뜻을 [0-9]·[ ] 로 적는다.
var TELRE=/(0[0-9]{1,2}[-. ]?[0-9]{3,4}[-. ]?[0-9]{4})/g;
var ADDRRE=/((?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)[^ ]*(?:[ ]+[^ ]+){1,6}?(?:로|길|동|리|가)[ ]*[0-9][0-9-]*(?:[ ]*[^ ,]{0,12}(?:아파트|빌라|타워|맨션|오피스텔|호|동))?)/g;
function _mkTel(num){var a=document.createElement('a');a.className='lk tel';
 a.href='tel:'+num.replace(/[^0-9+]/g,'');a.textContent='📞 '+num;return a;}
function _mkMap(addr){var a=document.createElement('a');a.className='lk map';
 a.href='https://map.kakao.com/link/search/'+encodeURIComponent(addr);
 a.target='_blank';a.rel='noopener';a.textContent='📍 '+addr;return a;}
function linkify(d,line){
 // 한 줄을 [보통글자 · 전화 · 주소] 조각으로 쪼갠다. 조각은 ★요소로 만든다(문자열로 붙이지 않는다).
 var marks=[],m;
 TELRE.lastIndex=0;while((m=TELRE.exec(line))!==null)marks.push([m.index,m.index+m[0].length,'tel',m[0]]);
 ADDRRE.lastIndex=0;while((m=ADDRRE.exec(line))!==null)marks.push([m.index,m.index+m[0].length,'map',m[0]]);
 marks.sort(function(x,y){return x[0]-y[0];});
 var out=[],last=0;
 marks.forEach(function(k){if(k[0]<last)return;   // 겹치면 앞의 것만 쓴다
  out.push([last,k[0],null]);out.push([k[0],k[1],k]);last=k[1];});
 if(!out.length){d.textContent=line;return false;}
 out.push([last,line.length,null]);
 out.forEach(function(seg){
  var txt=line.substring(seg[0],seg[1]);if(!txt)return;
  if(seg[2])d.appendChild(seg[2][2]==='tel'?_mkTel(seg[2][3]):_mkMap(seg[2][3]));
  else d.appendChild(document.createTextNode(txt));});
 return true;
}
// ★폰으로 받는 단추 — 주소에 ★번호표만 들어간다(경로가 아니다).
//   경로는 서버만 알고, 서버가 검사한 것만 번호표가 된다.
function addGet(o,tid,name){var a=document.createElement('a');a.className='fileopen getlink';
 a.href='/download?id='+encodeURIComponent(tid);a.setAttribute('download',name);
 a.textContent='📥 '+name+' — 눌러서 내려받기';o.appendChild(a);}
function renderOut(o,t){o.innerHTML='';
 // 받기 단추가 하나라도 있으면, 아래 '사무실에 저장되었습니다' 안내는 겹치므로 내지 않는다
 var hasGet=/^▶받기[|]/m.test(t||'');
 (t||'완료').split(String.fromCharCode(10)).forEach(function(line){
  var rg=line.match(/^▶받기[|](.+?)[|](.+)$/);
  if(rg){addGet(o,rg[1],rg[2]);return;}
  var sm=line.match(/^▶문자[|](.*?)[|](.*?)[|](.+)$/);
  if(sm){addSms(o,sm[1],sm[2],sm[3]);return;}
  var m=line.match(/^▶열기[|](.+?)[|](.+)$/);
  if(m){addOpen(o,m[1],m[2],'📂','');return;}
  var rc=line.match(/^▶실행[|](.+?)[|](.*?)[|](.+)$/);
  if(rc){var ar={};rc[2].split(',').forEach(function(kv){var kp=kv.split('=');if(kp[0])ar[kp[0].trim()]=(kp.slice(1).join('=')||'').trim();});addRun(o,rc[1],ar,rc[3]);return;}
  var d=document.createElement('div');linkify(d,line);o.appendChild(d);
  var fp=findPath(line);
  // ★폰에서는 이 단추를 만들지 않는다 — 파일을 여는 것은 ★사무실 컴퓨터에서만 되는 일이라,
  //   폰에 띄우면 눌러도 아무 일이 없다. 안 되는 것을 된다고 적지 않는다.
  if(fp&&!REMOTE){addOpen(o,fp,null,'📂',' — 이 문서 열기');addOpen(o,parentDir(fp),'이 파일이 있는 폴더','🗂️',' 열기');}
  else if(fp&&REMOTE&&!hasGet){var n=document.createElement('div');n.className='rnote';
   /* ★«저장되었습니다»라 하지 않는다 (2026-09-01) — 악보 열기처럼 ★문서를 만들지 않는
      카드도 이 줄을 탄다. 두 경우 다 참인 문장으로 적는다. */
   n.textContent='📄 '+baseName(fp)+' — 이 파일은 사무실 컴퓨터에 있습니다(폰으로는 받으실 수 없습니다).';o.appendChild(n);}
});}
function openPath(p,btn){if(btn)btn.textContent='📂 '+baseName(p)+' 여는 중...';
  fetch('/run',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:JSON.stringify({cmd:'open-file',args:{file:p}})})
   .then(function(r){return r.text();}).then(function(t){if(btn)btn.textContent='📂 '+baseName(p)+' — '+(t.indexOf('여는')>=0?'열렸습니다':t.slice(0,40));}).catch(function(e){if(btn)btn.textContent=isNet(e)?'⚠ 서버 꺼짐 — ★교회행정 시작 다시 실행':'오류';});
}
function browsePrev(btn){var L='📂 지난 자료 찾기 — 내 PC(C·D·USB)에서 예전 작업 열기';
  // ★폰이면 아예 하지 않고 사실대로 말한다(단추는 위에서 숨겼지만, 숨김이 뚫려도 거짓말은 안 하게).
  if(REMOTE){if(btn){btn.textContent='이 기능은 사무실 컴퓨터에서만 됩니다';setTimeout(function(){btn.textContent=L;},3500);}return;}
  if(btn)btn.textContent='📂 내 PC 여는 중...';
  fetch('/run',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:JSON.stringify({cmd:'open-file',args:{file:'shell:MyComputerFolder'}})})
   // ★응답을 ★보고 나서 말한다 — 종전엔 막혔든 말든 '내 PC 열림'이라고 적었다.
   .then(function(r){return r.text().then(function(t){return {ok:r.ok,t:t};});})
   .then(function(x){if(btn){btn.textContent=x.ok?'📂 내 PC 열림 — C·D·USB에서 예전 자료를 찾으세요':'⚠ 열지 못했습니다';setTimeout(function(){btn.textContent=L;},4500);}}).catch(function(e){if(btn)btn.textContent=isNet(e)?'⚠ 서버 꺼짐 — ★교회행정 시작 다시 실행':'오류';});
}
document.getElementById('modal').onclick=function(e){if(e.target.id==='modal')closeM();};
function closeW(){document.getElementById('welcome').classList.remove('on');try{localStorage.setItem('seen2','1');}catch(e){}}
function makeManual(){var o=document.getElementById('wout');o.className='out on';o.textContent='설명서 만드는 중...';
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:JSON.stringify({cmd:'manual',args:{}})})
  .then(function(r){return r.text();}).then(function(t){o.className='out on ok';o.textContent=t+' — 01 교회 기본·조직 폴더에서 [사용설명서] 파일을 여세요.';})
  .catch(function(e){o.textContent=isNet(e)?NETERR:'오류: '+e;});}
function quitApp(){if(!confirm('프로그램을 종료할까요?'))return;
 fetch('/shutdown',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:'{}'}).catch(function(){});
 document.body.innerHTML='<div style="text-align:center;margin-top:120px;color:#888;font-family:sans-serif"><h1>프로그램이 종료되었습니다 🙏</h1><p>이 인터넷 창을 닫으셔도 됩니다.</p></div>';}
function tg(){var r=document.documentElement;var cur=r.getAttribute('data-theme');var dark=cur?cur==='dark':matchMedia('(prefers-color-scheme:dark)').matches;r.setAttribute('data-theme',dark?'light':'dark');}
function toggleThemePanel(e){if(e)e.stopPropagation();var p=document.getElementById('themepanel');if(p){if(!p.classList.contains('on'))loadBgList();p.classList.toggle('on');}}
function loadBgList(){var box=document.getElementById('tp_photos');if(!box)return;
 fetch('/bglist').then(function(r){return r.json();}).then(function(fs){
  var Q=String.fromCharCode(39),cur=localStorage.getItem('thphoto')||'';
  var html='<div class="tp-thumb tp-none'+(cur?'':' sel')+'" onclick="setPhoto('+Q+Q+')" title="없음(기본 배경)">✕</div>';
  (fs||[]).forEach(function(f){var u='/bg?f='+encodeURIComponent(f);html+='<div class="tp-thumb'+(f===cur?' sel':'')+'" onclick="setPhoto('+Q+encodeURIComponent(f)+Q+')" style="background-image:url('+Q+u+Q+')" title="'+esc(f)+'"></div>';});
  box.innerHTML=html;
  if(!fs||!fs.length)box.innerHTML='<span class="tp-empty">_내자료 › 배경 폴더에 사진(jpg·png)을 넣어 보세요.</span>';
 }).catch(function(){box.innerHTML='<span class="tp-empty">사진 목록을 불러오지 못했습니다.</span>';});}
function setPhoto(f){var r=document.documentElement,DQ=String.fromCharCode(34);
 if(f){r.style.setProperty('--bgphoto','url('+DQ+'/bg?f='+f+DQ+')');r.setAttribute('data-bg','photo');}
 else{r.removeAttribute('data-bg');r.style.removeProperty('--bgphoto');}
 _thSave('thphoto',f?decodeURIComponent(f):'');loadBgList();}
function uploadBg(inp){var f=inp.files&&inp.files[0];if(!f){return;}
 if(f.size>25*1024*1024){alert('사진이 너무 큽니다. 25MB 이하로 넣어 주세요.');inp.value='';return;}
 var box=document.getElementById('tp_photos');if(box)box.innerHTML='<span class="tp-empty">사진 올리는 중…</span>';
 var rd=new FileReader();
 rd.onload=function(){
  fetch('/bgupload',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:JSON.stringify({name:f.name,data:rd.result})}).then(function(r){return r.json();}).then(function(j){
   inp.value='';
   if(j&&j.ok){setPhoto(encodeURIComponent(j.name));}
   else{alert('사진 추가에 실패했습니다: '+((j&&j.error)||'알 수 없는 오류'));loadBgList();}
  }).catch(function(){inp.value='';alert('사진 추가 중 오류가 났습니다.');loadBgList();});
 };
 rd.onerror=function(){inp.value='';alert('사진을 읽지 못했습니다.');loadBgList();};
 rd.readAsDataURL(f);}
function _thSave(k,v){try{if(v)localStorage.setItem(k,v);else localStorage.removeItem(k);}catch(e){}}
function setMode(m){document.documentElement.setAttribute('data-theme',m);_thSave('thmode',m);}
function setColor(c){var r=document.documentElement;if(c)r.setAttribute('data-color',c);else r.removeAttribute('data-color');_thSave('thcolor',c);}
function setSeason(s){var r=document.documentElement;if(s)r.setAttribute('data-season',s);else r.removeAttribute('data-season');_thSave('thseason',s);}
document.addEventListener('click',function(){var p=document.getElementById('themepanel');if(p)p.classList.remove('on');});
(function(){try{var r=document.documentElement,m=localStorage.getItem('thmode'),c=localStorage.getItem('thcolor'),s=localStorage.getItem('thseason'),ph=localStorage.getItem('thphoto');if(m)r.setAttribute('data-theme',m);if(c)r.setAttribute('data-color',c);if(s)r.setAttribute('data-season',s);if(ph){r.style.setProperty('--bgphoto','url('+String.fromCharCode(34)+'/bg?f='+encodeURIComponent(ph)+String.fromCharCode(34)+')');r.setAttribute('data-bg','photo');}}catch(e){}})();
function updateApp(){
 var NL=String.fromCharCode(10);
 if(!confirm('최신 버전으로 업데이트할까요?'+NL+NL+'입력하신 교인·심방·재정 등 모든 자료는 그대로 보존됩니다.'+NL+'(기능·문서 서식만 최신으로 교체됩니다)'))return;
 cur=['','update','프로그램 업데이트','🔄',[]];
 document.getElementById('mt').textContent='🔄 프로그램 업데이트';
 document.getElementById('ms').textContent='최신 버전으로 안전 교체 (자료는 보존)';
 document.getElementById('mf').innerHTML='';
 var o=document.getElementById('mo');o.className='out on';o.textContent='최신 버전을 확인하고 있습니다... (인터넷에서 새 파일을 받아옵니다)';
 document.getElementById('modal').classList.add('on');
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:JSON.stringify({cmd:'update',args:{}})})
  .then(function(r){return r.text();}).then(function(t){o.className='out on ok';renderOut(o,t);
    if(t.indexOf('업데이트 완료')>=0){setTimeout(function(){location.reload(true);},6000);}})
  .catch(function(e){o.className='out on';o.textContent=isNet(e)?NETERR:'오류: '+e;});
}
(function(){var el=document.getElementById('today');if(!el)return;var d=new Date();var w=['일','월','화','수','목','금','토'][d.getDay()];el.textContent=d.getFullYear()+'년 '+(d.getMonth()+1)+'월 '+d.getDate()+'일 ('+w+'요일)';})();
(function(){var p=document.getElementById('pastorName');var a=document.getElementById('avatarInit');if(p&&a){var t=(p.textContent||'').trim();if(t)a.textContent=t.charAt(0);}})();
try{if(!localStorage.getItem('seen2'))document.getElementById('welcome').classList.add('on');}catch(e){}
</script>
</body></html>"""

LOGIN_PAGE = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__CHURCH__ 교회행정</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  :root{--paper:#F4F2EC;--surface:#FFFFFF;--ink:#14171C;--muted:#6A7078;--line:#E7E3D8;
        --brand:#1E3A34;--crit:#B23B3B;
        --font:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",-apple-system,system-ui,sans-serif}
  @media (prefers-color-scheme:dark){
    :root{--paper:#0E1115;--surface:#161A20;--ink:#ECEEF1;--muted:#98A0AA;--line:#252B33;
          --brand:#6FA898;--crit:#D97C7C}
  }
  body{background:var(--paper);color:var(--ink);font-family:var(--font);font-size:16px;line-height:1.6;
       min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px 18px}
  /* ★아이폰 사파리는 주소창 때문에 100vh 가 실제로 보이는 높이보다 크다. 가운데 정렬과 겹치면
     로그인 상자의 아래쪽이 화면 밖으로 밀린다 — ★심방지에서 못 들어가시는 화면이다.
     그래서 실제로 보이는 높이(dvh)를 쓴다. 모르는 브라우저는 위의 100vh 를 그대로 쓴다. */
  @supports (min-height:100dvh){ body{min-height:100dvh} }
  .box{width:100%;max-width:400px;background:var(--surface);border:1px solid var(--line);
       border-radius:18px;padding:32px 24px 26px;box-shadow:0 10px 40px rgba(0,0,0,.10)}
  .mark{width:52px;height:52px;border-radius:14px;background:var(--brand);display:grid;place-items:center;
        margin:0 auto 18px}
  .mark svg{width:27px;height:27px}
  h1{font-size:21px;font-weight:800;text-align:center;letter-spacing:-.3px}
  .sub{text-align:center;color:var(--muted);font-size:14px;margin-top:7px;line-height:1.55}
  label{display:block;font-size:14px;font-weight:700;color:var(--muted);margin:24px 0 8px}
  input{width:100%;padding:15px 16px;border-radius:12px;border:1px solid var(--line);
        background:var(--paper);color:var(--ink);font-size:17px;font-family:inherit;min-height:52px}
  input:focus{outline:0;border-color:var(--brand)}
  button{width:100%;margin-top:18px;padding:16px;min-height:54px;border:0;border-radius:12px;
         background:var(--brand);color:#fff;font-size:17px;font-weight:800;font-family:inherit;cursor:pointer}
  button:disabled{opacity:.6}
  .msg{margin-top:14px;color:var(--crit);font-size:14.5px;text-align:center;line-height:1.55;min-height:1px}
  .note{margin-top:22px;padding-top:18px;border-top:1px solid var(--line);
        color:var(--muted);font-size:13px;line-height:1.7}
  .note b{color:var(--ink)}
</style></head><body>
<div class="box">
  <div class="mark"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.9" stroke-linecap="round"><path d="M12 3v18M7 8h10M4 21h16M6 21v-9l6-4 6 4v9"/></svg></div>
  <h1>__CHURCH__ 교회행정</h1>
__PANEL__
</div>
<script>
function doLogin(ev){
  if(ev&&ev.preventDefault)ev.preventDefault();
  var i=document.getElementById('pw');if(!i)return false;
  var m=document.getElementById('msg'),b=document.getElementById('go');
  var v=i.value||'';
  if(!v){m.textContent='비밀번호를 넣어 주세요.';return false;}
  b.disabled=true;b.textContent='확인하는 중...';m.textContent='';
  // ★'이 폰 기억하기' — 체크하면 약 30일, 끄면 브라우저를 닫을 때까지만.
  //   단추가 없는 옛 화면이면 켠 것으로 본다(종전 동작 유지).
  var _r=document.getElementById('rmb'); var _rem=_r?!!_r.checked:true;
  fetch('/login',{method:'POST',headers:{'Content-Type':'application/json','X-Church-App':'1'},body:JSON.stringify({pw:v,remember:_rem})})
   .then(function(r){return r.json();})
   .then(function(d){
     if(d&&d.ok){location.href='/';return;}
     b.disabled=false;b.textContent='들어가기';i.value='';
     m.textContent=(d&&d.error)?d.error:'비밀번호가 맞지 않습니다.';
   })
   .catch(function(){
     b.disabled=false;b.textContent='들어가기';
     m.textContent='연결하지 못했습니다. 사무실 컴퓨터에서 프로그램이 켜져 있는지 확인해 주세요.';
   });
  return false;
}
(function(){var i=document.getElementById('pw');if(i)i.focus();})();
</script>
</body></html>"""

LOGIN_PANEL = """  <p class="sub">폰에서 처음 들어오셨습니다.<br>정해 두신 비밀번호를 한 번만 넣어 주세요.</p>
  <form onsubmit="return doLogin(event)">
    <label for="pw">비밀번호</label>
    <input id="pw" type="password" autocomplete="current-password" inputmode="text" placeholder="비밀번호">
    <label style="display:flex;align-items:center;gap:8px;margin:10px 2px 4px;font-size:15px;font-weight:400">
      <input id="rmb" type="checkbox" checked style="width:20px;height:20px;flex:none">
      이 폰 기억하기 (약 __DAYS__일 동안 다시 안 묻습니다)</label>
    <div class="note" style="margin:0 2px 10px">끄시면 <b>브라우저를 닫을 때까지만</b> 열립니다 —
      다른 분 폰이나 빌린 기기로 잠깐 보실 때 꺼 주세요.</div>
    <button id="go" type="submit">들어가기</button>
  </form>
  <div class="msg" id="msg">__ERROR__</div>
  <div class="note"><b>한 번만 넣으시면 됩니다.</b> 그 뒤로는 이 폰에서 바로 열립니다(약 __DAYS__일).
  사무실 컴퓨터에서는 지금까지처럼 비밀번호를 묻지 않습니다.</div>
  <!-- ★이 비밀번호가 ★무엇을 막고 ★무엇을 못 막는지 그대로 적는다(오너 티켓 §1-6).
       지금 연결은 https 가 아니다 — '안전합니다'라고 쓰지 않는다. -->
  <div class="note"><b>이 비밀번호가 막아 주는 것</b><br>
  같은 와이파이에 있는 다른 사람이 <b>우연히 열어 보는 것</b>을 막아 줍니다.<br><br>
  <b>막지 못하는 것</b><br>
  지금 연결은 암호화(https)가 아닙니다. 같은 와이파이에서 <b>작정하고 엿보면 비밀번호가 보일 수 있습니다.</b><br>
  ★<b>「이 폰 기억하기」로 만들어지는 열쇠도 같은 조건입니다</b> — 비밀번호를 안 묻는 대신 그 열쇠가 오갑니다.
  기억을 켜셨다고 더 위험해지는 것은 아니지만, <b>더 안전해지는 것도 아닙니다.</b><br>
  ★<b>카페·공항 같은 공용 와이파이에서는 쓰지 마세요.</b></div>"""

NOPW_PANEL = """  <p class="sub">아직 폰 접속 비밀번호를 정하지 않으셨습니다.</p>
  <div class="note"><b>사무실 컴퓨터에서 먼저 정해 주세요.</b><br>
  프로그램 화면 &gt; 시스템 &gt; <b>폰 접속 설정</b> 카드에서 비밀번호를 정하시면,
  그때부터 이 폰에서 들어오실 수 있습니다.<br><br>
  비밀번호를 정하기 전에는 폰 접속이 열리지 않습니다 — 교인 명부를 지키기 위한 안전장치입니다.</div>"""

def _python_exe():
    # 서버가 pythonw로 떠도, 명령 실행은 stdout 있는 python.exe로
    e=sys.executable
    if e.lower().endswith("pythonw.exe"):
        c=e[:-len("pythonw.exe")]+"python.exe"
        if os.path.exists(c): return c
    return e
PYEXE=_python_exe()
def _beep(ok=True):
    """실행 결과 소리 피드백 — 성공/실패 다른 소리. (화면 아닌 서버 쪽에서 재생 → 프리미엄 디자인 무접촉)"""
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_OK if ok else winsound.MB_ICONHAND)
    except Exception: pass
def _ensure_desktop_icon():
    """★바탕화면 아이콘을 알아서 만들어 드린다(켤 때마다 점검, 필요할 때만 작업).

       왜 자동인가 — 예전에는 목사님이 「바탕화면 아이콘 만들기」 파일을 따로 찾아
       한 번 더 실행하셔야 했다. 시작 파일과 이름이 비슷해 헷갈리고, 그 단계를 놓치면
       매번 폴더를 뒤져 들어가셔야 한다. 압축 풀고 한 번 누르면 끝나야 한다.

       교회 이름을 나중에 넣으시면 아이콘 이름도 따라 바꾼다(옛 아이콘은 지운다).
       실패해도 프로그램은 정상 실행되어야 하므로 모든 예외를 조용히 삼킨다."""
    if os.name != "nt":
        return
    root = os.path.dirname(BASE)                     # 설치 폴더(_시스템의 상위)
    target = os.path.join(root, "★ 교회행정 시작 (여기를 더블클릭).bat")
    if not os.path.exists(target):
        return                                       # 시작 파일이 없으면 만들 이유가 없다
    c = cfg()
    nm = str(c.get("교회명") or "").strip()
    if not nm or nm in ("○○교회", "OO교회", "교회"):
        nm = "교회 종합행정"                          # 아직 교회 이름을 안 넣으신 단계
        want = f"{nm}.lnk"
    else:
        want = f"{nm} 행정.lnk"
    prev = str(c.get("바탕화면아이콘") or "").strip()

    try:
        desktop = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20).stdout.strip()
    except Exception:
        return
    if not desktop or not os.path.isdir(desktop):
        return

    if prev == want and os.path.exists(os.path.join(desktop, want)):
        return                                       # 이미 있고 이름도 맞다 — 할 일 없음

    ico = os.path.join(BASE, "_교회행정아이콘.ico")
    env = dict(os.environ)
    env.update({"CI_DESK": desktop, "CI_WANT": want, "CI_TGT": target,
                "CI_DIR": root, "CI_ICO": ico if os.path.exists(ico) else "",
                "CI_PREV": (os.path.join(desktop, prev) if prev and prev != want else "")})
    ps = (
        "$p=$env:CI_PREV; if($p -and (Test-Path $p)){Remove-Item $p -Force -ErrorAction SilentlyContinue}; "
        "$w=New-Object -ComObject WScript.Shell; "
        "$s=$w.CreateShortcut((Join-Path $env:CI_DESK $env:CI_WANT)); "
        "$s.TargetPath=$env:CI_TGT; $s.WorkingDirectory=$env:CI_DIR; "
        "if($env:CI_ICO -and (Test-Path $env:CI_ICO)){$s.IconLocation=$env:CI_ICO+',0'}; "
        "$s.Description='교회 종합행정시스템 - 여기를 눌러 시작'; $s.Save()")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", ps], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=40, env=env)
        if r.returncode != 0 or not os.path.exists(os.path.join(desktop, want)):
            return
    except Exception:
        return

    try:                                             # 만든 이름을 기억해 둔다(다음에 이름이 바뀌면 교체)
        p = os.path.join(BASE, "church_config.json")
        cur = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
        cur["바탕화면아이콘"] = want
        json.dump(cur, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass
    print(f"  🖥  바탕화면에 「{want[:-4]}」 아이콘을 만들어 두었습니다 — 다음부터는 그것만 누르세요.")


def _save_error_log(cmd, detail):
    """영문 오류 원문을 화면 대신 파일로 남긴다. 목사님이 필요하실 때만 담당자에게 보내시면 된다.
       (파일로 남기는 데 실패해도 안내는 떠야 하므로 조용히 넘어간다)"""
    try:
        import datetime as _dt
        d=os.path.join(BASE,"_오류기록"); os.makedirs(d,exist_ok=True)
        stamp=_dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        p=os.path.join(d,f"오류_{stamp}.txt")
        open(p,'w',encoding='utf-8').write(
            f"[오류 기록]\n일시: {stamp}\n기능: {cmd}\n\n"
            "※ 이 파일을 프로그램을 보내주신 담당자에게 카톡·메일로 전달해 주시면\n"
            "   원인을 찾아 다음 업데이트에서 고쳐 드립니다.\n"
            "   교인·심방·재정 자료는 이 파일에 들어있지 않습니다.\n\n"
            "─── 아래는 기술적인 내용입니다 ───\n"+str(detail))
        return p
    except Exception:
        return None


def _friendly_error(cmd, detail):
    """★목사님께 영문 오류를 보여드리지 않는다.
       Traceback·ModuleNotFoundError 같은 영문 덩어리는 '내가 뭘 잘못했나' 하는 당황을 부른다.
       원인을 짐작해 한국어로 안내하고, 무엇을 하시면 되는지까지 알려 드린다.
       기술적인 내용은 _오류기록 폴더의 파일로 남겨 담당자에게 전달하실 수 있게 한다."""
    t=str(detail)
    if any(k in t for k in ("URLError","urlopen error","getaddrinfo","TimeoutError",
                            "timed out","ConnectionError","SSLError","HTTPError")):
        why="인터넷 연결이 잠시 끊겼거나 느린 것 같습니다."
        how=["인터넷이 되는지 확인하신 뒤 다시 한 번 눌러 주세요.",
             "교회 와이파이가 불안정하면 잠시 뒤 다시 시도해 보세요."]
    elif any(k in t for k in ("PermissionError","WinError 32","Access is denied","때문에 액세스할 수 없습니다")):
        why="지금 만들려는 파일이 다른 프로그램에서 열려 있는 것 같습니다."
        how=["한글·워드·엑셀에서 같은 이름의 문서가 열려 있으면 닫아 주세요.",
             "닫으신 뒤 다시 한 번 눌러 주세요."]
    elif any(k in t for k in ("ModuleNotFoundError","ImportError","DLL load failed")):
        why="프로그램 파일 일부가 빠졌거나 손상된 것 같습니다."
        how=["프로그램을 껐다가 다시 켜 보세요.",
             "그래도 안 되면 받으신 압축파일(zip)을 새 폴더에 다시 풀어 사용해 주세요.",
             "※ 교인·심방·재정 자료는 그대로 있습니다(따로 보관됩니다)."]
    elif any(k in t for k in ("No space left","WinError 112","디스크 공간")):
        why="컴퓨터 저장 공간이 부족한 것 같습니다."
        how=["필요 없는 파일을 지우거나 휴지통을 비우신 뒤 다시 해보세요."]
    elif "FileNotFoundError" in t or "WinError 2" in t:
        why="필요한 파일을 찾지 못했습니다."
        how=["파일 이름·위치가 맞는지 확인해 주세요.",
             "엑셀 파일을 넣으실 때는 프로그램 폴더에 두시면 파일 이름만 넣으셔도 됩니다."]
    elif "MemoryError" in t:
        why="한 번에 처리하기에 자료가 너무 큰 것 같습니다."
        how=["기간이나 범위를 나누어 다시 시도해 보세요."]
    elif "시간이 너무 오래" in t:
        why="시간이 오래 걸려 중단했습니다."
        how=["자료가 많으면 시간이 걸립니다. 잠시 뒤 다시 해보세요."]
    else:
        why="이 작업을 끝내지 못했습니다."
        how=["프로그램을 껐다 다시 켜고 한 번만 더 해보세요.",
             "그래도 안 되면 「★ 문제 해결 안내」 파일을 열어보세요."]
    log=_save_error_log(cmd, detail)
    L=["⚠ "+why,""]
    L+= ["  · "+h for h in how]
    L+= ["","  🔒 입력하신 교인·심방·재정 자료는 안전합니다. 그대로 있습니다."]
    if log:
        L+= ["","  ※ 계속 같은 일이 생기면 아래 파일을 담당자에게 보내주세요.",
             "     "+log]
    return "\n".join(L)


# ── 📄 폰으로 문서 받기 — 등록부(메모리) ────────────────────────────────
#   ★경로를 주소에 싣지 않는다. 화면(브라우저)이 "이 파일 주세요"라고 ★경로를 말하게 두면,
#     무엇을 받을지 화면이 정하게 된다. 그래서 ★서버가 먼저 검사한 것만 ★번호표(토큰)로 바꿔 주고,
#     화면은 그 번호표만 안다 — 경로를 모르고, 보낼 수도 없다.
#   ★번호표는 ★메모리에만 둔다(설정 파일에 적으면 그 파일을 본 사람이 문서를 받는다).
_DL={}                    # {번호표: [실경로, 만료시각, 세션키, 파일명]}
_DL_LOCK=threading.Lock()
DL_TTL=1800               # 30분 — 심방 중 눌러 받기엔 넉넉하고, 오래 남지도 않는다
DL_MAX=200                # 상한 — 무한 증식 방지
DL_MIME={"docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "pptx":"application/vnd.openxmlformats-officedocument.presentationml.presentation",
         "pdf":"application/pdf","hwp":"application/x-hwp","hwpx":"application/hwp+zip",
         "txt":"text/plain; charset=utf-8","png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg"}

# ★내보낼 수 있는 확장자 — ★이 목록에 없으면 어떤 뿌리에 있든 못 나간다.
#   뿌리 목록은 설정에 따라 넓어질 수 있지만 ★이 층은 남는다(자료·소스·백업 파일은 문서가 아니다).
DL_EXT={"docx","xlsx","pptx","pdf","hwp","hwpx","txt","png","jpg","jpeg"}
# ★악보 형식 — ★악보 폴더(SONGDIR) 안에서만 내보낸다 (2026-09-01 오너 결정: "pdf·사진·뮤즈스코어 등").
#   ★왜 DL_EXT 를 넓히지 않는가: 그러면 ★모든 허용 뿌리에서 이 형식들이 나갈 수 있게 된다.
#     악보는 언제나 악보 폴더에 복사된다(church.py song_add 가 shutil.copy2 로 옮긴다) —
#     그러니 ★그 폴더 하나만 열면 충분하고, 그것이 ★가장 좁은 문이다.
#   ★pdf·png·jpg 는 이미 DL_EXT 에 있어 여기 없어도 받아진다(중복해 적지 않는다).
#   ★heic 는 아이폰 카메라 기본 형식이다 — 악보를 사진으로 찍어 등록하시면 이것으로 들어온다.
SHEET_EXT={"mscz","mscx","musicxml","mxl","mid","midi","sib","gp","gpx","cap","heic","webp"}
# ★문서 분류 9종 — church.py 의 CAT() 과 ★같은 이름이어야 한다. 한쪽만 고치지 마라.
#   프로그램 루트 : "01 교회 기본·조직"  (점 없음)
#   아카이브루트  : "01. 교회 기본·조직" (★점 있음 — CAT() 이 n+". "+이름 으로 만든다)
DL_CATS=(("01","교회 기본·조직"),("02","예배·성례·예식"),("03","교육·훈련"),("04","목양·셀·심방·새가족"),
         ("05","선교"),("06","재정·증명"),("07","행사·홍보·자료"),("08","대외·인사·시설"),("09","설교"))

# ★한글 → 로마자 (ASCII 파일명 폴백)
#   ★왜 필요한가 — 2026-08-17 실측(_실험/cd_rule_probe.py · 폰 폭 390 · playwright webkit):
#     webkit(사파리 계열)은 `filename*=UTF-8''…` 를 ★읽지 않는다.
#       · filename* 만 보내면 ★주소 끝 글자로 이름을 짓는다(시험에서 'B.docx' 가 나왔다)
#       · ASCII `filename=` 이 있으면 ★언제나 그것을 쓴다(둘의 ★순서를 바꿔도 결과가 같다)
#     ⇒ 아이폰에서 실제로 저장되는 이름은 ★ASCII 폴백이다. 그러니 폴백이 뜻을 지녀야 한다.
#   종전 폴백은 `re.sub(r'[^A-Za-z0-9._-]','_',fn).strip('_')` 였다. 한글이 전부 '_' 가 되고
#   앞쪽 '_' 가 잘려 나가 `[발급] 교인 증명원_박대가족_2026-08-17.docx` 가 ★`2026-08-17.docx` 로
#   뭉개졌다 — 폰에 받아 놓고도 ★그게 무슨 문서인지 알 수 없다(브리프 D6 이 막으려던 바로 그 일).
#   ⇒ 음절을 자모로 풀어 로마자로 적는다. 표 3개면 ★모든 한글 파일명에 통한다(카드마다 손볼 필요 없다).
#   chromium 은 종전대로 filename* 의 ★한글 이름을 그대로 쓴다 — 기능 후퇴 0.
_RR_CHO=("g","kk","n","d","tt","r","m","b","pp","s","ss","","j","jj","ch","k","t","p","h")
_RR_JUNG=("a","ae","ya","yae","eo","e","yeo","ye","o","wa","wae","oe","yo","u","wo","we","wi",
          "yu","eu","ui","i")
_RR_JONG=("","k","k","ks","n","nj","nh","t","l","lk","lm","lb","ls","lt","lp","lh","m","b","bs",
          "s","ss","ng","j","ch","k","t","p","h")

def _romanize(s):
    """한글 음절을 로마자로. 한글이 아닌 글자는 그대로 둔다."""
    out=[]
    for ch in s:
        o=ord(ch)
        if 0xAC00<=o<=0xD7A3:
            i=o-0xAC00
            out.append(_RR_CHO[i//588]+_RR_JUNG[(i%588)//28]+_RR_JONG[i%28])
        else:
            out.append(ch)
    return "".join(out)

def _ascii_name(fn):
    """filename* 를 못 읽는 폰에서도 ★무엇인지 알아볼 수 있는 ASCII 이름을 만든다."""
    base,dot,ext = fn.rpartition(".")
    if not dot: base,ext = fn,""
    r=re.sub(r"[^A-Za-z0-9._-]+","_",_romanize(base))
    r=re.sub(r"_{2,}","_",r).strip("_.")
    if not r: r="document"
    e=re.sub(r"[^A-Za-z0-9]+","",ext).lower()
    return r[:120]+(("."+e) if e else "")

def _songdir_rc():
    """악보 폴더(`church.py` L1229 `SONGDIR`)의 ★normcase(realpath). 없으면 ★빈 문자열.

       ★왜 함수로 두는가: 이 값을 ★두 곳(`_dl_roots` 의 뿌리 · `_dl_check` ②겹의 예외)에서 쓴다.
         한쪽만 고치면 ★한쪽은 열리고 한쪽은 막혀 원인 모를 '되다 안 되다'가 된다 — 진실은 한 곳에 둔다.
       ★폴더가 없으면 빈 문자열을 돌려준다 ⇒ 예외가 ★아예 성립하지 않는다(닫히는 쪽으로 실패한다).
       ★`church.py` 의 `SONGDIR` 을 옮기면 ★여기도 같이 옮겨라."""
    try:
        d=os.path.join(BASE,"_내자료","찬양곡")
        if os.path.isdir(d): return os.path.normcase(os.path.realpath(d))
    except Exception: pass
    return ""

def _dl_roots():
    """문서를 폰으로 내보내도 되는 ★뿌리 목록. ★realpath 로 풀어서 돌려준다.

       ★normpath 가 아니라 realpath 인 이유: normpath 는 '..' 만 접고 ★바로가기(심볼릭링크·정션)를
         못 푼다. 뿌리 안에 바깥을 가리키는 바로가기가 있으면 그대로 통과해 버린다.
       ★뿌리 쪽도 함께 풀어야 한다 — 파일만 풀고 뿌리를 안 풀면 ★비교가 어긋난다.
       ★목록은 church.py 의 CAT() 이 만드는 폴더와 같아야 한다 — 한쪽만 고치지 마라."""
    out=[]
    def _add(d):
        try:
            if d and os.path.isdir(d): out.append(os.path.normcase(os.path.realpath(d)))
        except Exception: pass
    root=os.path.dirname(BASE)                     # 프로그램 루트(_시스템의 위)
    for n,nm in DL_CATS:
        _add(os.path.join(root, n+" "+nm))         # 프로그램 루트 쪽 — 번호 뒤에 ★점이 없다
    # ★자료 보관 폴더(아카이브루트)를 쓰시면 문서는 ★그 밑 '0X. 이름' 폴더에 저장된다
    #   (church.py 의 CAT(): n+". "+이름 — ★번호 뒤에 점이 붙는다. 프로그램 루트 쪽과 이름 규칙이 다르다).
    #   ★그 9개 폴더만 뿌리로 넣는다 — 보관 폴더 ★자체를 넣으면 그것이 프로그램 폴더의 상위일 때
    #   교인 명부·설정·백업·스냅샷까지 통째로 삼킨다. 9개만 넣으면 프로그램 폴더는 그 ★형제라 안 들어온다.
    try:
        ar=(_cfg_live() or {}).get("아카이브루트")
        if ar and os.path.isdir(ar):
            for n,nm in DL_CATS:
                _add(os.path.join(ar, n+". "+nm))  # 아카이브 쪽 — 번호 뒤에 ★점이 있다
    except Exception: pass
    # ★A23(부채 4-10) — 성경자료 폴더 ★하나만 덧붙인다 (master 재정 A22 ② · 티켓 A23 1단계)
    #   ★왜 필요한가: 성경 통독표·암송표·퀴즈는 여기에 저장되는데 위 9종 밖이라
    #     ★번호표가 아예 안 나왔다 — 목사님이 폰에서 그 문서를 못 받으셨다.
    #   ★왜 안전한가: 이 폴더는 프로그램 폴더(_시스템)의 ★형제이지 상위가 아니다.
    #     그러니 교인 명부·설정·백업·스냅샷은 ★이 뿌리 안에 들어오지 않는다(위 9종과 같은 성질).
    #   ★★리터럴 경로를 박지 않는다 — `church.py` 의 `BIBLECAT()` 와 ★같은 규칙으로 런타임에 푼다.
    #     (아카이브루트가 있으면 그 밑, 없으면 프로그램 루트 밑 — 정본은 앞쪽, 시험대는 뒤쪽으로 갈린다.
    #      리터럴을 박으면 ★한쪽 환경에서 조용히 안 듣는다.)
    #   ★church.py 의 `BIBLECAT()` 을 고치면 ★여기도 같이 고쳐라(위 CAT() 주석과 같은 이유).
    try:
        ar=(_cfg_live() or {}).get("아카이브루트")
        _add(os.path.join(ar, "성경자료") if (ar and os.path.isdir(ar))
             else os.path.join(root, "성경자료"))
    except Exception: pass
    # ★A23-1 재정 §3-① — 엑셀 관리대장 폴더(`church.py` L1173 = `ROOT\_관리대장(Excel)`).
    #   ★`_시스템` 의 ★형제라 아래 ②겹(프로그램 폴더 하위 거부)에 ★걸리지 않는다 — 뿌리 한 줄이면 된다.
    _add(os.path.join(root, "_관리대장(Excel)"))
    # ★A23-1 재정 §2 — 악보 폴더. ★이것만은 `_시스템` ★안이라 뿌리에 넣는 것만으로는 부족하고
    #   `_dl_check` ②겹의 ★예외도 함께 있어야 한다(두 곳 다 좁게 — 재정 조건 2).
    _add(_songdir_rc())
    return out

def _dl_check(path):
    """이 경로를 내보내도 되는가. 되면 ★푼 실경로, 아니면 빈 문자열.
       ★번호표를 줄 때와 ★실제로 보낼 때 ★두 번 검사한다(그 사이에 파일이 바뀔 수 있다).

       ★검사는 4겹이다(하나가 뚫려도 나머지가 남게):
         ①확장자 화이트리스트 ②프로그램 폴더(_시스템) 하위는 ★무조건 거부
         ③허용 뿌리 안인지(realpath) ④보낼 때 다시 한 번."""
    try:
        rp=os.path.realpath(path)
        if not os.path.isfile(rp): return ""
        # ① 문서가 아닌 것은 어떤 뿌리에 있어도 못 나간다(.json .py .bak .db …)
        base_name=os.path.basename(rp)
        ext=base_name.rsplit(".",1)[-1].lower() if "." in base_name else ""
        rc=os.path.normcase(rp)
        if ext not in DL_EXT:
            # ★악보 형식은 ★악보 폴더 안에서만 통과시킨다 — 다른 뿌리에서는 종전 그대로 거부.
            #   ②③겹은 그대로 남는다: 교인 명부(.json)·소스(.py)·백업(.bak)은 여기에도 없다.
            _sd0=_songdir_rc()
            if not (ext in SHEET_EXT and _sd0 and (rc==_sd0 or rc.startswith(_sd0+os.sep))):
                return ""
        # ② ★프로그램 폴더 하위는 뿌리가 뭐라 하든 거부 —
        #    교인 명부(church_db.json)·설정(폰 비밀번호 해시)·소스·_백업·_피닉스(스냅샷 60개)가 다 여기 있다.
        basep=os.path.normcase(os.path.realpath(BASE))
        if rc==basep or rc.startswith(basep+os.sep):
            # ★★A23-1 재정 §2 — ★단 하나의 예외: 악보 폴더(`SONGDIR`).
            #
            # ★왜 예외가 필요한가: 악보는 `_시스템\_내자료\찬양곡` 에 저장된다. 이 ②겹이
            #   ★뿌리와 무관하게 막아 왔기 때문에 목사님이 심방지에서 악보를 못 보셨다.
            #
            # ★★왜 이 예외가 안전한가 (다음 사람에게 — ★이걸 근거로 예외를 ★넓히지 마라):
            #   ②를 열어도 ①(확장자 화이트리스트)과 ③(허용 뿌리)은 ★그대로 남는다.
            #   · 교인 명부 `church_db.json` · 설정 `church_config.json`(폰 비밀번호 해시·솔트)은
            #     ★`.json` 이라 ①이 막는다 — ②가 없어도 못 나간다.
            #   · 소스 `.py` · `.db` · `.bak` 도 ①에서 죽는다.
            #   ⇒ 이 예외의 실제 노출면은 **`_내자료\찬양곡` 안의 문서형 파일뿐**이고,
            #     그 폴더는 설계상 ★악보만 담는다(`church.py` `song_add` 가 거기에만 복사한다).
            #
            # ★★범위를 좁게 유지하는 두 장치 — ★고치지 마라:
            #   ⓐ `_songdir_rc()` 는 ★그 폴더 하나만 푼다. glob·패턴·목록이 ★아니다.
            #   ⓑ 비교에 ★`+os.sep` 를 붙인다. 이게 없으면 `찬양곡백업`·`찬양곡_old` 처럼
            #      ★접두사만 같은 형제 폴더가 통째로 뚫린다(startswith 함정).
            #      ★변이 검산으로 확인했다(2026-08-21): 구분자 가드를 빼면 `찬양곡백업` 이 ★실제로 뚫린다.
            #   ★`_백업\<시각>\_내자료\찬양곡\...` 은 경로가 달라(앞이 `_백업`) 여기 안 걸린다 — 계속 거부된다.
            _sd=_songdir_rc()
            if not (_sd and (rc==_sd or rc.startswith(_sd+os.sep))): return ""
        # ③ 허용 뿌리 안인가
        for r in _dl_roots():
            if rc==r or rc.startswith(r+os.sep): return rp
    except Exception: pass
    return ""

def _dl_reg(path, sess_key):
    """검사를 통과한 파일에만 번호표를 준다. 통과 못 하면 ★번호표 자체가 안 나온다."""
    rp=_dl_check(path)
    if not rp or not sess_key: return ""
    tid=secrets.token_urlsafe(18)
    now=time.time()
    with _DL_LOCK:
        for k,v in [(k,v) for k,v in _DL.items() if v[1]<=now]: _DL.pop(k,None)   # 만료분 청소
        if len(_DL)>=DL_MAX:
            for k,_ in sorted(_DL.items(), key=lambda kv: kv[1][1])[:max(1,len(_DL)-DL_MAX+1)]:
                _DL.pop(k,None)
        _DL[tid]=[rp, now+DL_TTL, sess_key, os.path.basename(rp)]
    return tid

def _dl_get(tid, sess_key):
    """번호표를 실경로로 바꾼다. ★남의 세션·만료·뿌리 밖은 전부 거절."""
    with _DL_LOCK: v=_DL.get(tid)
    if not v: return None, "이 문서는 더 이상 받을 수 없습니다. 카드를 다시 실행해 주세요."
    if v[1]<=time.time():
        with _DL_LOCK: _DL.pop(tid,None)
        return None, "받는 시간이 지났습니다(30분). 카드를 다시 실행해 주세요."
    if v[2]!=sess_key: return None, "이 문서를 받을 수 있는 기기가 아닙니다."
    if not _dl_check(v[0]): return None, "문서를 찾지 못했습니다. 카드를 다시 실행해 주세요."
    # ★번호표는 ★한 번만 쓴다 — 여기서 폐기한다(2026-08-20 · reviewer-codex 지적 · master 재정 A8).
    #   전에는 만료(위 30분)일 때만 지웠다. 그래서 같은 번호표로 30분 동안 몇 번이고 다시 받을 수 있었다.
    #   세션에 묶여 있어(위 v[2] 검사) 남이 주소만으로 받지는 못하지만, 폰을 잠깐 건네거나 브라우저를
    #   열어 둔 채 자리를 비우면 그 안에서 다시 받힌다. ★겹은 하나라도 더 있는 편이 낫다.
    #   ★다시 누르시면 어떻게 되나: 위 1924행이 "이 문서는 더 이상 받을 수 없습니다.
    #     카드를 다시 실행해 주세요." 라고 ★다음 행동까지 알려 드린다(막다른 길이 아니다).
    with _DL_LOCK: _DL.pop(tid,None)
    return v, ""


# ★폰에서 막는 명령. 지금은 ★비어 있다 — 2026-08-19 오너 결정으로 open-file·print-file 을
#   '막기'에서 '★문서를 내려받기'로 바꿨다(church.py 의 open_file·print_file 이 _openfile 을 탄다).
#   ★막는 것은 마지막 수단이다. 폰에서 뜻이 있는 일이면 되게 만들고, 정말 폰에서 할 수 없는 일
#   (폴더 열기·프로그램 종료)만 막는다 — 그 둘은 각자 제자리에서 막고 있다.
REMOTE_DENY=set()


def _srv_findpath(line):
    """줄에서 파일 경로를 찾는다 — ★화면 쪽 findPath() 와 ★같은 규칙이어야 한다.
       한쪽만 잡으면 폰에서 ★어떤 카드는 링크가 안 뜬다(그 카드만 반쪽이 된다).
       규칙: 아는 확장자 중 ★가장 뒤에 있는 것을 끝으로 잡고, 거기서 앞으로 훑어
             'X:' 처럼 ★드라이브 글자+콜론 이 나오는 자리를 시작으로 잡는다.
       ★church_web.py 화면 쪽 findPath 와 한 쌍이다 — 한쪽만 고치지 마라."""
    low=line.lower(); end=-1; el=0
    for e in ('.docx','.hwp','.hwpx','.xlsx','.pptx','.pdf','.txt'):
        q=low.rfind(e)
        # ★같은 자리에서 시작하면 ★긴 확장자가 이긴다 — .hwp 와 .hwpx 는 시작 위치가 같아서,
        #   먼저 검사된 .hwp 가 자리를 잡으면 .hwpx 의 x 가 잘려 나간다.
        #   잘린 경로는 존재하지 않으므로 ★그 문서만 조용히 안 받아진다(안전하게 실패하지만 반쪽이 된다).
        if q>=0 and (q>end or (q==end and len(e)>el)): end=q; el=len(e)
    if end<0: return ""
    end+=el; start=-1
    for j in range(end-1,0,-1):
        c=line[j]; pv=line[j-1]
        if c==':' and (('A'<=pv<='Z') or ('a'<=pv<='z')): start=j-1; break
    if start<0: return ""
    return line[start:end]

def _phone_line(ln):
    """폰 화면에 ★사무실 컴퓨터의 폴더 경로를 적지 않는다 — ★파일 이름만 남긴다.

       ★왜(2026-08-17 실측): 받기 단추 아래에
         `✅ 교인 증명원 발급(제 ○-2026-016 호): D:[역슬래시]○○교회[역슬래시]…[역슬래시]06 재정·증명[역슬래시][발급] 교인 증명원_….docx`
       가 그대로 떴다. 폰에서 이 경로는 ★뜻이 없다 — 목사님은 그 폴더를 열 수 없고,
       바로 위 받기 단추가 파일 이름을 ★이미 적어 준다. 남는 것은 읽기 어려운 긴 문자열과
       내부 폴더 구조뿐이다.
       ★단, 이 함수는 ★받기 단추가 생긴 줄에만 쓴다. 못 받는 문서는 경로를 ★그대로 두어야
         화면이 '사무실 컴퓨터에 저장되었습니다' 안내를 낼 수 있다(그 안내는 경로를 보고 만든다).
       ★PC 출력은 이 함수를 거치지 않는다 — 기능 후퇴 0."""
    out=ln
    for _ in range(4):                       # 한 줄에 경로가 여러 개일 수 있다
        p=_srv_findpath(out)
        if not p: break
        b=os.path.basename(p)
        if not b or b==p: break              # 이름만 있는 줄이면 더 줄일 것이 없다(무한반복 방지)
        out=out.replace(p, b)
    return out

def run_cmd(cmd, args, remote=False, sess=""):
    argv=[PYEXE, CHURCH_PY, cmd]
    for k,v in args.items(): argv+= ["--"+k, str(v)]
    env=dict(os.environ); env["PYTHONIOENCODING"]="utf-8"; env["CHURCH_WEB"]="1"
    # ★폰에서 부르신 것인지 자식(church.py)도 알아야 한다 — 폴더 열기처럼 ★내려받을 수 없는 동작은
    #   폰이면 아예 하지 않고 사실대로 알려야 하기 때문이다.
    if remote: env["CHURCH_REMOTE"]="1"
    tmo=600 if cmd in ("video-plan","video-render","nlm-add") else 120   # 영상·NLM 업로드는 시간이 더 걸림(큰 PDF 업로드·처리)상 대비)
    try:
        r=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=tmo,env=env,cwd=BASE)
        shown=[]; opened=0
        _dl_done=set()          # 같은 문서에 링크를 두 번 달지 않는다(마커와 본문 줄에 같은 경로가 온다)
        def _mk_get(path):
            """검사를 통과한 문서면 ▶받기 줄을 만든다. 이미 만든 문서면 None(중복 링크 방지)."""
            if not (remote and sess and path): return None
            rp=_dl_check(path)
            if not rp or rp in _dl_done: return None
            tid=_dl_reg(rp, sess)
            if not tid: return None
            _dl_done.add(rp)
            return "▶받기|%s|%s"%(tid, os.path.basename(rp))
        for ln in (r.stdout or "").split("\n"):     # 생성 파일은 부모(웹서버)가 확실히 연다
            if ln.startswith("__OPENFILE__"):
                _fp=ln[len("__OPENFILE__"):].strip()
                # ★폰에서 부르신 것이면 사무실 컴퓨터에서 파일을 ★열지 않는다 —
                #   심방지에서 카드를 누르셨는데 ★아무도 없는 사무실 화면에서 문서가 혼자 열린다.
                #   대신 ★그 자리에서 받으실 수 있게 번호표를 드린다.
                if remote:
                    g=_mk_get(_fp)
                    if g: shown.append(g)
                    elif not _dl_check(_fp):
                        # 받을 수 없는 파일일 때만 사실대로 알린다 —
                        # ★받기 링크를 옆에 두고 "사무실에 저장되었습니다"라고 하면 ★화면이 스스로 모순된 말을 한다.
                        # ★«만든 문서»라 하지 않는다 (2026-09-01) — 이 문장은 여러 카드가 함께 쓰는데,
                        #   악보 열기처럼 ★문서를 만들지 않는 카드도 여기로 온다.
                        #   ★두 경우 모두 참인 문장으로 바꾼다(사실 + 폰에서 못 받는다는 결과).
                        shown.append("  ※ 이 파일은 사무실 컴퓨터에 있습니다 — 폰으로는 받으실 수 없습니다.")
                else:
                    try: os.startfile(_fp); opened+=1
                    except Exception: pass
            elif remote and sess:
                # ★폰에서 부르신 것이면, ★서버가 여기서 경로를 찾아 검사하고 번호표로 바꾼다.
                #   ★화면(브라우저)에게 경로를 되돌려 달라고 하지 않는다 — 무엇을 받을지 화면이 정하면 안 된다.
                #   PC 출력은 이 분기에 들어오지 않으므로 ★지금 그대로다(기능 후퇴 0).
                mo=re.match(r'^▶열기\|(.+?)\|(.+)$', ln)
                if mo:
                    _t1=mo.group(1)
                    # ★A23-1 재정 §3-② — ★웹 주소는 «문서가 아니다». 문장만 바로잡는다(기능 무접촉).
                    #   ★무엇이 틀렸었나: `ask-ai` 는 ChatGPT·제미나이·클로드·뤼튼 ★링크 4줄을 내는데,
                    #     아래 문장이 그것을 *"사무실 컴퓨터에 저장되었습니다"* 라고 안내했다.
                    #     저장된 문서가 없는데 저장됐다고 말하니 ★목사님이 사무실에 가서 찾으신다.
                    #   ★고친 방식: 저장 여부를 말하지 않고 ★사실(인터넷 주소다)과 ★다음 행동(주소를 연다)을 준다.
                    if _t1.lower().startswith(("http://","https://")):
                        shown.append("  ※ %s — 인터넷 주소입니다(사무실 컴퓨터에 저장된 문서가 아닙니다)."%mo.group(2))
                        shown.append("     폰 브라우저 주소창에 넣어 여세요: %s"%_t1)
                        continue
                    g=_mk_get(_t1)
                    if g: shown.append(g)
                    elif not _dl_check(_t1):
                        # 번호표가 안 나오는 파일(문서 폴더 밖·문서 아닌 확장자)이면 ★죽은 단추를 만들지 않는다
                        shown.append("  ※ %s — 사무실 컴퓨터에 있습니다(폰으로는 받으실 수 없습니다)."%mo.group(2))
                    continue
                # ★경로를 지우기 ★전에 번호표를 만든다(지운 뒤엔 찾을 경로가 없다).
                _p=_srv_findpath(ln)
                g=_mk_get(_p)
                if g:
                    shown.append(_phone_line(ln))   # 받기 단추가 이름을 적어 주니 경로는 지운다
                    shown.append(g)
                elif _p and _dl_check(_p):
                    # ★받을 수 있는 문서인데 링크가 안 나온 경우 = 위에서 ★이미 단추를 만들었다
                    #   (__OPENFILE__ 마커와 본문 줄에 같은 경로가 온다 — _dl_done 이 중복을 막는다).
                    #   단추는 이미 있으니 여기서도 경로는 지운다. ★이 가지가 없으면
                    #   문서 카드의 ★가장 흔한 경우에서 경로가 그대로 남는다(2026-08-17 적발).
                    shown.append(_phone_line(ln))
                else:
                    shown.append(ln)                # ★못 받는 문서는 종전 그대로 —
                                                    #   화면이 이 경로를 보고 '사무실에 저장' 안내를 낸다
            else: shown.append(ln)
        _beep(r.returncode==0)
        if cmd=="setup" and r.returncode==0:
            # 교회 이름을 넣으셨으면 바탕화면 아이콘 이름도 바로 따라 바꾼다
            # (다음에 켜실 때까지 '○○교회 행정'으로 남아 있으면 안 된다)
            threading.Thread(target=_ensure_desktop_icon, daemon=True).start()
        body="\n".join(shown).rstrip()
        if r.returncode!=0:
            # ★영문 오류는 화면에 절대 붙이지 않는다(목사님이 당황하신다). 한국어 안내로 바꾼다.
            msg=_friendly_error(cmd, r.stderr or f"returncode={r.returncode}")
            return (body+"\n\n"+msg) if body else msg
        return body
    except subprocess.TimeoutExpired:
        _beep(False)
        return _friendly_error(cmd, "시간이 너무 오래 걸려 중단했습니다(timeout)")
    except Exception as e:
        _beep(False)
        return _friendly_error(cmd, repr(e))

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _send(self,body,ct="text/html; charset=utf-8",status=200,extra=None):
        b=body.encode('utf-8'); self.send_response(status)
        self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(b)))
        self.send_header("Cache-Control","no-store, must-revalidate")
        for k,v in (extra or []): self.send_header(k,v)
        self.end_headers(); self.wfile.write(b)
    # ── 📱 폰 접속 자물쇠 ──────────────────────────────────────────────
    def _login_page(self,err=""):
        """로그인 화면은 대시보드와 따로 만든다 — 아직 못 들어온 사람에게 카드 목록까지 보여줄 이유가 없다."""
        if _pw_rec():
            panel=LOGIN_PANEL.replace("__ERROR__",err).replace("__DAYS__",str(_sess_days()))
        else:
            panel=NOPW_PANEL
            if err: panel+=f'\n  <div class="msg">{err}</div>'   # 사유를 삼키지 않는다
        self._send(LOGIN_PAGE.replace("__CHURCH__",C.get("교회명","교회")).replace("__PANEL__",panel))
    def _kind(self):
        """이 요청의 세션 종류 — 'local'(이 컴퓨터) · 'remote'(폰) · None(아직 못 들어옴).
           ★들어와 있는 기기 목록을 위해 «방금 쓰였다»를 여기서 함께 적는다 —
             모든 요청이 이 문을 지나므로 여기 한 곳이면 빠짐없이 기록된다."""
        tok=_cookie_token(self.headers.get("Cookie"))
        v=_sess_get(tok)
        if v: _sess_touch(_tok_key(tok), self.headers.get("User-Agent"))
        return v[2] if v else None
    def _deny(self,msg,status=401):
        self._send(json.dumps({"ok":False,"error":msg},ensure_ascii=False),
                   "application/json; charset=utf-8",status)
    def _guard(self):
        """이 요청을 통과시켜도 되는가. 통과면 True.
           ★접속 주소로 통과를 결정하지 않는다 — 중계가 한 겹만 얹혀도 전원이 통과가 되기 때문이다.
             통과의 근거는 오직 ①유효한 세션 쿠키 ②기동 때 발급한 로컬 열쇠, 둘뿐이다."""
        # Host 검사는 아직 못 들어온 요청에도 먼저 한다 — 재바인딩은 로그인 화면부터 노린다.
        if (self.headers.get("Host") or "").strip().lower() not in _allowed_hosts():
            self._send("이 주소로는 열 수 없습니다.\n화면의 「📱 폰 접속 설정」 카드에 적힌 주소로 들어와 주세요.",
                       "text/plain; charset=utf-8",400); return False
        if _CFG_BROKEN[0]:      # 설정을 못 읽는 동안에는 아무도 통과시키지 않는다(조용한 실패 금지)
            if self.command=="GET" and self.path.split("?")[0]=="/": self._login_page(_CFG_BROKEN[0])
            else: self._deny(_CFG_BROKEN[0],503)
            return False
        path=self.path.split("?")[0]
        # ★자물쇠 «자체를 여는 문»들. /q 는 QR 1회용 열쇠로 들어오는 문이라 여기 있어야 한다
        #   (아직 세션이 없는 상태에서 오기 때문이다). 문 안쪽 검사는 _do_qr 이 한다.
        # ★열어 주는 문은 ★방식(GET/POST)까지 함께 본다 (2026-08-27 · reviewer-claude-1 지적 수리).
        #   종전에는 /logout 이 방식과 무관하게 통과였다. 그런데 do_GET 에는 /logout 갈래가 없어
        #   ★GET /logout 이 자물쇠를 지나 맨 아래 «대시보드 화면»까지 흘러갔다 —
        #   로그인하지 않은 사람에게 111,460자짜리 화면(교회명·담임·카드 전체 목록)이 나갔다.
        #   실측으로 재현했다. 자료(/stats)는 401 이었지만, ★안 나가야 할 것이 나간 것은 사실이다.
        #   ⇒ /logout 은 ★POST 로만 연다(화면 쪽도 POST 로 부른다). GET 은 아래에서 되돌려 보낸다.
        # ★/logout 은 ★POST 에서도 빼 둔다 (2026-08-27 · 「넓힌 자」가 잡았다).
        #   종전에는 POST 통과목록에 있어서 ★로그인하지 않은 요청에도 200 을 돌려줬다.
        #   실피해는 없었다(세션이 없으니 지울 것도 없다). 그러나 ★미인증 200 은 그 자체로
        #   «여기 무엇이 있다»를 알려 주는 신호이고, 통과목록은 좁을수록 좋다.
        #   ★로그인한 분의 나가기는 아래 _kind() 검사에서 그대로 통과한다 — 기능은 안 깨진다.
        #   ★이건 «찾던 것의 모양으로 자를 만들면 그 모양만 찾는다»(리뷰어 R2)의 실증이다:
        #     지난번 자는 «대시보드 화면이 나오는가»였고, 그 자로는 이 JSON 을 ★영영 못 봤다.
        # ★/appicon 은 자물쇠 밖에 둔다 (2026-08-29 · master 재정).
        #   ★근거: 아이콘은 파일이 아니라 ★코드가 그리는 초록 바탕 흰 십자가라
        #   ★교회명·교인정보가 한 글자도 없다 — 새어도 새는 것이 없다.
        #   ★왜 필요한가: 폰이 manifest 의 아이콘을 받아 갈 때 ★자격증명이 실리는지 확실치 않다.
        #   여기서 열어 두면 그 «모른다»를 기다리지 않아도 된다(불확실을 우회한다).
        #   ★manifest 자체는 ★열지 않는다 — 그 안에는 ★교회명(name·short_name)이 들어 있다.
        #   대신 화면 머리표에 crossorigin="use-credentials" 를 붙여 ★쿠키를 실어 보낸다.
        _open=("/login","/enter","/q","/appicon") if self.command=="GET" else ("/login",)
        if path in _open: return True
        if self._kind(): return True
        # 화면을 여는 것(/)이면 로그인 화면을 보여 주고, 자료를 가져가는 요청이면 401 로 답한다.
        # (자료 요청에 로그인 화면을 200 으로 돌려주면 화면 쪽이 그걸 자료로 알고 조용히 깨진다.)
        if self.command=="GET" and path=="/": self._login_page()
        else: self._deny("로그인이 필요합니다.")
        return False
    def _do_enter(self):
        """사무실 컴퓨터 자동 로그인 — 기동할 때 만든 열쇠를 가진 요청에만 세션을 심는다.
           열쇠는 이 프로그램이 브라우저를 열 때 주소에 담아 넘긴 값이라, 중계는 흉내낼 수 없다."""
        from urllib.parse import parse_qs, urlparse
        # ★이 문은 ★사무실 컴퓨터 소켓(127.0.0.1)에서만 열린다.
        #   폰 쪽 소켓도 같은 처리기를 쓰기 때문에, 이 한 줄이 없으면 사설망에 닿는 누구든
        #   ★비밀번호 없이 사무실 권한 로그인을 얻을 수 있다(열쇠만 알면).
        #   '중계 헤더가 있으면 거절'은 중계를 거친 요청만 잡는다 — 직결 요청은 그 헤더가 없다.
        #   그래서 그것만으로는 2겹이 아니라 한 겹이었다.
        if self.server.server_address[0]!="127.0.0.1":
            self._login_page(); return
        # ★2겹 방어 — 중계를 거쳐 온 요청에는 이 문을 열지 않는다.
        #   열쇠 자체가 이 컴퓨터에서만 얻어지지만, 중계가 붙은 구성이라면 그 전제가 흔들린다.
        if _via_proxy(self):
            self._login_page("중계(프록시)를 거친 접속에서는 자동 로그인을 하지 않습니다."); return
        # ★사람이 주소창으로 들어온 것만 받는다(화면 이동 요청). 페이지 속 스크립트가 몰래 부르는
        #   fetch·XHR·이미지 요청으로는 이 문을 열 수 없다 — 브라우저가 이 두 머리글을 대신 붙여 준다.
        #   (없으면 옛 브라우저다. 그때는 아래 loopback 조건으로만 받는다.)
        _m=(self.headers.get("Sec-Fetch-Mode") or "").lower()
        _d=(self.headers.get("Sec-Fetch-Dest") or "").lower()
        if (_m or _d) and not (_m=="navigate" and _d=="document"):
            self._login_page("주소창으로 직접 열어 주세요."); return
        if _CFG_BROKEN[0]:
            self._login_page(_CFG_BROKEN[0]); return
        global _LOCAL_KEY
        k=(parse_qs(urlparse(self.path).query).get('k',[''])[0])
        if not _LOCAL_KEY or not hmac.compare_digest(k,_LOCAL_KEY):
            # ★두 번째로 열린 것일 수 있다 — 탭 복원·새로고침·방문기록으로 같은 주소가 다시 열린다.
            #   ★오류 화면을 내지 않는다. 목사님이 ★당신 컴퓨터에서 오류를 보시면 안 된다.
            #   정상 로그인 화면 + '다시 여는 법'만 알려 드린다.
            self._login_page("이 주소는 ★한 번만 쓰입니다(안전을 위해 그렇게 만들었습니다). "
                             "검은 창에서 [Enter] 를 한 번 누르시면 새로 열어 드립니다 — "
                             "바탕화면 아이콘을 다시 누르셔도 됩니다."); return
        # ★열쇠를 ★여기서 버린다(1회용) — 방문기록·탭 복원으로 같은 주소가 다시 열려도 문이 되지 않는다.
        #   ★특히 브라우저 방문기록 동기화는 재기동 전에 그 주소를 클라우드로 올린다.
        _LOCAL_KEY=""
        t=_sess_new("local")
        self.send_response(302); self.send_header("Location","/")
        self.send_header("Set-Cookie",
                         f"{COOKIE_NAME}={t}; HttpOnly; SameSite=Lax; Path=/; "
                         f"Max-Age={_sess_days()*86400}{_cookie_attrs(self)}")
        self.send_header("Cache-Control","no-store, must-revalidate"); self.end_headers()
    def _do_qr(self):
        """📱 QR 로 들어오기 — 1회용 열쇠 하나로 비밀번호 없이 통과시킨다.
           ★위의 _do_enter(사무실 자동 로그인)와 ★같은 모양의 문이지만 조건이 다르다 —
             저 문은 127.0.0.1 에서만 열리고, 이 문은 ★폰 소켓에서 열린다(그게 이 문의 목적이다).
             그래서 대신 ★조건을 더 조인다:
               ㉮ 열쇠 수명 3분 ㉯ ★한 번 쓰면 죽는다 ㉰ 중계(프록시)를 거치면 거절
               ㉱ 주소창 이동(카메라가 여는 방식)만 받는다 — 남의 웹페이지 속 스크립트로는 못 연다
               ㉲ ★비밀번호가 아직 없으면 열지 않는다
           ★㉲ 에 대해 정확히 적는다 (2026-08-27 · reviewer-claude-1 지적 F-3 · 문장을 코드에 맞춘다):
             여기서 다시 확인하는 것은 ★비밀번호 유무 하나뿐이다. «폰 접속을 켜셨는가»(폰접속허용)는
             ★이 문에서 다시 보지 않는다. 그래서 «3중 자물쇠를 QR 이 우회하지 않는다»고 적었던
             종전 문장은 ★과장이었다 — 코드보다 앞서 나간 말이다.
             (실피해는 0 이다: 폰접속허용을 끄셔도 이미 열린 소켓을 닫는 코드가 없어 비밀번호
              로그인 문도 똑같이 열려 있다. 즉 QR 이 남보다 더 들어오는 것이 아니다.
              그러나 «피해가 없다»와 «문장이 맞다»는 다른 명제라, 문장을 낮춘다.)
           ★어긋나면 오류 화면이 아니라 ★비밀번호 화면으로 떨어진다(fail-closed).
             목사님은 그 자리에서 비밀번호를 넣어 그대로 들어가실 수 있다 — 막다른 길을 만들지 않는다."""
        from urllib.parse import parse_qs, urlparse
        if _via_proxy(self):
            self._login_page("중계(프록시)를 거친 접속에서는 QR 자동 로그인을 하지 않습니다."); return
        _m=(self.headers.get("Sec-Fetch-Mode") or "").lower()
        _d=(self.headers.get("Sec-Fetch-Dest") or "").lower()
        if (_m or _d) and not (_m=="navigate" and _d=="document"):
            self._login_page("QR 은 폰 카메라로 찍어 열어 주세요."); return
        if _CFG_BROKEN[0]:
            self._login_page(_CFG_BROKEN[0]); return
        if not _pw_rec():
            self._login_page(); return          # 비밀번호가 없으면 QR 도 통하지 않는다
        t=(parse_qs(urlparse(self.path).query).get('t',[''])[0])
        if not _qr_take(t):
            # ★사유를 삼키지 않는다. 다만 «틀렸다»가 아니라 «지났다»로 말한다 —
            #   대개는 공격이 아니라 ★새로고침·방문기록으로 같은 주소가 다시 열린 것이다.
            self._login_page("이 QR 은 ★한 번만 쓰이고 3분이 지나면 만료됩니다. "
                             "아래에 비밀번호를 넣어 들어오시거나, 사무실 컴퓨터 화면의 "
                             "「📱 폰으로 보기」에서 새 QR 을 띄워 주세요."); return
        tok=_sess_new("remote")
        # ★«?qr=1» 은 방금 QR 로 들어오셨다는 표시다 — 화면이 «이 폰을 기억했습니다»를 ★말하게 하려고 붙인다.
        #   QR 로그인은 예나 지금이나 30일 기억을 준다. 바뀐 것은 ★그 사실을 말하느냐뿐이다
        #   (기억은 하는데 목사님이 모르시면, 목사님은 «또 물어보겠지» 하고 QR 을 다시 찍으신다).
        self.send_response(302); self.send_header("Location","/?qr=1")
        self.send_header("Set-Cookie",
                         f"{COOKIE_NAME}={tok}; HttpOnly; SameSite=Lax; Path=/; "
                         f"Max-Age={_sess_days()*86400}{_cookie_attrs(self)}")
        self.send_header("Cache-Control","no-store, must-revalidate"); self.end_headers()
    def _do_qrinfo(self):
        """「📱 폰으로 보기」가 부르는 곳 — 지금 ★실제로 열려 있는 길마다 QR 을 한 장씩 만든다.
           ★사무실 컴퓨터(local)에서만 답한다. 폰에서 이걸 열어 또 다른 QR 을 뽑아
             남에게 건네는 길을 만들지 않는다(QR 은 «내 화면 앞에 있는 사람»에게만 준다).
           ★적는 주소는 _bind_plan 이 «열자»고 한 것이 아니라 _BOUND — ★정말로 열린 것이다.
             못 연 주소의 QR 은 찍어도 안 열리는 ★거짓말이 된다."""
        if self._kind()!="local":
            self._deny("이 기능은 사무실 컴퓨터 화면에서만 됩니다.",403); return
        # ★새 QR 을 만들기 ★전에 옛 열쇠를 먼저 죽인다 (R2-N1 · master 재정).
        #   「🔄 새 QR 만들기」가 이 문을 다시 두드리므로, 여기 한 줄이면 그 단추가 ★참이 된다 —
        #   목사님이 «새로 만들었으니 아까 것은 못 쓴다»고 믿으실 때 실제로 그렇게 된다.
        _qr_clear()
        cf=_cfg_live()
        out={"on":bool(cf.get("폰접속허용")),"haspw":bool(_pw_rec()),"port":PORT,"ways":[],"why":""}
        _h,_why,_ways=_bind_plan(); out["why"]=_why
        live=set(_BOUND)
        for ip,mode in _ways:
            if ip not in live: continue
            title,need,extra=_way_note(mode)
            url=f"http://{ip}:{PORT}/"
            try: svg=_qr_svg(url+"q?t="+_qr_new())
            except Exception: continue
            out["ways"].append({"mode":mode,"title":title,"need":need,"extra":extra,
                                "url":url,"svg":svg})
        if out["on"] and out["haspw"] and not out["ways"] and not out["why"]:
            out["why"]="폰 접속은 켜져 있지만 아직 소켓이 열리지 않았습니다 — 「📱 지금 켜기」를 눌러 주세요."
        self._send(json.dumps(out,ensure_ascii=False),"application/json; charset=utf-8")
    def _do_devices(self):
        """「지금 들어와 있는 기기」 — 목사님이 ★모르는 기기를 알아보시게 하는 창.
           ★사무실 컴퓨터(local)에서만 답한다. 주워 간 폰에서 이 목록을 열어
             목사님 기기를 골라 끊는 일이 없게 한다."""
        if self._kind()!="local":
            self._deny("들어와 있는 기기 목록은 사무실 컴퓨터에서만 보실 수 있습니다.",403); return
        me=_tok_key(_cookie_token(self.headers.get("Cookie")))
        rows=[dict(d, 이것이지금화면=(d["id"]==me)) for d in _sess_list()]
        self._send(json.dumps({"ok":True,"devices":rows,"now":time.time()},ensure_ascii=False),
                   "application/json; charset=utf-8")
    def _do_qrdrop(self):
        """화면의 QR 을 ★거두는 문 — 「닫기」·「3분 자동 가림」이 부른다.
           ★화면에서 사라지는 것과 ★열쇠가 죽는 것은 다른 일이다. 종전에는 앞의 것만 했다.
             그러면 목사님은 «치웠다»고 여기시는데 열쇠는 살아 있다 — 계기가 자기가 안 한 일을
             했다고 말하는 꼴이고, 그 거짓을 ★목사님이 겪으신다.
           ★사무실 컴퓨터에서만 받는다(QR 을 만드는 곳과 같은 문이라 같은 자물쇠를 건다)."""
        if self._kind()!="local":
            self._deny("이 기능은 사무실 컴퓨터 화면에서만 됩니다.",403); return
        n=_qr_clear()
        self._send(json.dumps({"ok":True,"dropped":n},ensure_ascii=False),
                   "application/json; charset=utf-8")
    def _do_devicedrop(self):
        """그 기기 하나만 끊기."""
        if self._kind()!="local":
            self._deny("기기를 끊는 것은 사무실 컴퓨터에서만 됩니다.",403); return
        try:
            n=int(self.headers.get('Content-Length',0) or 0)
            d=json.loads((self.rfile.read(n) if n else b"{}").decode('utf-8') or "{}")
            sid=str(d.get("id","")).strip()
        except Exception:
            sid=""
        me=_tok_key(_cookie_token(self.headers.get("Cookie")))
        if sid==me:
            # ★지금 보고 계신 화면을 끊지 않는다 — 끊으면 그 순간 목사님이 튕기시고,
            #   «모르는 기기를 끊으려다 내가 나가졌다»가 된다.
            self._deny("지금 보고 계신 이 화면입니다 — 이건 끊지 않습니다.",400); return
        ok=_sess_drop_id(sid)
        self._send(json.dumps({"ok":ok,"error":("" if ok else "이미 끊겼거나 없는 기기입니다.")},
                              ensure_ascii=False),"application/json; charset=utf-8")
    def _do_phoneon(self):
        """「📱 지금 켜기」 — 폰 접속을 ★이 자리에서 연다.
           ★설정 카드로 내쫓지 않는다: 화면을 옮겨 다니시게 하면 그것만으로 «세 번»이 깨진다.
           ★비밀번호가 없으면 자동으로 하나 만들어 드리고 ★그 자리에서 한 번 보여 드린다 —
             QR 이 안 읽힐 때 손으로 치실 길이 있어야 하기 때문이다.
           ★자물쇠를 여기에 새로 적지 않는다 — 여는 판단은 전부 _bind_plan/_phone_open_now 가 한다.
             조건을 두 곳에 적으면 언젠가 두 벌이 갈라지고, 갈라진 쪽이 느슨해진다."""
        if self._kind()!="local":
            self._deny("폰 접속을 켜는 것은 사무실 컴퓨터에서만 됩니다.",403); return
        if _CFG_BROKEN[0]:
            self._deny(_CFG_BROKEN[0],503); return
        newpw=""
        if not _pw_rec():
            newpw=_pw_suggest()
            if not _cfg_write({"폰비밀번호":_pw_make(newpw)}):
                self._deny("설정을 저장하지 못했습니다.",500); return
        # ★길을 ★한 번도 고르신 적이 없으면 「자동」으로 둔다 (2026-08-27 · 실측으로 잡은 결함).
        #   ★왜: 기본값은 「사설망」이다. 그런데 사설망(Tailscale)은 따로 깔아야 하는 것이라,
        #     ★처음 켜시는 분은 거의 다 안 깔려 있다. 그대로 두면 「지금 켜기」를 눌러도
        #     아무것도 안 열리고 «사설망이 아직 깔려 있지 않습니다» 만 보신다 —
        #     그러면 «누르기 한 번»이라는 약속이 그 자리에서 깨진다(시험대가 이걸 잡았다).
        #   ★이미 고르신 값은 ★건드리지 않는다. 기본값이 「사설망」인 본래 이유(업데이트만 했는데
        #     어느 날 갑자기 교회 와이파이에 로그인 화면이 열리면 안 된다)는 ★그대로 지켜진다 —
        #     여기서 바뀌는 것은 목사님이 ★직접 「지금 켜기」를 누르신 순간뿐이다.
        chose=""
        if not (_cfg_live().get("폰접속방식") or "").strip():
            if _cfg_write({"폰접속방식":"자동"}): chose="자동"
        if not _cfg_live().get("폰접속허용"):
            if not _cfg_write({"폰접속허용":True}):
                self._deny("설정을 저장하지 못했습니다.",500); return
        opened,why=_phone_open_now()
        self._send(json.dumps({"ok":bool(opened),"pw":newpw,"opened":opened,"way":chose,
                               "error":("" if opened else (why or "폰에서 들어오실 주소를 찾지 못했습니다."))},
                              ensure_ascii=False),"application/json; charset=utf-8")
    def _do_login(self):
        ip=self.client_address[0]
        # ★잠그지 않는다. 여러 번 틀렸으면 ★늦게 답할 뿐이다(오너 티켓 §1-4).
        #   여기서 미리 재우고 그 뒤에 정상 검사를 한다 — 그래서 맞는 비밀번호는 ★언제나 통과한다.
        _wait=_delay_for(ip)
        if _wait: time.sleep(_wait)
        if not _pw_rec():
            self._send(json.dumps({"ok":False,"error":"사무실 컴퓨터에서 먼저 비밀번호를 정해 주세요."},
                                  ensure_ascii=False),"application/json; charset=utf-8",403); return
        try:
            n=int(self.headers.get('Content-Length',0) or 0)
            d=json.loads((self.rfile.read(n) if n else b"{}").decode('utf-8') or "{}")
            pw=str(d.get("pw",""))
            # ★'이 폰 기억하기' — 없으면 켠 것으로 본다(옛 화면·자동화가 보낸 요청이 갑자기 짧아지지 않게)
            remember=bool(d.get("remember",True))
        except Exception:
            pw=""; remember=True
        if _pw_verify(pw):
            _fail_clear(ip)
            # ★기억하기 켬 = 30일(설정값) · 끔 = 브라우저를 닫으면 끝(쿠키에 만료를 안 적는다)
            #   ★쿠키 만료에만 기대지 않는다 — 서버도 12시간으로 끊는다(브라우저가 언제 닫혔는지는 서버가 모른다).
            t=_sess_new("remote", None if remember else NOREMEMBER_SEC)
            ck=(f"{COOKIE_NAME}={t}; HttpOnly; SameSite=Lax; Path=/; "
                +(f"Max-Age={_sess_days()*86400}" if remember else "")
                +_cookie_attrs(self))
            # ★Secure 는 _cookie_attrs 가 판단한다 — https 로 들어온 요청이면 붙이고, 아니면 뺀다.
            #   기본 경로(사설망 주소 직접 접속)는 http 라서 붙이면 쿠키가 저장되지 않아 로그인 자체가 막힌다.
            #   ★https 경로가 생기면 그때는 반드시 붙는다. 방식이 바뀌면 이 판단도 따라 바뀐다.
            self._send(json.dumps({"ok":True},ensure_ascii=False),"application/json; charset=utf-8",
                       200,[("Set-Cookie",ck)])
        else:
            time.sleep(FAIL_DELAY); _fail_mark(ip)
            nxt=_delay_for(ip)
            # ★지연 중임을 ★구별되는 문구로 알린다 — 안 그러면 "멈췄다"고 여기시고 앱을 지우신다.
            #   ★'잠겼다'고 쓰지 않는다. 실제로 잠기지 않았고, 맞는 비밀번호면 그대로 들어가진다.
            msg=(f"비밀번호가 맞지 않습니다. 여러 번 틀리셔서 다음 시도는 약 {nxt}초 뒤에 답합니다 — "
                 f"잠긴 것이 아니라 늦게 답하는 것입니다. 맞는 비밀번호를 넣으시면 그대로 들어가집니다."
                 if nxt else "비밀번호가 맞지 않습니다.")
            self._send(json.dumps({"ok":False,"error":msg,"delay":nxt},ensure_ascii=False),
                       "application/json; charset=utf-8",401)
    def _do_sessshort(self):
        """★«이 폰은 기억하지 않기» — 지금 이 기기의 열쇠 수명을 12시간으로 줄인다.
           ★새 권한을 만들지 않는다. 할 수 있는 일은 그대로이고 ★비밀번호를 다시 묻는 시점만 앞당긴다.
           ★폰(remote)에만 건다 — 사무실 화면은 이 문으로 짧아지지 않는다."""
        t=_cookie_token(self.headers.get("Cookie"))
        k=_tok_key(t); now=time.time()
        with _SESS_LOCK: v=_SESS.get(k)
        if not v or v[2]!="remote":
            self._send(json.dumps({"ok":False,"error":"폰에서만 됩니다."},ensure_ascii=False),
                       "application/json; charset=utf-8",400); return
        with _SESS_LOCK:
            v[4]=float(NOREMEMBER_SEC); v[0]=now+float(NOREMEMBER_SEC)
        _sess_save()
        self._send(json.dumps({"ok":True,"hours":int(NOREMEMBER_SEC//3600)},ensure_ascii=False),
                   "application/json; charset=utf-8")
    def _do_logout(self):
        _sess_drop(_cookie_token(self.headers.get("Cookie")))
        self._send(json.dumps({"ok":True},ensure_ascii=False),"application/json; charset=utf-8",
                   200,[("Set-Cookie",f"{COOKIE_NAME}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")])
    def do_GET(self):
        if not self._guard(): return
        _p0=self.path.split("?")[0]
        if _p0=="/enter": self._do_enter(); return
        if _p0=="/q": self._do_qr(); return
        if _p0=="/logout":
            # ★주소창에 /logout 을 치면 «나가기»가 아니라 ★화면으로 돌려보낸다.
            #   나가기는 화면의 단추(POST)로만 된다 — 링크 한 줄로 로그아웃되면
            #   남의 페이지에 그 링크를 심어 목사님을 심방 중에 튕겨낼 수 있다.
            self.send_response(302); self.send_header("Location","/")
            self.send_header("Cache-Control","no-store, must-revalidate"); self.end_headers(); return
        if _p0=="/qrinfo": self._do_qrinfo(); return
        if _p0=="/devices": self._do_devices(); return
        if _p0=="/manifest.webmanifest":
            # ★폰이 «앱처럼» 홈 화면에 두기 위해 읽는 쪽지. start_url 을 "/" 로 둔다 —
            #   QR 주소(1회용 열쇠가 붙은 주소)를 여기 적으면 아이콘이 ★죽은 열쇠를 물고 다닌다.
            self._send(json.dumps({
                "name":(C.get("교회명","교회")+" 교회행정"),"short_name":C.get("교회명","교회행정"),
                "start_url":"/","scope":"/","display":"standalone",
                "background_color":"#ffffff","theme_color":"#1F6E5A","lang":"ko",
                "icons":[{"src":"/appicon?s=192","sizes":"192x192","type":"image/png","purpose":"any"},
                         {"src":"/appicon?s=512","sizes":"512x512","type":"image/png","purpose":"any"}]},
                ensure_ascii=False),"application/manifest+json; charset=utf-8"); return
        if _p0=="/appicon":
            from urllib.parse import parse_qs, urlparse
            try: s=int((parse_qs(urlparse(self.path).query).get('s',['192'])[0]))
            except Exception: s=192
            s=max(48,min(512,s))            # ★바깥에서 온 숫자는 그대로 안 쓴다(큰 값을 넣어 굶기지 못하게)
            data=_app_icon(s)
            self.send_response(200); self.send_header("Content-Type","image/png")
            self.send_header("Content-Length",str(len(data)))
            self.send_header("Cache-Control","max-age=86400")
            self.end_headers(); self.wfile.write(data); return
        if _p0=="/login":
            if self._kind():
                self.send_response(302); self.send_header("Location","/"); self.end_headers(); return
            self._login_page(); return
        if self.path=="/stats":     # 대시보드 실데이터(JSON) — church.py dashboard 결과
            js="{}"
            try:
                env=dict(os.environ); env["PYTHONIOENCODING"]="utf-8"; env["CHURCH_WEB"]="1"
                r=subprocess.run([PYEXE,CHURCH_PY,"dashboard"],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,env=env,cwd=BASE)
                for ln in (r.stdout or "").split("\n"):
                    if ln.startswith("__DASH__"): js=ln[8:].strip(); break
            except Exception: pass
            self._send(js,"application/json; charset=utf-8"); return
        if self.path.startswith("/finance-stats"):   # 재정 통계(JSON) — ?year=YYYY · 그래프용
            from urllib.parse import parse_qs, urlparse
            yr=(parse_qs(urlparse(self.path).query).get('year',[''])[0])
            js="{}"
            try:
                env=dict(os.environ); env["PYTHONIOENCODING"]="utf-8"; env["CHURCH_WEB"]="1"
                argv=[PYEXE,CHURCH_PY,"finance-stats"]+(["--year",yr] if yr else [])
                r=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,env=env,cwd=BASE)
                for ln in (r.stdout or "").split("\n"):
                    if ln.startswith("__FSTATS__"): js=ln[10:].strip(); break
            except Exception: pass
            self._send(js,"application/json; charset=utf-8"); return
        if self.path.startswith("/events"):   # 일정 목록(JSON) — ?month=YYYY-MM
            from urllib.parse import parse_qs, urlparse
            mo=(parse_qs(urlparse(self.path).query).get('month',[''])[0])
            js="[]"
            try:
                env=dict(os.environ); env["PYTHONIOENCODING"]="utf-8"; env["CHURCH_WEB"]="1"
                argv=[PYEXE,CHURCH_PY,"events-json"]+(["--month",mo] if mo else [])
                r=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20,env=env,cwd=BASE)
                for ln in (r.stdout or "").split("\n"):
                    if ln.startswith("__EVT__"): js=ln[7:].strip(); break
            except Exception: pass
            self._send(js,"application/json; charset=utf-8"); return
        if self.path=="/bglist":          # 배경 사진 목록(_내자료/배경 폴더의 이미지)
            bgdir=os.path.join(BASE,"_내자료","배경"); files=[]
            if os.path.isdir(bgdir):
                for f in sorted(os.listdir(bgdir)):
                    if f.lower().endswith(('.jpg','.jpeg','.png','.webp','.gif')): files.append(f)
            self._send(json.dumps(files,ensure_ascii=False),"application/json; charset=utf-8"); return
        if self.path.startswith("/download"):
            # ★폰으로 문서 받기 — 주소에는 ★번호표만 들어온다(경로가 아니다).
            #   여기서 다시 한 번 뿌리를 검사한다 — 번호표를 준 뒤에 파일이 바뀌었을 수 있다.
            from urllib.parse import parse_qs, urlparse, quote
            tid=(parse_qs(urlparse(self.path).query).get('id',[''])[0])
            rec,err=_dl_get(tid, _tok_key(_cookie_token(self.headers.get("Cookie"))))
            if not rec:
                self._send(err or "받을 수 없습니다.","text/plain; charset=utf-8",404); return
            rp=rec[0]; fn=os.path.basename(rp)
            try: data=open(rp,'rb').read()
            except Exception:
                self._send("문서를 여는 중 문제가 생겼습니다. 카드를 다시 실행해 주세요.",
                           "text/plain; charset=utf-8",500); return
            ct=DL_MIME.get(fn.rsplit('.',1)[-1].lower() if '.' in fn else '', "application/octet-stream")
            # ★한글 파일명 — 이름이 깨지면 목사님이 그 파일을 폰에서 못 찾으신다.
            #   RFC5987(filename*)로 한글을 싣고, 못 읽는 옛 기기를 위해 ASCII 이름도 함께 적는다.
            ascii_fb=_ascii_name(fn)     # ★webkit(아이폰)은 이 이름으로 저장한다 — 뜻이 남아야 한다
            cd='attachment; filename="%s"; filename*=UTF-8\'\'%s' % (ascii_fb, quote(fn, safe=''))
            self.send_response(200)
            self.send_header("Content-Type",ct)
            self.send_header("Content-Length",str(len(data)))
            self.send_header("Content-Disposition",cd)
            self.send_header("Cache-Control","no-store, must-revalidate")
            self.end_headers(); self.wfile.write(data); return
        if self.path.startswith("/bg?"):  # 배경 사진 서빙(경로이탈 차단)
            from urllib.parse import parse_qs, urlparse
            fn=(parse_qs(urlparse(self.path).query).get('f',[''])[0])
            bgdir=os.path.normpath(os.path.join(BASE,"_내자료","배경")); fp=os.path.normpath(os.path.join(bgdir,fn))
            if (fp==bgdir or fp.startswith(bgdir+os.sep)) and os.path.isfile(fp):
                ct={'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','webp':'image/webp','gif':'image/gif'}.get(fp.rsplit('.',1)[-1].lower(),'application/octet-stream')
                data=open(fp,'rb').read()
                self.send_response(200); self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(data))); self.send_header("Cache-Control","max-age=3600"); self.end_headers(); self.wfile.write(data); return
            self.send_response(404); self.end_headers(); return
        if self.path=="/updatecheck":     # 새 업데이트 있는지 표시용(적용 안 함)
            js='{"new":false}'
            try:
                env=dict(os.environ); env["PYTHONIOENCODING"]="utf-8"; env["CHURCH_WEB"]="1"
                r=subprocess.run([PYEXE,CHURCH_PY,"update-check"],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15,env=env,cwd=BASE)
                for ln in (r.stdout or "").split("\n"):
                    if ln.startswith("__UPD__"): js=ln[7:].strip(); break
            except Exception: pass
            self._send(js,"application/json; charset=utf-8"); return
        page=(PAGE.replace("__CHURCH__",C.get("교회명","○○교회")).replace("__PASTOR__",C.get("담임","담임 목사"))
              .replace("__VERSION__",_engine_ver())
              # ★화면이 자기가 폰인지 알아야 한다 — 사무실에서만 되는 일(파일 열기)을
              #   폰에 단추로 띄우면 눌러도 아무 일이 없고, 그게 목사님께는 고장으로 보인다.
              .replace("__REMOTE__","true" if self._kind()!="local" else "false")
              # ★열쇠 수명은 서버가 단일 출처다 — 화면이 따로 적지 않게 여기서 실어 보낸다
              .replace("__QRTTL__",str(QR_TTL))
              .replace("__DAYS__",str(_sess_days()))   # ★QR 직후 «며칠 기억하는가» — 설정값과 화면이 어긋나지 않게
              .replace("__ACTIONS__",json.dumps(ACTIONS,ensure_ascii=False))
              .replace("__HIDDEN__",json.dumps((cfg() or {}).get("숨긴카드",[]),ensure_ascii=False)))
        self._send(page)
    def do_POST(self):
        # ★모든 POST 는 우리 화면에서 온 것인지 먼저 확인한다.
        #   이게 없으면 목사님이 아무 웹사이트나 방문하는 것만으로 그 사이트가 몰래
        #   이 프로그램에 명령을 보내 교인 자료를 건드릴 수 있다(사이트 간 요청 위조).
        if not _csrf_ok(self):
            self._deny("이 요청은 프로그램 화면에서 보낸 것이 아닙니다.",403); return
        if self.path=="/login":  self._do_login();  return
        # ★/logout 을 ★_guard 뒤로 옮겼다 (2026-08-27).
        #   ★여기가 진짜 문이었다: 통과목록에서 빼도 ★이 줄이 _guard 앞에 있으면 아무 소용이 없다.
        #     실제로 목록에서 먼저 뺐는데 미인증 200 이 ★그대로였고, 그제서야 순서를 봤다.
        #   ★교훈 — 「어디에 적혀 있는가」가 아니라 「어느 순서로 도는가」가 자물쇠다.
        #     («의도를 주석에 적는 것과 코드가 그대로 도는 것은 다른 명제»의 또 한 판이다)
        if not self._guard(): return
        if self.path=="/logout": self._do_logout(); return
        if self.path=="/phoneon": self._do_phoneon(); return
        if self.path=="/sessshort": self._do_sessshort(); return
        if self.path=="/devicedrop": self._do_devicedrop(); return
        if self.path=="/qrdrop": self._do_qrdrop(); return
        kind=self._kind()
        if self.path=="/shutdown":
            # ★폰에서는 끄지 못하게 한다 — 잘못 누르면 사무실 컴퓨터의 프로그램이 꺼져
            #   그때부터 폰에서도 아무것도 안 된다(스스로 다시 켤 방법이 없다).
            if kind!="local":
                self._deny("프로그램 종료는 사무실 컴퓨터에서만 됩니다.",403); return
            self._send("종료되었습니다","text/plain; charset=utf-8")
            import threading as _t
            _t.Timer(0.4, lambda: os._exit(0)).start(); return
        if self.path=="/bgupload":         # 배경 사진 업로드(프로그램 안에서 바로 추가)
            try:
                import base64 as _b64, re as _re
                n=int(self.headers.get('Content-Length',0) or 0)
                raw=self.rfile.read(n) if n else b"{}"
                d=json.loads(raw.decode('utf-8') or "{}")
                name=os.path.basename(str(d.get("name","사진.jpg")))
                name=_re.sub(r'[^\w.\- 가-힣]','_',name).strip() or "사진.jpg"      # 파일명 정화(경로·특수문자 제거)
                if not name.lower().endswith(('.jpg','.jpeg','.png','.webp','.gif')): name+=".jpg"
                b64=str(d.get("data",""))
                if "," in b64: b64=b64.split(",",1)[1]                              # dataURL 접두(data:image/...;base64,) 제거
                img=_b64.b64decode(b64)
                if len(img)>25*1024*1024: raise ValueError("사진이 너무 큽니다(25MB 이하로 넣어 주세요).")
                bgdir=os.path.normpath(os.path.join(BASE,"_내자료","배경")); os.makedirs(bgdir,exist_ok=True)
                fp=os.path.normpath(os.path.join(bgdir,name))
                if not (fp==bgdir or fp.startswith(bgdir+os.sep)): raise ValueError("잘못된 파일명입니다.")
                open(fp,'wb').write(img)
                self._send(json.dumps({"ok":True,"name":name},ensure_ascii=False),"application/json; charset=utf-8")
            except Exception as e:
                self._send(json.dumps({"ok":False,"error":str(e)[:120]},ensure_ascii=False),"application/json; charset=utf-8")
            return
        if self.path!="/run": self.send_response(404); self.end_headers(); return
        try:
            n=int(self.headers.get('Content-Length',0) or 0)
            raw=self.rfile.read(n) if n else b"{}"
            try: text=raw.decode('utf-8')
            except UnicodeDecodeError: text=raw.decode('cp949',errors='replace')
            data=json.loads(text or "{}")
            cmd=data.get("cmd","")
            if kind!="local" and cmd in REMOTE_DENY:
                self._deny("이 기능은 사무실 컴퓨터에서만 됩니다 — 폰에서 누르면 사무실 화면에서 열립니다.",403); return
            out=run_cmd(cmd, data.get("args",{}), remote=(kind!="local"),
                        sess=_tok_key(_cookie_token(self.headers.get("Cookie"))))
            if cmd=="update" and ("업데이트 완료" in out):
                out+="\n\n🔄 잠시 후 화면이 자동으로 새 버전으로 바뀝니다. (안 바뀌면 F5 또는 시작.bat 다시 실행)"
                import threading as _rt; _rt.Timer(1.6, _restart_self).start()
        except Exception as e:
            out="오류: "+str(e)
        self._send(out or "완료","text/plain; charset=utf-8")

class _Server(ThreadingHTTPServer):
    """폰이 연결을 끊는 것은 ★사고가 아니라 일상이다 — 그래서 사고로 적지 않는다.

       폰은 화면이 잠기거나 와이파이↔데이터가 바뀌거나 다른 앱으로 넘어갈 때마다
       받던 응답을 그냥 버리고 끊는다. 그때마다 파이썬 기본 서버는 트레이스백을
       ★한 건에 15줄씩 화면에 쏟는다. 실제로 시험대에서 한 번 도는 동안 814KB,
       1,600줄이 넘게 쌓였다(2026-08-18 실측). 문제가 셋이다 —
         ① ★진짜 오류가 그 더미에 묻힌다(다음 사람이 원인을 못 찾는다),
         ② 출력이 파이프를 채워 프로그램이 멈춰 보인다(시험 도구가 실제로 죽었다),
         ③ 목사님이 검은 창에 쏟아지는 영문 트레이스백을 보시고 고장으로 아신다.

       ★끊김만 삼키고 나머지는 그대로 올린다 — 조용해지자고 진짜 오류까지 덮으면
         그건 고친 게 아니라 눈을 가린 것이다."""
    def handle_error(self, request, client_address):
        import sys as _s
        if isinstance(_s.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return                                  # 상대가 먼저 끊었다 — 알릴 것이 없다
        super().handle_error(request, client_address)

def _free_port(port):
    """포트를 점유한 옛 서버를 PID로 강제 종료 — 이미지 이름과 무관하게 새 코드가 항상 뜨게 한다."""
    try:
        out=subprocess.run(["netstat","-ano"],capture_output=True,text=True,errors='replace').stdout
        killed=set()
        for line in out.splitlines():
            u=line.upper()
            if (f":{port} " in line or f":{port}\t" in line) and "LISTENING" in u:
                pid=line.split()[-1]
                if pid.isdigit() and int(pid)!=os.getpid() and pid not in killed:
                    subprocess.run(["taskkill","/F","/PID",pid],capture_output=True)
                    killed.add(pid)
        if killed:
            import time as _t; _t.sleep(1.0)
            print(f"  (옛 서버 {len(killed)}개 정리 후 새로 시작)")
    except Exception: pass

def _restart_self():
    """업데이트 후 서버를 새 코드로 재시작(시작.bat와 같은 방식) — 브라우저는 자동 새로고침으로 새 화면을 봄."""
    import subprocess, time
    env=dict(os.environ); env["CHURCH_NOOPEN"]="1"   # 재시작 시 새 브라우저 탭 열지 않음
    try:
        flags=0
        try: flags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
        except Exception: pass
        subprocess.Popen([PYEXE, os.path.abspath(__file__)], cwd=BASE, env=env, creationflags=flags, close_fds=True)
    except Exception:
        try: subprocess.Popen([PYEXE, os.path.abspath(__file__)], cwd=BASE, env=env)
        except Exception: pass
    time.sleep(1.2); os._exit(0)   # 새 서버가 포트를 넘겨받도록 잠시 후 종료
PW_ALPHABET="abcdefghjkmnpqrstuvwxyz23456789"   # ★혼동되는 글자(l·1·I·o·0)는 뺐다 — 폰에서 손으로 치신다

def _pw_suggest():
    """폰 접속 비밀번호를 자동으로 하나 만든다(8자).
       ★왜 자동인가 — 「지금 켜기」한 번으로 끝나야 하기 때문이다. 비밀번호를 지어내라고 하면
         그 자리에서 손이 멈추고, 대개 «1234» 같은 것이 된다.
       ★그래도 아주 짧게 하지 않는다: 8자 × 31글자 ≈ 40비트. 여기에 이미 있는 ★점증 지연
         (5회부터 1s→2s→…→60s)이 겹쳐 자동 대입은 사실상 불가능해진다.
       ★QR 로 들어가시면 이 비밀번호는 ★쓰이지 않는다 — QR 이 안 읽힐 때의 뒷문일 뿐이다."""
    return "".join(secrets.choice(PW_ALPHABET) for _ in range(8))

def _pw_make(pw):
    """비밀번호 → 저장용 기록. ★church.py 의 `_phone_hash()` 와 ★같은 모양이어야 한다 —
       한쪽만 고치면 저기서 정한 비밀번호를 여기서 못 알아보거나 그 반대가 된다.
       ★'세대'를 넣는 이유: 비밀번호를 바꾸면 이 숫자가 바뀌고, 그러면 폰 로그인이 전부 끊긴다
         (폰을 잃어버리셨을 때 목사님이 하실 수 있는 유일한 조치가 그것이다)."""
    it=240000; s=secrets.token_bytes(16).hex()
    v=hashlib.pbkdf2_hmac('sha256',(pw or "").encode('utf-8'),bytes.fromhex(s),it).hex()
    return {"알고리즘":"pbkdf2_sha256","반복":it,"솔트":s,"해시":v,
            "세대":time.time(),"설정시각":time.strftime("%Y-%m-%d %H:%M")}

def _phone_open_now():
    """폰 소켓을 ★지금 연다 — 껐다 켜지 않고. 돌려주는 값 = (연 주소 목록, 못 연 사유).
       ★왜 필요한가: 종전에는 «프로그램을 한 번 껐다 켜 주세요» 였다. 그러면 목사님이 하실 일이
         한 번 늘고, «📱 → QR → 홈 화면» 세 번이라는 약속이 그 자리에서 깨진다.
       ★자물쇠를 여기서 새로 판단하지 않는다 — 어느 주소를 열지는 ★_bind_plan() 이 정한다.
         그래야 기동할 때와 ★똑같은 자물쇠(폰접속 켬·비밀번호 있음·사설 대역)가 걸린다.
       ★공용 바인딩 금지는 여기서도 다시 본다 — 기동 경로에만 있으면 이 새 경로로 새어 나간다."""
    hosts,why,ways=_bind_plan()
    opened=[]
    for ip,mode in ways:
        if ip in FORBIDDEN_BIND:
            return [], "안전을 위해 열지 않았습니다(모든 주소에 여는 설정은 쓰지 않습니다)."
        if ip in _BOUND:
            opened.append(ip); continue                  # 이미 열려 있다
        try:
            s=_Server((ip,PORT),H)
        except OSError as e:
            why=why or (f"{ip} 주소로는 지금 열지 못했습니다 — 다른 프로그램이 쓰고 있거나 "
                        f"그 주소가 아직 이 컴퓨터에 없습니다({getattr(e,'errno','')}).")
            continue
        # ★순서가 중요하다 (2026-08-27 · reviewer-claude-1 「내가 못 본 축」 ②).
        #   _BOUND 는 Host 화이트리스트(_allowed_hosts)의 근거다. 스레드를 ★먼저 띄우면
        #   그 찰나에 들어온 첫 요청이 «이 주소로는 열 수 없습니다»(400)로 튕긴다 —
        #   목사님이 QR 을 바로 찍으시는 동선이라 그 찰나가 실제로 겹칠 수 있다.
        #   ⇒ ★받아들일 근거를 먼저 세우고, 그 다음에 문을 연다.
        #   (틀린 순서라도 «열어 놓고 안 받는» 쪽이라 안전 방향이었다. 그래도 헛걸음은 헛걸음이다.)
        _BOUND.append(ip)                                # ★Host 검사가 이 주소를 받아들이는 근거
        threading.Thread(target=s.serve_forever, daemon=True).start()
        opened.append(ip)
    return opened, why

def _enter_url_new():
    """★들어가는 주소를 ★새 열쇠로 만들어 돌려준다(쓸 때마다 새로).

       왜 매번 새로 만드나 — 열쇠는 ★한 번 쓰면 버린다(_do_enter 가 소비한다).
       그래서 '브라우저를 다시 열기'도 옛 주소를 재사용하면 안 되고 ★새 주소를 만들어야 한다.
       (옛 주소가 다시 통하면 '1회용'이 아니게 되고, 방문기록에 남은 주소가 계속 문이 된다.)"""
    global _LOCAL_KEY
    _LOCAL_KEY=secrets.token_urlsafe(24)
    return f"http://127.0.0.1:{PORT}/enter?k={_LOCAL_KEY}"

def _reopen_loop(enter_url):
    """이 창에서 [Enter] 를 누르시면 브라우저를 다시 열어 드린다.
       ★들어가는 열쇠를 화면에 찍지 않고도 복구할 수 있는 길이다 —
         열쇠는 이 프로그램의 기억에만 있고, 창에도 파일에도 남지 않는다.
       ★enter_url 이 함수면 부를 때마다 ★새 열쇠로 새 주소를 만든다(1회용 열쇠 대응)."""
    while True:
        try:
            if sys.stdin is None or not sys.stdin.readable(): return
            line = sys.stdin.readline()
            # ★EOF 면 여기서 끝낸다. readable() 은 "읽을 수 있는 종류인가"만 답하고 EOF 는 못 본다 —
            #   창 없이 뒤에서 띄우면 readline() 이 예외 없이 즉시 빈 줄을 돌려주므로, 이 줄이 없으면
            #   브라우저를 무한히 다시 여는 폭주가 난다(실측 373회·크롬 126개까지 증식).
            if line == "": return
        except Exception:
            return
        try:
            _u=enter_url() if callable(enter_url) else enter_url
            webbrowser.open(_u); print("  브라우저를 다시 열었습니다.")
        except Exception: print("  브라우저를 열지 못했습니다. 바탕화면 아이콘을 다시 눌러 주세요.")

def main():
    url=f"http://127.0.0.1:{PORT}/"
    _sess_load()                   # 폰이 이미 로그인해 두었으면 그대로 이어간다(재시작 후 재로그인 방지)
    try:   # 사진 배경 폴더 자동 준비 — 목사님이 여기에 사진을 넣으면 테마 패널에 나타남
        _bgd=os.path.join(BASE,"_내자료","배경"); os.makedirs(_bgd,exist_ok=True)
        _gid=os.path.join(_bgd,"여기에 배경 사진을 넣으세요.txt")
        if not os.path.exists(_gid):
            open(_gid,'w',encoding='utf-8').write(
                "화면 배경으로 쓸 사진을 넣는 폴더입니다.\n\n"
                "· 가장 쉬운 법: 프로그램 화면 오른쪽 위 ☀ 단추 → '내 사진 배경'의\n"
                "  '＋ 사진 추가' 버튼을 누르면, 이 폴더를 열지 않고도 바로 올릴 수 있습니다.\n"
                "· 또는 이 폴더에 사진(jpg·png)을 직접 넣어도 '내 사진 배경'에 나타납니다.\n\n"
                "· 가족·자녀 사진, 교회 전경, 좋아하시는 풍경 등 무엇이든 좋습니다.\n"
                "· 가로로 넓은 사진(1600px 이상)이 화면에 예쁘게 채워집니다.\n"
                "· 글자가 잘 보이도록 사진 위에 은은한 막을 자동으로 씌워 드립니다.")
    except Exception: pass
    enter=_enter_url_new()   # 이 컴퓨터용 열쇠로 만든 ★1회용 주소(메모리에만 둔다 · 쓰면 버린다)
    _hosts,_why,_ways=_bind_plan()   # ★_ways = [(주소, 길)] — 「자동」이면 ★둘 다 들어 있다
    _mode_of=dict(_ways)             # 주소 → 길. 안내문이 길마다 ★정반대라 짝을 잃으면 안 된다
    _phone_on=len(_hosts)>1
    if _cfg_live().get("폰접속허용") and _why:
        print(f"  ※ 폰 접속을 켜 두셨지만 아직 열지 못했습니다 — {_why}")
    # ★여기서 무조건 옛 서버를 정리하지 않는다 — 포트가 비어 있어도 남의 프로그램을 찾아
    #   죽이러 나서기 때문이다. 아래 :바인딩 실패 때만(그것도 포트 점유일 때만) 정리한다.
    #   127.0.0.1 은 항상 첫 순서라, 옛 서버가 물고 있으면 거기서 잡혀 결국 정리된다
    #   ⇒ "항상 최신 코드로 기동"은 그대로 지켜지고, 달라지는 것은 ★포트가 비었을 때
    #     아무도 건드리지 않는다는 것뿐이다.
    # ★주소마다 소켓을 따로 연다. 127.0.0.1 은 사무실 컴퓨터 몫이라 늘 열고,
    #   사설망 주소는 조건이 맞을 때만 연다. 공용 바인딩(0.0.0.0)을 쓰지 않으므로
    #   공유기(랜) 쪽에는 어떤 경우에도 나타나지 않는다.
    import errno as _errno
    # ★기동 때 한 번 더 확인한다 — 나중에 누가 "폰에서 안 보인다"며 여기에 0.0.0.0 을 넣으면
    #   교회 와이파이에 8899 가 열리고, 거기엔 사설망 암호가 없어 ★로그인 비밀번호가 그대로 흐른다.
    for _h in _hosts:
        if _h in FORBIDDEN_BIND:
            print("■ 안전을 위해 시작하지 않았습니다 — 모든 주소에 여는 설정이 들어 있습니다.")
            print("   담당자에게 이 화면을 알려 주세요(공용 바인딩 금지).")
            return
    servers=[]
    for _h in _hosts:
        for _try in range(3):
            try:
                servers.append(_Server((_h,PORT),H)); break  # 멀티태스킹(동시 처리) · 폰 끊김은 사고로 적지 않는다
            except OSError as _e:
                # ★'포트를 누가 쓰고 있다'와 '그 주소가 이 컴퓨터에 없다'는 ★다른 사고다.
                #   주소가 없는 것(사설망이 아직 안 떴을 때)인데 포트 점유로 오해하면,
                #   그 포트를 쓰던 ★무관한 프로그램을 죽인다. 주인님이 쓰시는 프로그램일 수 있다.
                if getattr(_e,"errno",None) in (_errno.EADDRNOTAVAIL, _errno.EAFNOSUPPORT):
                    print(f"  ※ {_h} 주소가 아직 이 컴퓨터에 없습니다(사설망이 안 떴을 수 있습니다) — 이 주소는 건너뜁니다.")
                    break                      # ★아무것도 죽이지 않고 이 소켓만 포기한다
                if _h=="127.0.0.1": _free_port(PORT)   # 포트 점유일 때만 옛 서버 정리
                import time as _t; _t.sleep(1.0)
        else:
            print(f"  ※ {_h} 주소로는 열지 못했습니다(다른 프로그램이 쓰는 중일 수 있습니다).")
    if not servers:
        print("포트를 열 수 없습니다. 브라우저만 엽니다..."); webbrowser.open(url); return
    # ★실제로 열린 주소만 허용 목록에 넣는다 — 못 연 주소를 남겨 두면
    #   바인딩하지도 않은 주소를 Host 검사가 계속 통과시킨다.
    _BOUND[:] = [s.server_address[0] for s in servers]
    _phone_on = any(h!="127.0.0.1" for h in _BOUND)   # 폰 소켓이 실제로 열렸을 때만 열렸다고 말한다
    # 바탕화면 아이콘은 뒤에서 조용히 챙긴다 — 아이콘 만드느라 프로그램이 늦게 뜨면 안 된다.
    threading.Thread(target=_ensure_desktop_icon, daemon=True).start()
    print(f"■ {C.get('교회명','')} 교회행정 웹 대시보드 실행 중 → {url}")
    if _phone_on:
        # ★안내문은 ★길마다 2벌이다 (2026-08-27 · 오너 결정 «와이파이 먼저, 밖은 사설망»).
        #   같은 문장을 쓰면 둘 중 하나는 반드시 거짓이 된다 —
        #   사설망은 «밖에서도», 와이파이는 «그 와이파이 안에서만» 이다.
        # ★주소가 둘이면 ★둘 다 적는다(2026-08-27). 하나만 적으면 나머지 하나는
        #   ★열려 있는데 아무도 모르는 문이 된다.
        print("  📱 폰에서도 보실 수 있게 열려 있습니다(비밀번호 필요)")
        for _pip in [h for h in _BOUND if h!="127.0.0.1"]:
            _m=_mode_of.get(_pip,""); _lab=_phone_way_label(_m)
            print(f"     → http://{_pip}:{PORT}/")
            if _m=="wifi":
                print(f"        열린 길: {_lab} — ★교회·집의 ★같은 와이파이에 연결된 폰에서만 열립니다(밖에서는 안 됩니다).")
                print("        폰이 그 와이파이에 붙어 있는지 먼저 확인해 주세요. 따로 설치하실 것은 없습니다.")
            elif _m=="vpn":
                print(f"        열린 길: {_lab} — ★밖에서도(심방지·이동 중) 열립니다. 폰에도 사설망이 연결돼 있어야 합니다.")
        print("     ★가장 쉬운 길: 화면 위의 「📱 폰으로 보기」를 누르시면 QR 이 뜹니다 —")
        print("       폰 카메라로 비추기만 하면 비밀번호 없이 열립니다.")
    for s in servers[1:]:          # 사설망 소켓은 뒤에서 돌린다
        threading.Thread(target=s.serve_forever, daemon=True).start()
    if not os.environ.get("CHURCH_NOOPEN"):   # 업데이트 자동 재시작 시엔 새 탭 안 엶(F5로 갱신)
        print("  브라우저가 자동으로 열립니다. 종료: 이 창을 닫으세요.")
        # ★들어가는 열쇠는 화면에 찍지 않는다. 이 창의 글자는 목사님이 사진으로 찍어 보내시거나
        #   기록 파일에 섞여 나갈 수 있다. 안 열렸으면 ★이 프로그램이 다시 열어 드린다.
        print("  (브라우저가 안 열렸으면 이 창에서 [Enter] 를 한 번 눌러 주세요 — 다시 열어 드립니다)")
        threading.Timer(1.0, lambda: webbrowser.open(enter)).start()
        # ★[Enter] 로 다시 열 때는 ★새 열쇠로 새 주소를 만든다 — 처음 주소는 한 번 쓰면 죽는다.
        threading.Thread(target=_reopen_loop, args=(_enter_url_new,), daemon=True).start()
    httpd=servers[0]
    try: httpd.serve_forever()
    except KeyboardInterrupt: print("\n종료합니다.")

if __name__=="__main__": main()
