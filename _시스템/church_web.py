# -*- coding: utf-8 -*-
"""교회 종합행정시스템 — 웹 대시보드(모던 UI). 브라우저에서 카드로 사용.
실행: python church_web.py  → 자동으로 브라우저 열림(localhost). church.py를 그대로 구동."""
import os, sys, json, subprocess, threading, webbrowser, re
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

ACTIONS=[
 # group, cmd, title, icon, fields[(name,label,placeholder,required)]
 ("목양","member-add","교우 등록 & 조회","🙌",[("name","이름","",1),("role","직분","",0),("cell","소속셀","",0),("tel","연락처","",0),("addr","주소","",0),("birth","생년월일","",0),("family","가족(이름:관계 ; 로 구분 · 예: 김영희:배우자; 홍철수:자녀)","",0)],"이름만 넣고 실행하면 → 이미 등록된 교인이면 정보·가족을 조회해 보여줍니다. 새 이름이면 → 나머지 칸(직분·연락처·가족 등)을 채워 실행해 등록합니다. 한 카드로 등록과 조회를 다 합니다."),
 ("목양","member-transfer","교적 이동(전입·전출·이명) + 대장","↔️",[("kind","종류(전입/전출/이명)","전출",0),("name","이름 (비우면 대장만 봅니다)","",0),("date","날짜","",0),("church","상대 교회","",0),("memo","사유","",0)],"이름을 넣으면 전입·전출·이명을 기록하고 교인 상태를 갱신하며, 항상 '교적 이동 대장'을 함께 출력합니다. 이름을 비우면 대장만 봅니다. 이명증서는 '증명서 발급'에서."),
 ("목양","visit-add","심방 기록 & 브리핑","📝",[("name","이름","",1),("kind","구분(정기/춘계대심방/추계대심방/입원/새가족/구역)","정기",0),("word","전한 말씀(다녀와서 기록)","",0),("prayer","기도제목(;로 구분)","",0),("note","나눈 내용","",0),("followup","후속","",0)],"이름만 넣고 실행하면 → 지난 말씀·기도제목 브리핑(반복 방지). 심방 다녀와서 '전한 말씀·기도제목·나눈 내용'을 채워 실행하면 → 기록됩니다. 한 카드로 심방 전·후를 다 챙깁니다."),
 ("목양","visit-daesim","춘계·추계 대심방 현황","🏘️",[("year","연도","2026",0)],"올해 대심방(전교인 심방)의 완료·미완료 세대와 진행률을 한 장으로 — 대심방 기간에 빠짐없이 챙기게."),
 ("목양","ref-visit","심방 지침(상황별) 📖","🧭",[]),
 ("목양","newfamily-add","새가족 등록","🌱",[("name","이름","",1),("tel","연락처","",0),("leader","인도자","",0),("cell","소속셀","",0)]),
 ("목양","newfamily-board","새가족 정착 현황","📊",[]),
 ("목양","care","돌봄 필요 성도","💗",[("days","기준일수","90",0)]),
 ("목양","weekly-brief","주간 목회 브리핑","🗞️",[]),
 ("목양","birthday","🎂 생일·결혼기념일 축하","🎂",[("days","며칠 이내를 볼까요? (오늘만 보려면 0)","7",0)],"다가오는 생일·결혼기념일을 미리 확인하고, 당일에 보낼 축하 카톡을 함께 만들어 드립니다('오늘'로 표시). 100가지 문구가 매년 다르게 자동 선택되고, 지난 축하도 보여드려 겹치지 않아요."),
 ("목양","careevent-add","축하·위로 문자 (상황별·경조사 통합) 🎉","🎉",[("kind","상황(취업·이사·합격·군입대·출산… / 경조사: 결혼·장례·출생·회갑·입원)","",1),("name","대상 이름","",1),("jik","호칭·직분(형제/집사 등)","",0),("date","날짜(결혼→기념일 자동연동)","",0),("amount","경조금(경조사만·기록됨)","",0),("note","내용·메모(경조사 기록용)","",0)],"상황이나 사건을 넣으면 골라 쓸 축하·위로 카톡 문구를 만들어 드립니다. 취업·이사·합격 등 상황별은 3문구, 결혼·장례·출생 등 경조사는 문자+경조금 기록·심방 연동까지. 생일·결혼기념일은 옆의 '생일·결혼기념일 축하' 카드가 자동으로 챙깁니다."),
 ("목양","cell-worship","구역·속회 예배 순서지","🏠",[("title","제목","구역예배",0),("text","본문","",0),("date","날짜","",0),("leader","인도(구역장)","",0)],"구역·속회 예배 순서 + 나눔 질문 + 기도제목 기입란. 구역장이 인도용으로 출력합니다."),
 ("목양","group-add","소그룹(셀) 등록","🧩",[("name","소그룹명","",1),("leader","리더","",0),("day","모임요일","",0),("place","장소","",0)]),
 ("목양","group-report","셀 주간보고","🗒️",[("name","소그룹명","",1),("attend","참석","",0),("note","나눔","",0),("absent","결석자","",0)]),
 ("목양","group-form","셀 보고서 양식(인쇄)","🖨️",[("name","소그룹명","",0)]),
 ("목양","train-add","양육·제자훈련 기록","🎓",[("name","교인","",1),("course","과정","제자훈련",0),("stage","단계","",0),("status","상태(진행/수료)","진행",0)]),
 ("목양","ref-conflict","성도·당회 갈등 관리 📖","🕊️",[]),
 ("목양","ref-ceremony","예식서(순서·기도문) 📖","📜",[]),
 ("목양","ref-prayer","대표기도문·상황별 📖","🙏",[]),
 ("성경자료","ref-bstudy","성경공부 인도 📖","📖",[]),
 ("영성","ref-spirit","목회자 영성·자기돌봄 📖","✝️",[]),
 ("예배·설교","sermon","설교 초안 작성","✍️",[("title","제목","",1),("text","본문","요3:16",0),("service","예배유형","주일오전예배/새벽기도회/수요예배/목요집회/금요기도회/주일오후예배/중고등부/초등부",0),("theme","주제","믿음 은혜",0),("points","대지(;로 구분)","",0),("series","시리즈","",0)]),
 ("예배·설교","sermon-files","지난 설교 (목록·열기·검색)","📚",[("open","설교 제목 (비우면 전체 목록·눌러 열기)","",0),("query","이력 검색어(본문/제목)","",0),("service","예배유형(검색 필터)","",0)],"지난 설교 파일을 봅니다 — 비우면 전체 목록(눌러 열기), 제목을 넣으면 그 파일 열기, '검색어'로 설교 이력(본문·제목)에서 찾기."),
 ("예배·설교","sermon-reuse","지난 설교 재활용 (새 초안 작성)","♻️",[("query","지난설교 검색(본문/제목)","",1),("title","새 제목(비우면 동일)","",0),("service","예배유형","",0)],"지난 설교(본문·제목으로 검색)를 바탕으로 새 설교 초안을 작성합니다 — 재묵상·재작성에 좋습니다."),
 ("예배·설교","bulletin","주보 만들기","📰",[("sermon","설교 제목","",0),("notice","교회소식(;로 구분)","",0),("week","주간일정(;로 구분)","",0)]),
 ("예배·설교","devotion","오늘의 묵상 (말씀카드·해설·질문 자동) 🕊️","🕊️",[("title","제목","",1),("text","★성경구절을 넣어보세요 (예: 엡 2:19-22)","",0),("theme","주제(사랑·믿음·공동체·시련·감사·기도·순종·은혜·소망·회개·사명·평안 / 비우면 자동)","",0),("verse","본문 말씀 — 목사님이 직접 입력(저작권 안전)","",0),("body","묵상/해설(비우면 주제 참고문장 자동 제안)","",0),("apply","오늘의 적용","",0),("pray","기도","",0)],"★성경구절을 넣으면 이쁜 말씀카드 그림 + 간단한 해설·적용·질문이 자동으로. 성도들께 카톡으로 보내면 은혜가 됩니다."),
 ("행정서식","cert","증명서·상장 발급 & 대장","📜",[("name","이름 (비우면 발급대장 보기)","",0),("kind","종류(교인/세례/재적/출석/이명/헌금/재직/수료/임명/위촉)","교인",0),("role","직분·과정(재직/수료/임명/위촉 시)","",0),("term","임기·재직기간","",0),("purpose","용도·근거","",0)],"이름을 넣으면 증명서·상장을 발급하고(문서번호 자동·대장 자동기록), 이름을 비우면 지금까지 발급한 내역(발급대장)을 봅니다. 한 카드로 발급과 대장을 다 합니다."),
 ("성례","sacrament-add","성례 등록 & 대장 (세례·학습·입교)","💧",[("name","이름 (비우면 성례대장 보기)","",0),("kind","종류(유아세례/세례/학습/입교)","세례",0),("birth","생년월일","",0),("addr","주소","",0),("date","성례일","",0),("by","집례자(비우면 담임)","",0),("memo","비고","",0)],"이름을 넣으면 성례(세례·학습·입교·유아세례)를 대장에 등록하고, 이름을 비우면 성례대장 전체를 봅니다. 진학용 세례증명의 근거."),
 ("성례","sacrament-apply","성례 서식 (신청서·증명서 발급)","📝",[("mode","무엇을? (신청서 / 증명서 · 비우면 신청서)","",0),("name","이름","",0),("kind","종류(유아세례/세례/학습/입교)","세례",0),("birth","생년월일","",0),("addr","주소","",0),("tel","연락처","",0),("cell","소속 셀·부서","",0),("leader","추천 인도자","",0),("purpose","용도(증명서·예: 진학)","",0)],"'신청서'는 당회 제출용 성례 신청서 서식, '증명서'는 세례교인 증명서를 발급합니다. 이름을 넣으면 채워서, 비우면 빈 양식으로."),
 ("성경자료","bible","성경 찾기 (KJV·WEB)","📖",[("ref","찾을 곳(예: 요한복음 3:16 · 요 3장 · 요 3:16-18)","요한복음 3:16",1),("version","역본(kjv/web)","web",0)],"성경 본문을 찾아봅니다(KJV·WEB 영어 역본). 장 전체·범위·약칭 다 인식합니다."),
 ("성경자료","bible-plan","성경 통독표","📖",[("type","유형(1년/90일/맥체인)","1년",0),("date","시작일(YYYY-MM-DD·비우면 오늘)","",0),("dept","부서(선택)","",0)]),
 ("성경자료","bible-quiz","성경 퀴즈","📝",[("ref","범위(예: 요한복음 3)","요한복음 3",1),("type","유형(빈칸/사지선다/성구찾기)","빈칸",0),("count","문항수","10",0),("version","역본(비우면 자동: 개역개정 있으면 한국어·없으면 주소중심 / web·kjv 지정가능)","",0),("level","난이도(초/중/고)","",0),("dept","부서","",0)]),
 ("성경자료","memory-verse","성경 암송표·카드","💳",[("refs","성구들(;로 구분·예: 요한복음 3:16; 로마서 8:28)","",1),("set","세트명(예: 구원/절기/부서)","암송",0),("version","역본(비우면 자동: 개역개정 있으면 한국어·없으면 주소중심 / web·kjv 지정가능)","",0),("dept","부서","",0)]),
 ("성경자료","ref-bible","성경교육 자료 📖","📖",[],"성경을 어떻게 가르칠까 — 연령별 성경교육 원리·교수법·커리큘럼 참고자료(전 부서 공용)."),
 ("찬양","ref-wor","찬양·예배음악 📖","🎶",[]),
 ("전도","ref-ev","전도·새신자 📖","🌱",[]),
 ("목회 참고자료","ref-dis","제직·제자훈련 📖","🎓",[]),
 ("목회 참고자료","ref-laity","평신도 사역·사역자 세우기 📖","🙋",[]),
 ("목회 참고자료","ref-fam","가정·결혼·상담 📖","💒",[]),
 ("목회 참고자료","ref-counsel","성경적 상담 실전 가이드 📖","🕊️",[]),
 ("행정서식","ref-adm","교회행정·재정 📖","🗂️",[]),
 ("전도","ref-newbeliever","새신자 교육 4주 프로그램 📖","🌱",[],"새가족을 4주간 양육하는 실전 교재 — 주차별 인도안·나눔질문·부록 양식 A~F."),
 ("전도","vip-add","태신자(전도대상) 등록","🌟",[("name","이름","",1),("sponsor","담당 성도","",0),("tel","연락처","",0)],"전도할 태신자(아직 교회에 안 나오는 전도 대상자)를 담당 성도와 함께 등록·관리합니다. 새생명축제(초청잔치)에 초청할 명단이 됩니다."),
 ("전도","ref-harvest","준비 가이드(태신자운동~후속) 📖","🌾",[],"태신자 운동~새생명 초청잔치까지 D-56~후속 타임라인·초청카드 서식·부록 12종 전체 가이드."),
 ("전도","harvest-plan","준비 타임라인 (축제일 D-day)","🗓️",[("title","축제명","새생명 초청잔치",0),("dday","축제일(YYYY-MM-DD)","",0)],"축제일을 넣으면 D-56~D+28 월·일별 준비사항을 날짜까지 자동 계산해 체크리스트로 만들어 드립니다."),
 ("전도","harvest-checklist","당일 진행 체크리스트","✅",[("title","축제명","새생명 초청잔치",0),("date","날짜","",0)],"축제 당일 시간대·역할별 진행 점검표(세팅~맞이~예배·초청~배웅~정리)."),
 ("예배·설교","ref-season","교회 절기 사역 준비 📖","🕯️",[],"대강절·성탄·고난주간·부활절·맥추·추수감사 등 11절기 — 준비 타임라인·예배순서·기도문·행사 아이디어."),
 ("목회 참고자료","ref-cult","이단 분별·대처 (성도 보호) 📖","🛡️",[],"지능화된 이단 포교로부터 성도를 지키는 실전 분별서 — 판별 기준(삼위일체·성경권위·구원관)·주요 이단 교리·최신 포교수법(문화센터·SNS·추수꾼)·분별 체크리스트 24개·상담과 돌봄. 정죄가 아닌 분별과 긍휼."),
 ("다음세대(주일학교)","student-add","학생 등록(청소년·청년)","🎒",[("name","이름","",1),("school","학교","",0),("grade","학년","",0),("dept","부서","중고등부",0),("tel","연락처","",0),("guardian","보호자","",0),("gtel","보호자연락처","",0)]),
 ("다음세대(주일학교)","student-list","학생 명단(부서별)","📋",[("dept","부서(비우면 전체)","",0),("grade","학년","",0)]),
 ("다음세대(주일학교)","lesson","공과·교안 만들기","📝",[("title","제목","",1),("target","대상(부서·학년)","중고등부",0),("text","본문","요3:16",0),("theme","주제","",0),("goal","목표","",0)]),
 ("다음세대(주일학교)","exam-cheer","시험 응원 카톡","💪",[("exam","시험명","중간고사",0),("dept","부서(전체는 비움)","",0)]),
 ("다음세대(주일학교)","event-plan","수련회·여름사역 기획서","⛺",[("title","수련회·행사명","여름수련회",1),("date","일시","",0),("place","장소","",0),("theme","주제","",0),("host","담당","",0)]),
 ("다음세대(주일학교)","ref-summer","여름성경학교·수련회 준비 📖","⛺",[]),
 ("다음세대(주일학교)","vbs","여름 성경학교(수련회) 공과 (7주제) 📖","📖",[("no","주제 번호를 적으세요 1~7 (비우고 실행하면 1과)","","")],"여름 성경학교·수련회용 7주제 공과를 한 카드에 — 칸에 1~7 중 하나를 적고 실행하면 그 공과가 열립니다. 1창조·2복음·3동행·4사랑섬김·5믿음·6기도·7제자도."),
 ("다음세대(주일학교)","ref-ss","주일학교 지도자료 📖","🧸",[]),
 ("다음세대(주일학교)","ref-vision","청소년 비전코칭(진로·소명) 📖","🧭",[],"진로가 막막한 청소년을 돕는 비전코칭 — 강점 발견·소명 세우기·1:1 진행안·상황별 코칭·부록 7종."),
 ("다음세대(주일학교)","ref-worldview","기독교 세계관 교육 📖","🌍",[],"세속 문화 속 청소년을 위한 성경적 세계관 — 창조·타락·구속·완성, 주제 10개, 10주 커리큘럼, 미디어 분별 훈련."),
 ("행정서식","annual-plan","연간 사역 계획표","📅",[("year","연도","2026",0)],"월별 절기·주요 사역을 한 장으로. 우리 교회 계획 기입란 포함(절기는 그 해 달력 확인)."),
 ("행정서식","meeting-minutes","회의록","🗒️",[("type","종류(제직회/공동의회/당회/교사회)","제직회",0),("date","날짜","",0),("place","장소","",0),("host","사회","",0),("clerk","서기","",0),("attend","참석(;로 구분)","",0),("absent","불참(;로 구분)","",0),("agenda","안건(;로 구분)","",0)]),
 ("행정서식","official-doc","공문(협조문)","📄",[("to","수신","",1),("title","제목","",1),("body","본문(;로 구분)","",0),("via","경유","",0),("sender","발신(비우면 담임)","",0),("date","날짜","",0)]),
 ("행정서식","asset-register","비품대장","📦",[("name","품목(비우면 대장만)","",0),("qty","수량","1",0),("place","위치","",0),("manager","담당","",0),("status","상태","사용",0),("date","구입일","",0)]),
 ("행정서식","vehicle-log","차량운행일지","🚗",[("driver","운전자","",0),("dest","행선지","",0),("km","거리(km)","",0),("fuel","주유","",0),("date","일자","",0)]),
 ("예배·설교","calendar","교회력·절기","✝️",[("year","연도","2026",0)]),
 ("예배·설교","cal-open","🗓️ 일정 캘린더","🗓️",[],"탁상 달력처럼 월별 일정을 봅니다. 날짜를 눌러 행사를 기록하고, ★ 중요한 날은 대시보드에도 뜹니다."),
 ("찬양","setlist","찬양 콘티","🎶",[("songs","곡목(;로 구분)","",1),("size","용지(A4/A3)","A4",0),("title","콘티 제목","",0)]),
 ("찬양","compose","AI 찬양 작곡 (수노·작업지) 🎼","🎼",[("title","곡 제목","새 찬양",1),("theme","주제(예: 은혜·감사·부흥)","",0),("bible","성경 본문(예: 시 103편)","",0),("mood","분위기(예: 은혜롭고 벅찬)","",0),("key","조(Key)","G",0),("bpm","BPM","72",0),("lyrics","가사(직접 쓰면 그대로·비우면 틀만)","",0)],"★찬양 한 곡을 만들기 위한 작업지를 만들어 드립니다 — 가사 틀(1절·후렴·2절·브릿지) + 수노(Suno)·유디오(Udio) 같은 무료 음악 AI에 그대로 붙여넣는 영어 프롬프트까지. 작업지의 프롬프트를 복사해 수노(suno.com, 무료)에 붙여넣으면 실제 멜로디·음원이 만들어집니다. 완성곡을 유튜브에 올린 뒤 '찬양곡·자작곡 등록'에 링크를 넣으면 찬양 콘티에 자동 반영됩니다. ※가사는 직접 창작하므로 저작권 걱정이 없습니다."),
 ("찬양","song-add","찬양곡·자작곡 등록","🎼",[("title","곡명","",1),("composer","작곡가","",0),("key","조(Key)","D",0),("bpm","BPM","72",0),("youtube","유튜브 링크","",0),("lyrics","가사","",0)]),
 ("찬양","song-sheet","작곡 곡 악보 열기","🎼",[("title","곡 제목","",1)]),
 ("찬양","song-catalog","찬양 작품집","🏆",[("title","제목","",0)]),
 ("영상·홍보","video-plan","행사 홍보영상 기획·대본 (만들 준비) 🎬","🎬",[("title","행사·영상 제목","여름성경학교",1),("purpose","목적·대상(예: 지역 어린이 초청)","",0),("message","핵심 메시지(자막)","올여름, 아이들이 예수님을 만납니다",0),("when","일시·장소(자막)","",0),("cta","신청·문의(자막)","",0),("length","길이(초·짧게 30초~3분)","30",0),("tone","톤·분위기(예: 활기찬/따뜻한)","따뜻하고 설레는",0),("aspect","화면(가로=유튜브 / 세로=릴스·밴드)","가로",0)],"★홍보영상을 만들기 위한 '작업지'를 만들어 드립니다 — 스토리보드 5장면 + 자막 대본 + 장면별 촬영 안내 + 영상AI 프롬프트 3종 + 무료 편집기 조립 순서까지 한 장에. 이 작업지대로 무료 편집기(Clipchamp·Canva·CapCut)로 만들면 완성됩니다(→ '무료 영상편집·영상 AI 완전 가이드' 카드 참고). 영상 다룰 줄 몰라도 순서만 따라오시면 됩니다. ※사진만 넣으면 자동으로 영상까지 만들어 주는 기능은 다음 업데이트에 정식 지원 예정입니다."),
 ("영상·홍보","ref-video","홍보영상 편집·영상 AI 완전 가이드 📖","📖",[],"홍보·행사 영상을 만드는 법 — Clipchamp·Canva·CapCut 등 무료 편집기와 Runway·Pika·Kling 등 영상 AI 사용법, 목적별 홍보영상 템플릿, 저작권 안전 음원까지 총정리."),
 ("영상·홍보","sermon-slides","설교 슬라이드(PPT) 만들기 📊","📊",[("title","설교 제목","주일 설교",1),("text","본문 성구(예: 요 3:16)","",0),("theme","주제","",0),("points","설교 대지(; 로 구분)","",0)],"설교 제목·본문 성경구절·대지를 넣으면 예배 프로젝터·화면공유용 슬라이드(PPT)를 자동으로 만들어 드립니다."),
 ("영상·홍보","ref-worshipvid","예배·설교 영상 — 녹화·유튜브 라이브 완전 가이드 📖","📡",[],"예배·설교를 영상으로 전하는 모든 것 — 1부 녹화·자막·유튜브 업로드·짧은 요약영상, 2부 실시간 방송(Prism Live·OBS 단계별)·유튜브 라이브 켜기·소리·온라인 성도 돌봄·CCLI 저작권까지. 영상·방송이 처음이어도 OK."),
 ("찬양","songbook","찬양집(악보집) 출판","📔",[("songs","곡목(;, 전체는 비움)","",0),("title","제목","",0)]),
 ("찬양","worship-roster","찬양팀 배정표","🎹",[("date","날짜","2026-01-01",0),("leader","인도","",0),("keys","건반","",0),("guitar","기타","",0),("bass","베이스","",0),("drums","드럼","",0),("singers","싱어","",0)]),
 ("찬양","production-add","뮤지컬·공연 등록","🎭",[("title","작품","",1),("date","공연일","",0),("place","장소","",0),("director","연출","",0),("music","음악감독","",0)],"찬양 뮤지컬·공연을 등록합니다(작품·공연일·연출·음악감독)."),
 ("찬양","casting","공연 배역(캐스팅)","🎬",[("title","작품","",1),("date","공연일","",0),("roles","배역(;로 구분)","",0)],"뮤지컬·공연의 배역(캐스팅)을 정리합니다."),
 ("사역","schedule-add","집회·외부 일정 (등록 & 목록)","📅",[("place","장소/교회 (비우면 일정 목록 보기)","",0),("date","날짜","",0),("type","유형(집회/외부설교/행사/찬양사역)","집회",0),("theme","주제","",0),("host","담당","",0),("fee","사례","",0),("upcoming","목록에서 다가오는것만(1)","1",0)],"장소·주제 등을 넣으면 집회·외부 일정을 등록하고, 비우면 일정 목록(D-day 표시)을 봅니다."),
 ("선교","ref-mission","단기선교·비전트립 준비 📖","🌏",[],"8주 사전훈련·안전·서류·재정·현지사역·이주민선교까지 담은 단기선교 실전 참고자료입니다."),
 ("선교","mission-plan","선교 준비 (타임라인·체크리스트)","✈️",[("title","팀명","단기선교",1),("dday","출국일(예: 2026-08-04)","",0)],"팀명·출국일을 넣으면 D-day 준비 타임라인 + 준비 체크리스트(여권·비자·예방접종·짐·사역·안전)를 한 번에 만들어 드립니다."),
 ("선교","ref-me","선교지 선교영어 📖","🗣️",[],"선교지에서 바로 쓰는 상황별 선교 영어 — 인사·전도·기도·생활 표현."),
 ("사역","event-plan","대외행사 기획서","🎪",[("title","행사명","",1),("date","일시","",0),("place","장소","",0),("theme","주제","",0)]),
 ("사역","presbytery-add","노회 관련","⛪",[("kind","구분(회의/서류/노회비)","회의",0),("note","내용","",1),("role","담당직무","",0),("due","기한","",0)]),
 ("선교","mission-field","선교 현지정보 시트","🗺️",[("title","선교 팀명","",1)],"선교사·숙소·식당·사역지 연락처와 일자별 장소 계획을 한 장으로 정리합니다."),
 ("재정","finance-add","재정 기록 & 요약 (수입/지출)","💵",[("kind","구분(수입/지출)","수입",0),("item","항목 — 수입:십일조·감사·선교·건축 / 지출:인건비·시설·공과금·행사","십일조",0),("name","교인(헌금자·선택)","",0),("dept","부서(선택·예: 선교부/교육부/찬양)","",0),("amount","금액(숫자만·비우면 요약 보기)","",0),("month","요약 볼 월(YYYY-MM·비우면 전체)","",0)],"금액을 넣으면 수입/지출을 기록하고(부서 넣으면 부서별 회계 집계), 금액을 비우면 재정 요약을 봅니다."),
 ("재정","finance-chart","재정 그래프·통계 📊","📊",[],"★재정을 그래프로 한눈에 — 월별 수입·지출 추이(막대), 헌금 종류·지출 항목 비중(도넛), 예산 대비 집행률(게이지), 부서별 집계. 전문 재정프로그램을 넘어서는 시각화 대시보드입니다."),
 ("재정","giving-ledger","교인별 헌금대장","🧾",[("name","교인(전체는 비움)","",0),("year","연도","",0)]),
 ("재정","donation-receipt","기부금영수증","🧧",[("name","교인","",1),("year","연도","2026",0)]),
 ("재정","finance-report","주일 재정 결산서 (+연간 총결산)","🧮",[("date","결산 주일(YYYY-MM-DD·비우면 오늘)","",0),("year","연간 총결산 볼 연도(YYYY·넣으면 그 해 전체)","",0),("dfrom","기간시작","",0),("dto","기간끝","",0)],"주일(또는 기간) 재정 결산서. '연도'를 넣으면 그 해 연간 총결산(월별 합계·헌금종류·지출항목·부서별)을 만들어 드립니다."),
 ("재정","finance-ledger","재정 출납부(원장)","📒",[("month","월(YYYY-MM·비우면 이번달)","",0),("year","연도(YYYY·연간)","",0),("dfrom","기간시작","",0),("dto","기간끝","",0)]),
 ("재정","finance-items","헌금·지출 항목표","📋",[]),
 ("재정","budget-plan","예산안 편성 양식 📋","🧾",[("year","편성 연도(YYYY·비우면 올해)","",0)],"작년 실적을 참고칸에 자동으로 채운 금년 예산안 표 — 제직회·공동의회 심의용. 이 표로 예산을 정한 뒤 '예산 편성' 카드에 입력하세요."),
 ("재정","budget-set","예산 편성 & 집행현황","🧮",[("year","연도(YYYY·비우면 올해)","",0),("kind","구분(수입/지출)","수입",0),("item","항목(비우면 집행현황 보기 · 예: 십일조/인건비)","",0),("amount","예산액(숫자만·0 삭제)","",0)],"항목을 넣으면 연간 예산을 항목별로 편성하고, 항목을 비우면 예산 대비 집행현황(항목별 집행률·잔액·초과)을 봅니다. 전문가급 예산 관리."),
 ("출력·파일","ppt","찬양 가사 PPT","📽️",[("songs","곡목(;로 구분)","",1),("title","제목","",0)]),
 ("출력·파일","lyrics-screen","가사 스크린(문서)","🖥️",[("songs","곡목(;로 구분)","",1),("title","제목","",0)]),
 ("출력·파일","hwp","한글(.hwp) 변환","📄",[("recent","최근 몇 개(기본10)","10",0)]),
 ("출력·파일","print-file","프린터 출력","🖨️",[("file","파일 경로","",1)]),
 ("출력·파일","open-file","내 파일·작업물 찾아 열기","📁",[("name","파일 이름 검색 (비우면 종류별 목록)","",0),("kind","종류(설교/심방/주보/묵상/찬양/악보/증명서/재정/교안·비우면 전체)","",0)],"파일 이름을 넣으면 프로그램·D폴더·USB에서 찾아 열고, 비우면 종류별 내 작업물을 최근순 목록(눌러 열기)으로 보여줍니다."),
 ("출력·파일","nlm-add","NotebookLM에 자료 올리기 (성경주석·찬양작곡 등)","☁️",[("file","올릴 파일 경로(주석·찬양곡·자료)","",1),("book","성경책(예: 로마서·롬·히브리서 — 자동 연결)","",0),("notebook","노트북ID(직접 지정할 때만)","",0)]),
 ("출력·파일","read-file","파일 읽기(TXT/DOCX)","📄",[("file","파일 경로","",1)]),
 ("시스템","why","✨ 이 프로그램의 강점","✨",[],"교인정보 보안·데이터 통합·전문가급 재정 등, 이 프로그램만의 강점을 한눈에 봅니다. 작은 교회 목사님을 위한 정성입니다."),
 ("시스템","setup","⛪ 우리 교회 이름 설정 (맨 처음 한 번)","⛪",[("church","우리 교회 이름","예: 은혜교회",1),("pastor","담임 목사님 성함","예: 홍길동 목사",0)],"교회명·담임명만 넣으면 모든 문서·주보·증명서·축하 문자에 자동으로 들어갑니다. 어려운 설정 파일을 직접 여실 필요가 없어요."),
 ("시스템","set-backup","USB·D 백업 (설정 & 지금 저장)","📦",[("path","저장 폴더(예: E:\\교회백업 · 비우면 설정된 폴더로 지금 저장)","",0)],"저장 폴더를 넣으면 자동저장 폴더로 설정하고 즉시 전체 저장합니다. 비우면 이미 설정된 폴더로 지금 전체 저장. USB·D폴더에 안전 이중보관."),
 ("시스템","backup","자료 백업","💾",[]),
 ("시스템","phoenix","🔥 피닉스 복구","🔥",[("last","최근으로 복구하려면 1","",0)]),
 ("시스템","version","버전·업데이트 확인","🔔",[]),
 ("시스템","manual","사용 설명서 만들기","📘",[]),
 ("시스템","export-excel","엑셀 관리대장","📗",[]),
]

PAGE = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>__CHURCH__ 교회행정</title>
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
  @media (max-width:900px){.app{grid-template-columns:1fr}.side{display:none}.stats{grid-template-columns:repeat(2,1fr)}.search{width:auto;flex:1}.top{padding:15px 20px}.wrap{padding:26px 20px 48px}}

  /* ── 실행 모달·입력폼·결과 (기존 JS 기능 유지 · 프리미엄 토큰 적용) ── */
  .modal{position:fixed;inset:0;background:rgba(10,12,20,.55);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;padding:18px;z-index:20}
  .modal.on{display:flex}
  .sheet{background:var(--surface);border:1px solid var(--line);border-radius:18px;max-width:540px;width:100%;max-height:88vh;overflow:auto;padding:30px;box-shadow:var(--shadow)}
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
    <div class="credit" style="padding:11px 14px 14px;font-size:11.5px;line-height:1.6;color:var(--muted);border-top:1px solid var(--line-2)"><b style="color:var(--ink)">제작 · 저작권 ⓒ 2026 김용원 (세움교회)</b><br>목회 목적 사용 자유 · 무단 복제 · 재판매 금지</div>
  </aside>

  <div class="main">
    <header class="top">
      <div><h1>대시보드</h1></div>
      <div class="date" id="today"></div>
      <div class="search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="search" placeholder="교인·설교·재정·서식 검색"><span class="kbd">Ctrl K</span></div>
      <button class="upd" onclick="updateApp()" title="최신 버전으로 안전 업데이트 (자료 보존)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v11M8 10l4 4 4-4M5 21h14"/></svg>업데이트</button>
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
      <div class="lede">
        <div>
          <h2>평안하세요, 목사님 🙏</h2>
          <p>필요한 기능을 바로 실행하세요. 왼쪽 메뉴에서 분류로 이동할 수 있습니다.</p>
        </div>
      </div>

      <!-- 요약 대시보드: 현재는 정적 플레이스홀더(실측 데이터 아님).
           TODO(batch C): church.py 연동 — 등록교인=명부 count · 이번주 심방=visit-* · 주일헌금=finance-sum · 다가오는 생일=birthday/anniversary -->
      <div class="stats">
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

      <div class="foot">자료는 내 컴퓨터에 안전 저장 · <b>버전 v__VERSION__ (재정 출납부·원장)</b><br>
        <button class="quit" onclick="quitApp()">⏻ 프로그램 종료</button></div>
    </div>
  </div>
</div>
<div class="modal" id="welcome"><div class="sheet">
 <h2>👋 환영합니다, 목사님!</h2><div class="sub">__CHURCH__ 교회 종합행정</div>
 <p>위쪽 <b>카드</b>를 누르면 바로 사용됩니다. 만든 문서는 번호 폴더에 자동 정리되고, 입력한 자료는 <b>영구 보존</b>됩니다. 처음이시면 아래 <b>사용 설명서</b>를 먼저 만들어 읽어보세요.</p>
 <div class="row"><button class="b cancel" onclick=closeW()>바로 시작</button><button class="b go" onclick="openWhy()">✨ 이 프로그램의 강점</button><button class="b go" onclick=makeManual()>📘 사용 설명서 만들기</button></div>
 <div class="out" id="wout"></div>
</div></div>
<div class="modal" id="modal"><div class="sheet">
 <h2 id="mt"></h2><div class="sub" id="ms"></div><div id="mf"></div>
 <div class="row"><button class="b cancel" onclick=closeM()>닫기</button><button class="b go" id="mgo">실행</button></div>
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
<div class="modal" id="whymodal"><div class="sheet">
 <h2>✨ 이 프로그램의 강점</h2><div class="sub">작은 교회 목회, 이 한 곳에서</div>
 <div style="background:var(--brand-soft);border:1px solid var(--line);border-radius:12px;padding:13px 15px;margin:12px 0;font-size:14px;line-height:1.65;color:var(--ink)">🔒 <b>교인 정보는 목사님 컴퓨터 안에서만.</b> 교인 명단·심방기록·헌금내역 같은 소중한 정보를 외부 온라인 서비스에 올리지 않고, 목사님 PC 안에서 안전하게 관리하고 활용합니다.</div>
 <div style="font-size:14px;line-height:1.65;color:var(--ink)">
  <div style="padding:9px 4px;border-bottom:1px solid var(--line-2)">📇 <b>쌓이고 연결됩니다</b> — 교적·심방·생일·헌금·결산이 하나로 이어져, 쓸수록 브리핑과 통계가 정확해집니다.</div>
  <div style="padding:9px 4px;border-bottom:1px solid var(--line-2)">📝 <b>누르면 완성되는 서식</b> — 설교문·주보·증명서·결산서를 한글 문서로 클릭 한 번에.</div>
  <div style="padding:9px 4px;border-bottom:1px solid var(--line-2)">💰 <b>전문가급 재정</b> — 계산기처럼 정확한 결산에 그래프·부서별 회계·연간 총결산까지.</div>
  <div style="padding:9px 4px">📚 <b>내 서재로 하는 설교연구</b> — 목사님이 모으신 주석·장서를 바탕으로 깊이 있게(NotebookLM 연동).</div>
 </div>
 <p style="font-size:14.5px;margin:14px 2px 2px;color:var(--ink)">흩어진 목회 실무를 <b>한 곳에서</b> — 작은 교회 목사님을 위한 정성입니다.</p>
 <div class="row"><button class="b go" onclick="closeWhy()">닫기</button></div>
</div></div>
<button class="home" id="homebtn" onclick="goHome()">⌂ 전체 메뉴</button>
<script>
var A=__ACTIONS__;
var NETERR='⚠ 프로그램 서버에 연결할 수 없습니다.'+String.fromCharCode(10)+'★ 교회행정 시작 파일을 다시 더블클릭(실행)한 뒤,'+String.fromCharCode(10)+'이 창을 새로고침(F5)하고 다시 눌러주세요.';
function isNet(e){var s=String(e);return s.indexOf('fetch')>=0||s.indexOf('Failed')>=0||s.indexOf('NetworkError')>=0;}
var COLORS={"목양":"#10b981","예배·설교":"#f43f5e","성례":"#0ea5e9","성경자료":"#6366f1","목회 참고자료":"#8b5cf6","다음세대(주일학교)":"#ec4899","영성":"#7c3aed","찬양":"#8b5cf6","영상·홍보":"#c026d3","사역":"#f59e0b","전도":"#16a34a","선교":"#0d9488","재정":"#3b82f6","행정서식":"#0891b2","출력·파일":"#14b8a6","시스템":"#64748b"};
var GROUP_ICON={"목양":"🙌","예배·설교":"✝️","성례":"💧","성경자료":"📖","목회 참고자료":"📚","다음세대(주일학교)":"🎒","영성":"✝️","행정서식":"🗂️","찬양":"🎶","영상·홍보":"🎬","사역":"📅","전도":"🌾","선교":"🌏","재정":"💵","출력·파일":"📂","시스템":"⚙️"};
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
function render(q){
 app.innerHTML='';q=(q||'').toLowerCase();
 GROUPS.forEach(function(g){
  var items=A.filter(function(a){return a[0]===g && (!q || (a[1]+a[2]).toLowerCase().indexOf(q)>=0);});
  if(!items.length)return;
  var col=COLORS[g]||'#6366f1';var gi=GROUPS.indexOf(g);
  var h=document.createElement('div');h.className='sec-h';h.id='sec'+gi;
  h.innerHTML='<span class="dotm" style="background:'+col+'"></span><h3>'+esc(g)+'</h3><span class="cnt">'+items.length+'개 기능</span><span class="rule"></span>';
  app.appendChild(h);
  var grid=document.createElement('div');grid.className='grid';
  var SUB=SUBGROUPS[g];
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
   d.innerHTML=(feat?'<span class="badge">추천</span>':'')+'<div class="ci" style="color:'+cc+';background:color-mix(in srgb,'+cc+' 15%,transparent)">'+a[3]+'</div><h4>'+esc(a[2])+'</h4><p>'+esc(a[5]||a[1])+'</p><span class="go">→</span>';
   d.onclick=function(){openM(a);};grid.appendChild(d);
  });
  app.appendChild(grid);
 });
}
buildNav();render('');
function _setTx(id,v){var e=document.getElementById(id);if(e)e.textContent=v;}
function _fmt(n){try{return (Number(n)||0).toLocaleString('ko-KR');}catch(e){return n;}}
function briefBday(){runQuick('birthday',{days:'0'},'🌅 오늘 생일·기념일 축하');}
function briefCare(){runQuick('care',{},'🧭 돌봄 필요 성도');}
function briefNew(){runQuick('newcomer',{},'🌱 새가족 정착 현황');}
function brow(ic,cls,title,sub,badge,bcls,fn){
 return '<div class="brow" onclick="'+fn+'()"><div class="ic '+cls+'">'+ic+'</div><div class="tx"><b>'+esc(title)+'</b><s>'+esc(sub)+'</s></div><span class="bdg '+bcls+'">'+esc(badge)+'</span><span class="go2">→</span></div>';
}
function loadStats(){
 fetch('/stats').then(function(r){return r.json();}).then(function(s){
  _setTx('st_mem',_fmt(s.교인)+'명');
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
  if(s.새가족){H+=brow('🌱','nw','정착 중 새가족 '+s.새가족+'명','최근 90일 등록 — 정착까지 함께','새가족','nw','briefNew');}
  var bp=document.getElementById('brief'),br=document.getElementById('brief_rows');
  if(br&&bp){br.innerHTML=H||'<div class="brief-empty">오늘은 특별히 챙길 목양 알림이 없습니다. 평안한 하루 되세요 🙏</div>';bp.style.display='';}
 }).catch(function(){});
}
function runQuick(cmd,args,title){
 cur=['',cmd,title||cmd,'▶',[]];
 _setTx('mt',title||cmd);_setTx('ms','');document.getElementById('mf').innerHTML='';
 var o=document.getElementById('mo');o.className='out on';o.textContent='실행 중...';
 document.getElementById('modal').classList.add('on');
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:cmd,args:args})})
  .then(function(r){return r.text();}).then(function(t){o.className='out on ok';renderOut(o,t);loadStats();})
  .catch(function(e){o.className='out on';o.textContent=isNet(e)?NETERR:'오류: '+e;});
}
loadStats();
function checkUpdate(){
 fetch('/updatecheck').then(function(r){return r.json();}).then(function(u){
  var b=document.querySelector('.upd');if(!b)return;
  if(u&&u['new']){
   b.classList.add('has-new');
   if(!b.querySelector('.updbadge')){var s=document.createElement('span');s.className='updbadge';s.textContent='NEW';b.appendChild(s);}
   b.title='새 업데이트'+(u.version?(' '+u.version.split(' ')[0]):'')+' 있음 — 눌러서 업데이트하세요'+(u.notes?(String.fromCharCode(10)+u.notes):'');
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
function openM(a){if(a[1]==='why'){openWhy();return;}if(a[1]==='cal-open'){openCal();return;}if(a[1]==='finance-chart'){openFinance();return;}cur=a;document.getElementById('mt').textContent=a[3]+' '+a[2];
 document.getElementById('ms').textContent=a[1];
 var mf=document.getElementById('mf');mf.innerHTML='';
 a[4].forEach(function(f){var n=f[0],label=f[1],ph=f[2],req=f[3];
  var l=document.createElement('label');l.textContent=label+(req?' *':'');mf.appendChild(l);
  var big=(n==='lyrics'||n==='note'||n==='body'||n==='notice'||n==='week'||n==='goal'||n==='purpose');
  var inp=document.createElement(big?'textarea':'input');inp.className='f';inp.id='fld_'+n;inp.placeholder=ph;mf.appendChild(inp);
 });
 var o=document.getElementById('mo');o.className='out';o.textContent='';
 document.getElementById('modal').classList.add('on');
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
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'event-add',args:{date:ym,title:t,important:imp}})}).then(function(){renderCal();if(typeof loadStats==='function')loadStats();});
}
function delEvent(e,id,title){
 e.stopPropagation();if(!confirm('"'+title+'" 일정을 삭제할까요?'))return;
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'event-del',args:{id:id}})}).then(function(){renderCal();if(typeof loadStats==='function')loadStats();});
}
function calPrint(){var ym=calY+'-'+('0'+calM).slice(-2);closeCal();runQuick('cal-print',{month:ym},calY+'년 '+calM+'월 일정 달력 인쇄');}
document.getElementById('mgo').onclick=function(){
 var args={},miss=null;cur[4].forEach(function(f){var v=document.getElementById('fld_'+f[0]).value.trim();if(v)args[f[0]]=v;else if(f[3]&&!miss)miss=f[1];});
 var o=document.getElementById('mo');
 if(miss){o.className='out on';o.textContent='⚠ "'+miss+'" 칸을 먼저 입력해 주세요.';return;}
 o.className='out on';o.textContent='실행 중...';
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:cur[1],args:args})})
  .then(function(r){return r.text();}).then(function(t){o.className='out on ok';renderOut(o,t);loadStats();})
  .catch(function(e){o.className='out on';o.textContent=isNet(e)?NETERR:'오류: '+e;});
};
function baseName(p){var a=p.split('/');p=a[a.length-1];var b=p.split(String.fromCharCode(92));return b[b.length-1];}
function findPath(line){var low=line.toLowerCase();var exts=['.docx','.hwp','.hwpx','.xlsx','.pptx','.pdf','.txt'];var end=-1,el=0;
 for(var i=0;i<exts.length;i++){var p=low.lastIndexOf(exts[i]);if(p>end){end=p;el=exts[i].length;}}
 if(end<0)return null;end+=el;var start=-1;
 for(var j=end-1;j>0;j--){var c=line.charAt(j),pv=line.charAt(j-1);if(c===':'&&((pv>='A'&&pv<='Z')||(pv>='a'&&pv<='z'))){start=j-1;break;}}
 if(start<0)return null;return line.substring(start,end);}
function parentDir(p){var i=Math.max(p.lastIndexOf('/'),p.lastIndexOf(String.fromCharCode(92)));return i>0?p.substring(0,i):p;}
function addOpen(o,path,label,icon,tail){var b=document.createElement('button');b.className='fileopen';b.textContent=(icon||'📂')+' '+(label||baseName(path))+(tail||' — 눌러서 열기');b.onclick=function(){openPath(path,b);};o.appendChild(b);}
function renderOut(o,t){o.innerHTML='';(t||'완료').split(String.fromCharCode(10)).forEach(function(line){
  var m=line.match(/^▶열기[|](.+?)[|](.+)$/);
  if(m){addOpen(o,m[1],m[2],'📂','');return;}
  var d=document.createElement('div');d.textContent=line;o.appendChild(d);
  var fp=findPath(line);
  if(fp){addOpen(o,fp,null,'📂',' — 이 문서 열기');addOpen(o,parentDir(fp),'이 파일이 있는 폴더','🗂️',' 열기');}
});}
function openPath(p,btn){if(btn)btn.textContent='📂 '+baseName(p)+' 여는 중...';
  fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'open-file',args:{file:p}})})
   .then(function(r){return r.text();}).then(function(t){if(btn)btn.textContent='📂 '+baseName(p)+' — '+(t.indexOf('여는')>=0?'열렸습니다':t.slice(0,40));}).catch(function(e){if(btn)btn.textContent=isNet(e)?'⚠ 서버 꺼짐 — ★교회행정 시작 다시 실행':'오류';});
}
function browsePrev(btn){var L='📂 지난 자료 찾기 — 내 PC(C·D·USB)에서 예전 작업 열기';if(btn)btn.textContent='📂 내 PC 여는 중...';
  fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'open-file',args:{file:'shell:MyComputerFolder'}})})
   .then(function(r){return r.text();}).then(function(){if(btn){btn.textContent='📂 내 PC 열림 — C·D·USB에서 예전 자료를 찾으세요';setTimeout(function(){btn.textContent=L;},4500);}}).catch(function(e){if(btn)btn.textContent=isNet(e)?'⚠ 서버 꺼짐 — ★교회행정 시작 다시 실행':'오류';});
}
document.getElementById('modal').onclick=function(e){if(e.target.id==='modal')closeM();};
function closeW(){document.getElementById('welcome').classList.remove('on');try{localStorage.setItem('seen2','1');}catch(e){}}
function makeManual(){var o=document.getElementById('wout');o.className='out on';o.textContent='설명서 만드는 중...';
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'manual',args:{}})})
  .then(function(r){return r.text();}).then(function(t){o.className='out on ok';o.textContent=t+' — 01 교회 기본·조직 폴더에서 [사용설명서] 파일을 여세요.';})
  .catch(function(e){o.textContent=isNet(e)?NETERR:'오류: '+e;});}
function quitApp(){if(!confirm('프로그램을 종료할까요?'))return;
 fetch('/shutdown',{method:'POST'}).catch(function(){});
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
  fetch('/bgupload',{method:'POST',body:JSON.stringify({name:f.name,data:rd.result})}).then(function(r){return r.json();}).then(function(j){
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
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'update',args:{}})})
  .then(function(r){return r.text();}).then(function(t){o.className='out on ok';renderOut(o,t);
    if(t.indexOf('업데이트 완료')>=0){setTimeout(function(){location.reload(true);},6000);}})
  .catch(function(e){o.className='out on';o.textContent=isNet(e)?NETERR:'오류: '+e;});
}
(function(){var el=document.getElementById('today');if(!el)return;var d=new Date();var w=['일','월','화','수','목','금','토'][d.getDay()];el.textContent=d.getFullYear()+'년 '+(d.getMonth()+1)+'월 '+d.getDate()+'일 ('+w+'요일)';})();
(function(){var p=document.getElementById('pastorName');var a=document.getElementById('avatarInit');if(p&&a){var t=(p.textContent||'').trim();if(t)a.textContent=t.charAt(0);}})();
try{if(!localStorage.getItem('seen2'))document.getElementById('welcome').classList.add('on');}catch(e){}
</script>
</body></html>"""

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
def run_cmd(cmd, args):
    argv=[PYEXE, CHURCH_PY, cmd]
    for k,v in args.items(): argv+= ["--"+k, str(v)]
    env=dict(os.environ); env["PYTHONIOENCODING"]="utf-8"; env["CHURCH_WEB"]="1"
    tmo=600 if cmd in ("video-plan","video-render","nlm-add") else 120   # 영상·NLM 업로드는 시간이 더 걸림(큰 PDF 업로드·처리)상 대비)
    try:
        r=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=tmo,env=env,cwd=BASE)
        shown=[]; opened=0
        for ln in (r.stdout or "").split("\n"):     # 생성 파일은 부모(웹서버)가 확실히 연다
            if ln.startswith("__OPENFILE__"):
                try: os.startfile(ln[len("__OPENFILE__"):].strip()); opened+=1
                except Exception: pass
            else: shown.append(ln)
        _beep(r.returncode==0)
        return "\n".join(shown)+(("\n[오류]\n"+r.stderr) if r.returncode!=0 and r.stderr else "")
    except Exception as e:
        _beep(False)
        return f"실행 오류: {e}"

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _send(self,body,ct="text/html; charset=utf-8"):
        b=body.encode('utf-8'); self.send_response(200)
        self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(b)))
        self.send_header("Cache-Control","no-store, must-revalidate")
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
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
              .replace("__ACTIONS__",json.dumps(ACTIONS,ensure_ascii=False)))
        self._send(page)
    def do_POST(self):
        if self.path=="/shutdown":
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
            out=run_cmd(cmd, data.get("args",{}))
            if cmd=="update" and ("업데이트 완료" in out):
                out+="\n\n🔄 잠시 후 화면이 자동으로 새 버전으로 바뀝니다. (안 바뀌면 F5 또는 시작.bat 다시 실행)"
                import threading as _rt; _rt.Timer(1.6, _restart_self).start()
        except Exception as e:
            out="오류: "+str(e)
        self._send(out or "완료","text/plain; charset=utf-8")

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
def main():
    url=f"http://127.0.0.1:{PORT}/"
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
    _free_port(PORT)               # 옛 서버 강제 정리 → 항상 최신 코드로 기동
    httpd=None
    for _try in range(3):
        try:
            httpd=ThreadingHTTPServer(("127.0.0.1",PORT),H); break  # 멀티태스킹(동시 처리)
        except OSError:
            _free_port(PORT)
            import time as _t; _t.sleep(1.0)
    if httpd is None:
        print("포트를 열 수 없습니다. 브라우저만 엽니다..."); webbrowser.open(url); return
    print(f"■ {C.get('교회명','')} 교회행정 웹 대시보드 실행 중 → {url}")
    if not os.environ.get("CHURCH_NOOPEN"):   # 업데이트 자동 재시작 시엔 새 탭 안 엶(F5로 갱신)
        print("  브라우저가 자동으로 열립니다. 종료: 이 창을 닫으세요.")
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try: httpd.serve_forever()
    except KeyboardInterrupt: print("\n종료합니다.")

if __name__=="__main__": main()
